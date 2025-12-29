import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone



class OnlineStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if user.is_authenticated:
            await self.accept()
            await self.mark_online(user.id)
        else:
            await self.close()

    async def disconnect(self, close_code):
        user = self.scope["user"]
        if user.is_authenticated:
            await self.mark_offline(user.id)

    async def receive(self, text_data):
        """Any message = user is active"""
        user = self.scope["user"]
        if user.is_authenticated:
            await self.update_last_seen(user.id)

    @database_sync_to_async
    def mark_online(self, user_id):
        from social.models import Profile
        Profile.mark_user_online(user_id)

    @database_sync_to_async
    def mark_offline(self, user_id):
        from social.models import Profile
        Profile.mark_user_offline(user_id)

    @database_sync_to_async
    def update_last_seen(self, user_id):
        from social.models import Profile
        Profile.objects.filter(user_id=user_id).update(last_seen=timezone.now())