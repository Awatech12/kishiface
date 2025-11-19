from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def get_models():
    from social.models import Message
    return Message

class MessageChannel(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            logger.warning("WebSocket connection attempt by unauthenticated user.")
            await self.close()
            return
            
        self.username = self.user.username
        self.group_name = 'message'
        
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self.audio_buffer = None
        await self.accept()
        logger.info(f"Message Channel Connected for user: {self.username}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f'Disconnected user: {self.username} with code: {code}')

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'text_message':
                message = data.get('message')
                receiver = data.get('receiver')
                now = timezone.now()
                formatted_time = now.strftime("%I:%M %p")

                await self.save_message(self.user, receiver, message)

                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_message',
                    'sender': self.username,
                    'receiver': receiver,
                    'message': message,
                    'time': formatted_time
                })
                logger.debug(f"Text message sent from {self.username} to {receiver}")

            elif message_type == 'audio_message':
                self.audio_buffer = {
                    'file_name': data.get('file_name'),
                    'receiver': data.get('receiver')
                }
                logger.debug(f"Audio metadata received for file: {data.get('file_name')}")

        if bytes_data and self.audio_buffer:
            file_name = self.audio_buffer['file_name']
            receiver = self.audio_buffer['receiver']

            logger.info(f"Received {len(bytes_data)} bytes of audio data for {file_name}")

            try:
                message_instance = await self.save_sound(
                    self.user, 
                    receiver, 
                    bytes_data,
                    file_name
                )
                logger.info(f"File successfully saved to URL: {message_instance.file.url}")

                now = timezone.now()
                formatted_time = now.strftime("%I:%M %p")
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_sound',
                    'sender': self.username,
                    'receiver': receiver,
                    'file_url': message_instance.file.url,
                    'time': formatted_time
                })

            except Exception as e:
                logger.error(f"Error saving/sending audio file: {e}", exc_info=True)

            self.audio_buffer = None
            
        elif bytes_data and not self.audio_buffer:
            logger.warning(f"Received unexpected byte data from {self.username} without prior audio metadata.")

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
            'file_url': event['file_url'],
            'time': event['time']
        }))

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
    def save_sound(self, sender, receiver_username, file_bytes, file_name):
        from django.core.files.base import ContentFile 
        file_content = ContentFile(file_bytes, name=file_name)
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)
        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            file=file_content
        )