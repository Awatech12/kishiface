# social/consumers/inbox.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class InboxConsumer(AsyncWebsocketConsumer):
    """
    Personal inbox channel for each user.
    Each logged-in user connects here on the inbox page.
    When any DM is sent, message.py broadcasts an inbox_update
    to inbox_{sender} and inbox_{receiver} — this consumer
    forwards it to the browser so the inbox re-orders in real time.
    It also pushes the live unread DM count so the header badge
    stays accurate without any HTMX polling.
    """

    @database_sync_to_async
    def get_unread_count(self):
        from social.models import Message  # adjust import path to your project
        return Message.objects.filter(receiver=self.user, is_read=False).count()

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        self.inbox_group = f"inbox_{self.user.username}"
        await self.channel_layer.group_add(self.inbox_group, self.channel_name)
        await self.accept()

        # Push the current unread count immediately so the badge is accurate on load
        unread_count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'inbox_count',
            'unread_count': unread_count,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.inbox_group, self.channel_name)

    async def inbox_update(self, event):
        """Receive an inbox_update broadcast and forward it to the browser."""
        unread_count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'inbox_update',
            'sender': event.get('sender'),
            'sender_avatar': event.get('sender_avatar'),
            'receiver': event.get('receiver'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'time': event.get('time'),
            'unread_count': unread_count,
        }))
