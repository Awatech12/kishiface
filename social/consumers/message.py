# social/consumers/message.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class DirectMessageConsumer(AsyncWebsocketConsumer):
    @database_sync_to_async
    def get_user(self, username):
        from django.contrib.auth.models import User
        return User.objects.get(username=username)

    async def connect(self):
        from django.contrib.auth.models import User
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        self.other_username = self.scope['url_route']['kwargs']['username']
        try:
            self.other_user = await self.get_user(self.other_username)
        except User.DoesNotExist:
            await self.close()
            return

        user_ids = sorted([self.user.id, self.other_user.id])
        self.room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        self.room_group_name = f"chat_{self.room_name}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Clear typing indicator when user disconnects mid-typing
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'sender': self.user.username,
                'is_typing': False
            }
        )
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'typing':
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing_indicator',
                        'sender': self.user.username,
                        'is_typing': data.get('is_typing', False)
                    }
                )
        except json.JSONDecodeError:
            pass

    async def chat_message(self, event):
        """Handle new messages from send_message view."""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message_id': event.get('message_id'),
            'sender': event.get('sender'),
            'sender_avatar': event.get('sender_avatar'),
            'receiver': event.get('receiver'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'file_url': event.get('file_url'),
            'file_name': event.get('file_name', ''),
            'time': event.get('time'),
            'reply_to': event.get('reply_to'),
            'link_preview': event.get('link_preview'),
        }))

        # Broadcast inbox update to both users' personal inbox channels
        inbox_payload = {
            'type': 'inbox_update',
            'sender': event.get('sender'),
            'sender_avatar': event.get('sender_avatar'),
            'receiver': event.get('receiver'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'time': event.get('time'),
        }
        await self.channel_layer.group_send(f"inbox_{event.get('sender')}", inbox_payload)
        await self.channel_layer.group_send(f"inbox_{event.get('receiver')}", inbox_payload)

    async def message_deleted(self, event):
        """Handle deletion events from delete_message view."""
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event.get('message_id'),
            'sender': event.get('sender'),
            'receiver': event.get('receiver'),
        }))

    async def typing_indicator(self, event):
        """Forward typing indicator only to the other user."""
        if event['sender'] != self.user.username:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'sender': event['sender'],
                'is_typing': event['is_typing'],
            }))

    async def message_reaction(self, event):
        """Broadcast reaction updates to both participants."""
        await self.send(text_data=json.dumps({
            'type': 'message_reaction',
            'message_id': event.get('message_id'),
            'reactions': event.get('reactions', {}),
            'actor': event.get('actor'),
        }))
