
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class DirectMessageConsumer(AsyncWebsocketConsumer):
    async def connect(self):
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
        
        # Create a unique room name for the conversation
        user_ids = sorted([self.user.id, self.other_user.id])
        self.room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        self.room_group_name = f"chat_{self.room_name}"
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"Direct message connected: {self.user.username} with {self.other_username}")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        print(f"Direct message disconnected: {self.user.username}")

    async def receive(self, text_data):
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
        
        elif action == 'mark_read':
            # Mark messages as read
            await self.mark_messages_as_read(self.user, self.other_user)

    async def direct_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message_id': event['message_id'],
            'sender': event['sender'],
            'receiver': event['receiver'],
            'message': event['message'],
            'file_type': event['file_type'],
            'file_url': event['file_url'],
            'time': event['time'],
            'date_label': event['date_label'],
            'created_at': event['created_at']
        }))

    async def typing_indicator(self, event):
        # Send typing indicator
        if event['sender'] != self.user.username:  # Don't send to self
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'sender': event['sender'],
                'is_typing': event['is_typing']
            }))

    @database_sync_to_async
    def get_user(self, username):
        return User.objects.get(username=username)

    @database_sync_to_async
    def mark_messages_as_read(self, user, other_user):
        from social.models import Message
        Message.objects.filter(
            sender=other_user,
            receiver=user,
            is_read=False
        ).update(is_read=True)