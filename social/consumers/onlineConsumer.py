import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class OnlineStatusConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = "online_status_group"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.set_online(True)
        await self.broadcast_status("Online")

    async def disconnect(self, close_code):
        if self.user.is_anonymous or not hasattr(self, 'group_name'):
            return

        await self.set_online(False)
        await self.broadcast_status("Offline")
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Heartbeat ping — no DB hit needed, connection staying open is enough
        pass

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
