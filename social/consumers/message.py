from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

# Set up logging for better debugging in all environments
logger = logging.getLogger(__name__)

def get_models():
    # Deferred import to avoid AppRegistryNotReady error
    from social.models import Message
    return Message

class MessageChannel(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            # Reject connection if the user is not authenticated
            logger.warning("WebSocket connection attempt by unauthenticated user.")
            await self.close()
            return
            
        self.username = self.user.username
        # Use a general group name for simple broadcast
        self.group_name = 'message'
        
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"Message Channel Connected for user: {self.username}")
        self.audio_metadata = None 

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f'Disconnected user: {self.username} with code: {code}')

    async def receive(self, text_data=None, bytes_data=None):
        # --- Handle incoming text (JSON metadata) ---
        if text_data:
            data = json.loads(text_data)
            message_type = data.get('type')
            receiver = data.get('receiver')
            now = timezone.now()
            formatted_time = now.strftime("%I:%M %p")

            if message_type == 'text_message':
                message = data.get('message')
                
                # 1. Save to DB
                await self.save_message(self.user, receiver, message)
                
                # 2. Send to group (broadcast)
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_message',
                    'sender': self.username,
                    'receiver': receiver,
                    'message': message,
                    'time': formatted_time
                })
                logger.debug(f"Text message sent from {self.username} to {receiver}")

            elif message_type == 'audio_metadata':
                # Store metadata temporarily; actual audio bytes are expected next
                self.audio_metadata = {
                    'file_name': data.get('file_name'),
                    'receiver': receiver
                }
                logger.debug(f"Audio metadata received for file: {data.get('file_name')}")
            
        # --- Handle incoming audio bytes ---
        if bytes_data and self.audio_metadata:
            file_name = self.audio_metadata['file_name']
            receiver = self.audio_metadata['receiver']
            
            try:
                # ContentFile respects Django's default storage (local) 
                # or configured storage (e.g., Cloudinary, S3)
                file_content = ContentFile(bytes_data, name=file_name)
                
                # 1. Save file to DB
                message_instance = await self.save_sound(self.user, receiver, file_content)

                # 2. Send group message with URL
                now = timezone.now()
                formatted_time = now.strftime("%I:%M %p")
                
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_sound',
                    'sender': self.username,
                    'receiver': receiver,
                    'file_url': message_instance.file.url,
                    'time': formatted_time
                })
                logger.info(f"Audio file '{file_name}' saved and broadcasted.")
                
            except Exception as e:
                logger.error(f"Error saving/sending audio file: {e}")

            # Clear buffer immediately after processing
            self.audio_metadata = None
            
        # Error handling for unexpected bytes without metadata
        elif bytes_data and not self.audio_metadata:
            logger.warning(f"Received unexpected byte data from {self.username} without prior metadata.")


    # --- Client broadcasting ---
    async def chat_message(self, event):
        """Sends a text message response to the client."""
        await self.send(text_data=json.dumps({
            'type': 'text_response',
            'sender': event['sender'],
            'receiver': event['receiver'],
            'message': event['message'],
            'time': event['time']
        }))

    async def chat_sound(self, event):
        """Sends an audio message URL response to the client."""
        await self.send(text_data=json.dumps({
            'type': 'sound_response',
            'sender': event['sender'],
            'receiver': event['receiver'],
            'file_url': event['file_url'],
            'time': event['time']
        }))

    # --- Database helpers ---
    @database_sync_to_async
    def save_message(self, sender, receiver_username, message):
        """Saves a text message."""
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)
        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            conversation=message
        )

    @database_sync_to_async
    def save_sound(self, sender, receiver_username, file_content):
        """Saves an audio file message."""
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)
        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            file=file_content
        )
