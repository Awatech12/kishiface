from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.utils import timezone

def get_models():
    from social.models import Message
    return Message

class MessageChannel(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.username = self.user.username
        self.group_name = 'message'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self.audio_buffer = None  # Temporarily store audio metadata
        await self.accept()
        print("Message Channel Connected")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        print('Disconnected')

    # Handles both text (JSON) and audio bytes
    async def receive(self, text_data=None, bytes_data=None):
        # --- Text / metadata ---
        if text_data:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'text_message':
                message = data.get('message')
                receiver = data.get('receiver')
                now = timezone.now()
                formatted_time = now.strftime("%I:%M %p")

                # Save to DB
                await self.save_message(self.user, receiver, message)

                # Send to group
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_message',
                    'sender': self.username,
                    'receiver': receiver,
                    'message': message,
                    'time': formatted_time
                })

            elif message_type == 'audio_message':
                # Store metadata temporarily; actual audio bytes come next
                self.audio_buffer = {
                    'file_name': data.get('file_name'),
                    'receiver': data.get('receiver')
                }

        # --- Audio bytes ---
        if bytes_data and self.audio_buffer:
            file_name = self.audio_buffer['file_name']
            receiver = self.audio_buffer['receiver']

            file_content = ContentFile(bytes_data, name=file_name)
            # Save file to DB (Cloudinary if enabled)
            message_instance = await self.save_sound(self.user, receiver, file_content)

            # Send group message with URL
            now = timezone.now()
            formatted_time = now.strftime("%I:%M %p")
            await self.channel_layer.group_send(self.group_name, {
                'type': 'chat_sound',
                'sender': self.username,
                'receiver': receiver,
                'file_url': message_instance.file.url,  # Full URL
                'time': formatted_time
            })

            # Clear buffer
            self.audio_buffer = None

    # --- Client broadcasting ---
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'text_response',
            'sender': event['sender'],
            'receiver': event['receiver'],
            'message': event['message'],
            'time': event['time']
        }))

    async def chat_sound(self, event):
        await self.send(text_data=json.dumps({
            'type': 'sound_response',
            'sender': event['sender'],
            'receiver': event['receiver'],
            'file_url': event['file_url'],  # Use URL for audio playback
            'time': event['time']
        }))

    # --- Database helpers ---
    @database_sync_to_async
    def save_message(self, sender, receiver_username, message):
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)
        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            conversation=message
        )

    @database_sync_to_async
    def save_sound(self, sender, receiver_username, file_content):
        """
        Saves audio message and returns Message instance.
        Works with Cloudinary in production or local storage in debug.
        """
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)
        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            file=file_content
        )