# social/consumers/message.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async



class DirectMessageConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        from django.contrib.auth.models import User
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        # Get the other user from URL parameters
        self.other_username = self.scope['url_route']['kwargs']['username']
        
        try:
            self.other_user = await self.get_user(self.other_username)
        except User.DoesNotExist:
            await self.close()
            return

        # Create a consistent room name for both users
        user_ids = sorted([self.user.id, self.other_user.id])
        self.room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        self.room_group_name = f"chat_{self.room_name}"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        print(f"✅ Direct message connected: {self.user.username} with {self.other_username} in room {self.room_group_name}")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        print(f"🔌 Direct message disconnected: {self.user.username}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'typing':
                # Broadcast typing indicator
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing_indicator',
                        'sender': self.user.username,
                        'is_typing': data.get('is_typing', False)
                    }
                )
        except json.JSONDecodeError:
            print("❌ Invalid JSON received")

    async def chat_message(self, event):
        """
        Handle incoming chat messages broadcast to the group.
        This is triggered by channel_layer.group_send()
        """
        print(f"📨 Sending message to WebSocket: {event.get('sender')} -> {event.get('receiver')}")
        
        # Send message to WebSocket client
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message_id': event.get('message_id'),
            'sender': event.get('sender'),
            'receiver': event.get('receiver'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'file_url': event.get('file_url'),
            'time': event.get('time'),
            'date_label': event.get('date_label'),
            'created_at': event.get('created_at')
        }))

    async def typing_indicator(self, event):
        """
        Handle typing indicators.
        Only send to the opposite user.
        """
        if event['sender'] != self.user.username:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'sender': event['sender'],
                'is_typing': event['is_typing']
            }))

    @database_sync_to_async
    def get_user(self, username):
        from django.contrib.auth.models import User
        return User.objects.get(username=username)