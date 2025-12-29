import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class OnlineStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return
        
        await self.accept()
        await self.mark_online()
        
        # Start heartbeat task that updates every second
        self.heartbeat_task = asyncio.create_task(self.send_heartbeats())
        
        # Send initial status
        await self.send_status("online")
    
    async def disconnect(self, close_code):
        await self.mark_offline()
        if hasattr(self, 'heartbeat_task'):
            self.heartbeat_task.cancel()
    
    async def receive(self, text_data):
        """Handle incoming messages - any message = user is active"""
        try:
            data = json.loads(text_data)
            if data.get('type') == 'ping':
                await self.update_ping()
                await self.send(json.dumps({'type': 'pong'}))
        except:
            await self.update_ping()
    
    async def send_heartbeats(self):
        """Send heartbeat every second to keep connection alive"""
        try:
            while True:
                await asyncio.sleep(1)  # Every second
                if self.user.is_authenticated:
                    await self.update_ping()
                    await self.send(json.dumps({
                        'type': 'heartbeat',
                        'timestamp': timezone.now().isoformat()
                    }))
        except asyncio.CancelledError:
            pass
    
    async def send_status(self, status):
        """Send status update"""
        await self.send(json.dumps({
            'type': 'status',
            'status': status,
            'user_id': self.user.id
        }))
    
    @database_sync_to_async
    def mark_online(self):
        from social.models import Profile
        """Mark user as online"""
        Profile.objects.filter(user=self.user).update(
            online=True,
            last_ping=timezone.now()
        )
    
    @database_sync_to_async
    def mark_offline(self):
        from social.models import Profile
        """Mark user as offline"""
        Profile.objects.filter(user=self.user).update(online=False)
    
    @database_sync_to_async
    def update_ping(self):
        from social.models import Profile
        """Update last ping timestamp"""
        Profile.objects.filter(user=self.user).update(
            last_ping=timezone.now(),
            online=True
        )