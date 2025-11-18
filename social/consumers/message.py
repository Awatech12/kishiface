from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.conf import settings
from social.models import Message  # Your Message model
from django.utils import timezone

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

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'text_message':
                message = data.get('message')
                receiver = data.get('receiver')
                await self.handle_text_message(message, receiver)

            elif message_type == 'audio_message':
                # Store metadata temporarily; bytes will be sent separately
                self.audio_buffer = {
                    'file_name': data.get('file_name'),
                    'receiver': data.get('receiver')
                }

        if bytes_data and self.audio_buffer:
            await self.handle_audio_bytes(bytes_data)

    async def handle_text_message(self, message, receiver_username):
        now = timezone.now()
        formatted_time = now.strftime("%I:%M %p")
        group_data = {
            'type': 'chat_message',
            'sender': self.username,
            'receiver': receiver_username,
            'message': message,
            'time': formatted_time
        }
        await self.save_message(self.user, receiver_username, message)
        await self.channel_layer.group_send(self.group_name, group_data)

    async def handle_audio_bytes(self, bytes_data):
        file_name = self.audio_buffer['file_name']
        receiver_username = self.audio_buffer['receiver']

        # Handle Cloudinary vs local storage
        file_content = ContentFile(bytes_data, name=file_name)
        if getattr(settings, 'USE_CLOUDINARY', False):
            # CloudinaryField will automatically handle upload
            file_to_save = file_content
        else:
            # Save with random name locally
            import uuid, os
            ext = os.path.splitext(file_name)[1]
            file_to_save.name = f"{uuid.uuid4().hex}{ext}"

        await self.save_sound(self.user, receiver_username, file_to_save)

        # Send to group for real-time playback
        now = timezone.now()
        formatted_time = now.strftime("%I:%M %p")
        group_data = {
            'type': 'chat_sound',
            'sender': self.username,
            'receiver': receiver_username,
            'file_name': file_to_save.url if getattr(settings, 'USE_CLOUDINARY', False) else file_to_save.name,
            'time': formatted_time
        }
        await self.channel_layer.group_send(self.group_name, group_data)
        self.audio_buffer = None

    # --- WebSocket event handlers ---
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
            'file_name': event['file_name'],
            'time': event['time']
        }))

    # --- Database operations ---
    @database_sync_to_async
    def save_message(self, sender, receiver_username, message):
        user_model = get_user_model()
        receiver_user = user_model.objects.get(username=receiver_username)
        Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            conversation=message
        )

    @database_sync_to_async
    def save_sound(self, sender, receiver_username, file_content):
        user_model = get_user_model()
        receiver_user = user_model.objects.get(username=receiver_username)
        Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            file=file_content
        )
