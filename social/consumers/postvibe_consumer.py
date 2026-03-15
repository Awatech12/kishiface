# social/consumers/postvibe_consumer.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db.models import Count


class PostVibeConsumer(AsyncWebsocketConsumer):
    """
    Real-time WebSocket consumer for post vibe reactions.

    Group name : post_vibes_{post_id}
    Every client viewing the same post joins the same group,
    so any vibe event is instantly broadcast to all of them.

    Flow
    ────
    1. Client connects  → joins group post_vibes_{post_id}
    2. Client sends     → { "action": "vibe", "vibe_type": "fire" }
    3. Consumer         → runs toggle_vibe() in DB thread pool
    4. Consumer         → group_send() broadcasts updated summary to ALL group members
    5. Every client     → receives vibe_update event and re-renders pills

    Vibe logic (one vibe per user per post)
    ────────────────────────────────────────
    • No existing vibe  → create  (action: added)
    • Same vibe again   → delete  (action: removed  — acts as toggle off)
    • Different vibe    → update  (action: changed)
    """

    # ──────────────────────────────────────────────────────────────────── #
    #  Connection lifecycle                                                 #
    # ──────────────────────────────────────────────────────────────────── #

    async def connect(self):
        self.post_id    = self.scope['url_route']['kwargs']['post_id']
        self.group_name = f'post_vibes_{self.post_id}'

        # Reject unauthenticated sockets early
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # ──────────────────────────────────────────────────────────────────── #
    #  Receive message from client                                          #
    # ──────────────────────────────────────────────────────────────────── #

    async def receive(self, text_data):
        user = self.scope.get('user')

        # Double-check auth (connection may have been accepted before auth expired)
        if not user or not user.is_authenticated:
            await self.send(json.dumps({'error': 'Authentication required'}))
            return

        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, ValueError):
            await self.send(json.dumps({'error': 'Invalid JSON'}))
            return

        action    = data.get('action', '')
        vibe_type = data.get('vibe_type', '').strip().lower()

        if action != 'vibe':
            await self.send(json.dumps({'error': f'Unknown action: {action}'}))
            return

        result = await self.toggle_vibe(user, vibe_type)

        if result['action'] == 'error':
            await self.send(json.dumps({'error': 'Invalid vibe type or post not found'}))
            return

        # Broadcast to ALL viewers of this post
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type':      'vibe_update',
                'post_id':   str(self.post_id),
                'summary':   result['summary'],
                'total':     result['total'],
                'actor_id':  user.id,
                'user_vibe': result['user_vibe'],   # None means vibe was removed
                'action':    result['action'],       # added | changed | removed
            }
        )

    # ──────────────────────────────────────────────────────────────────── #
    #  Group event handler — relay broadcast to this WebSocket             #
    # ──────────────────────────────────────────────────────────────────── #

    async def vibe_update(self, event):
        """Called for every member of the group when a vibe event fires."""
        await self.send(json.dumps({
            'type':      'vibe_update',
            'post_id':   event['post_id'],
            'summary':   event['summary'],   # { "fire": 3, "real": 1, ... }
            'total':     event['total'],     # sum of all vibes
            'actor_id':  event['actor_id'],  # user.id who triggered it
            'user_vibe': event['user_vibe'], # actor's current vibe (null = removed)
            'action':    event['action'],    # added | changed | removed
        }))

    # ──────────────────────────────────────────────────────────────────── #
    #  Database logic (runs synchronously inside thread pool)              #
    # ──────────────────────────────────────────────────────────────────── #

    @database_sync_to_async
    def toggle_vibe(self, user, vibe_type):
        """
        Toggle / switch / remove the user's vibe on this post.
        Returns a result dict consumed by receive() above.
        """
        from social.models import PostVibe, Post, Notification

        VALID_VIBES = {'fire', 'real', 'vibing', 'dead', 'cringe', 'chill'}

        if vibe_type not in VALID_VIBES:
            return {'summary': {}, 'total': 0, 'user_vibe': None, 'action': 'error'}

        # Fetch post
        try:
            post = Post.objects.get(post_id=self.post_id)
        except Post.DoesNotExist:
            return {'summary': {}, 'total': 0, 'user_vibe': None, 'action': 'error'}

        existing     = PostVibe.objects.filter(post=post, user=user).first()
        action_taken = 'added'
        user_vibe    = vibe_type

        if existing:
            if existing.vibe_type == vibe_type:
                # ── Toggle OFF — same vibe tapped again ──────────────────
                existing.delete()
                user_vibe    = None
                action_taken = 'removed'

                # Remove the like notification that was created when vibe was added
                Notification.objects.filter(
                    recipient=post.author,
                    actor=user,
                    post=post,
                    notification_type=Notification.LIKE,
                ).delete()

            else:
                # ── Switch to a different vibe ────────────────────────────
                existing.vibe_type = vibe_type
                existing.save(update_fields=['vibe_type'])
                action_taken = 'changed'
                # No notification change needed — user already notified on first vibe

        else:
            # ── Brand new vibe ────────────────────────────────────────────
            PostVibe.objects.create(post=post, user=user, vibe_type=vibe_type)
            action_taken = 'added'

            # Notify the post author (skip self-vibes)
            if post.author != user:
                Notification.objects.get_or_create(
                    recipient=post.author,
                    actor=user,
                    post=post,
                    notification_type=Notification.LIKE,
                )

        # ── Build fresh summary for broadcast ────────────────────────────
        rows = (
            PostVibe.objects
            .filter(post=post)
            .values('vibe_type')
            .annotate(count=Count('id'))
        )
        summary = {row['vibe_type']: row['count'] for row in rows}
        total   = sum(summary.values())

        return {
            'summary':   summary,
            'total':     total,
            'user_vibe': user_vibe,
            'action':    action_taken,
        }
