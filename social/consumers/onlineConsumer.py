import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class OnlineStatusConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = "online_status_group"
        self.disconnect_task = None

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.set_online(True)
        await self.broadcast_status("Online")

        # Send snapshot of all currently online users to this new connection
        online_users = await self.get_all_online_users()
        for uid in online_users:
            await self.send(text_data=json.dumps({
                'type': 'status_update',
                'user_id': uid,
                'status': 'Online',
            }))

    async def disconnect(self, close_code):
        if self.user.is_anonymous or not hasattr(self, 'group_name'):
            return

        if self.disconnect_task and not self.disconnect_task.done():
            self.disconnect_task.cancel()
            self.disconnect_task = None

        loop = asyncio.get_event_loop()
        self.disconnect_task = loop.create_task(self._delayed_offline())

        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def _delayed_offline(self):
        try:
            await asyncio.sleep(5)
            still_online = await self.is_still_online()
            if not still_online:
                await self.set_online(False)
                await self.broadcast_status("Offline")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type')

        if msg_type == 'request_snapshot':
            online_users = await self.get_all_online_users()
            for uid in online_users:
                await self.send(text_data=json.dumps({
                    'type': 'status_update',
                    'user_id': uid,
                    'status': 'Online',
                }))
            await self.send(text_data=json.dumps({
                'type': 'status_update',
                'user_id': self.user.id,
                'status': 'Online',
            }))

    @database_sync_to_async
    def is_still_online(self):
        from social.models import Profile
        try:
            return Profile.objects.get(user__id=self.user.id).online  # ← fixed
        except Profile.DoesNotExist:
            return False

    @database_sync_to_async
    def get_all_online_users(self):
        from social.models import Profile
        return list(
            Profile.objects.filter(online=True)           # ← fixed
                           .exclude(user__id=self.user.id)
                           .values_list('user__id', flat=True)
        )

    @database_sync_to_async
    def set_online(self, is_online):
        from social.models import Profile
        if is_online:
            Profile.mark_user_online(self.user.id)
        else:
            Profile.mark_user_offline(self.user.id)

    async def broadcast_status(self, status):
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'user_status_event',
                'user_id': self.user.id,
                'status': status,
            }
        )

    async def user_status_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'user_id': event['user_id'],
            'status': event['status'],
        }))
