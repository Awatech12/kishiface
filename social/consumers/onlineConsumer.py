import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class OnlineStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        
        # Check if user is logged in
        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = "online_status_group"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Update DB to Online and notify others
        await self.update_status(True)
        await self.broadcast_status("Online")

    async def disconnect(self, close_code):
        if not self.user.is_anonymous:
            # Update DB to Offline and notify others
            await self.update_status(False)
            await self.broadcast_status("Offline")
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Keep connection alive, ensure user is marked online
        await self.update_status(True)

    @database_sync_to_async
    def update_status(self, is_online):
        from social.models import Profile
        # Only update the online boolean
        Profile.objects.filter(user=self.user).update(online=is_online)

    async def broadcast_status(self, status):
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'user_status_event',
                'user_id': self.user.id,
                'status': status
            }
        )

    async def user_status_event(self, event):
        # Send update to the browser
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'user_id': event['user_id'],
            'status': event['status']
        }))