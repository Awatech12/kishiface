from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.base import ContentFile
from django.conf import settings
import logging

if not settings.DEBUG:
    import cloudinary.uploader
    from django.core.files.uploadedfile import InMemoryUploadedFile
    import io

logger = logging.getLogger(__name__)


def get_models():
    from social.models import Message 
    return Message


class MessageChannel(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            logger.warning("Unauthenticated websocket attempt.")
            await self.close()
            return

        self.username = self.user.username
        self.group_name = 'message' 

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self.audio_buffer = None

        await self.accept()
        logger.info(f"WebSocket connected: {self.username}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WebSocket disconnected: {self.username}")

    async def receive(self, text_data=None, bytes_data=None):

        if text_data:
            data = json.loads(text_data)
            msg_type = data.get("type")

            if msg_type == "text_message":
                message = data.get("message")
                receiver = data.get("receiver")
                now = timezone.now().strftime("%I:%M %p")

                await self.save_message(self.user, receiver, message)

                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "chat_message",
                        "sender": self.username,
                        "receiver": receiver,
                        "message": message,
                        "time": now
                    }
                )
                return

            elif msg_type == "audio_message":
                self.audio_buffer = {
                    "receiver": data.get("receiver"),
                    "file_name": data.get("file_name"),
                }
                logger.info(f"Audio metadata received: {self.audio_buffer}")
                return

        if bytes_data and self.audio_buffer:

            receiver = self.audio_buffer["receiver"]
            file_name = self.audio_buffer["file_name"]

            logger.info(f"Received {len(bytes_data)} audio bytes for: {file_name}")

            try:
                msg_instance = await self.save_sound(
                    self.user,
                    receiver,
                    bytes_data,
                    file_name
                )

                now = timezone.now().strftime("%I:%M %p")

                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "chat_sound",
                        "sender": self.username,
                        "receiver": receiver,
                        "file_url": msg_instance.file.url, 
                        "time": now
                    }
                )

            except Exception as e:
                logger.error(f"Error saving audio: {e}", exc_info=True)

            self.audio_buffer = None
            return

        if bytes_data and not self.audio_buffer:
            logger.warning("Received bytes without audio metadata.")
            return

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "text_response",
            "sender": event["sender"],
            "receiver": event["receiver"],
            "message": event["message"],
            "time": event["time"]
        }))

    async def chat_sound(self, event):
        await self.send(text_data=json.dumps({
            "type": "sound_response",
            "sender": event["sender"],
            "receiver": event["receiver"],
            "file_url": event["file_url"],
            "time": event["time"]
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
        Message = get_models()
        receiver_user = get_user_model().objects.get(username=receiver_username)

        message = Message.objects.create(
            sender=sender,
            receiver=receiver_user
        )

        file_content = ContentFile(file_bytes)

        if settings.DEBUG:
            message.file.save(file_name, file_content)
            return message

        try:
            message.file.save(file_name, file_content)
        except Exception as e:
            logger.error(f"Failed to save file using Django storage wrapper: {e}", exc_info=True)
            file_obj = ContentFile(file_bytes, name=file_name)
            file_stream = io.BytesIO(file_bytes)
            file_stream.name = file_name
            upload_file = InMemoryUploadedFile(
                file=file_stream, 
                field_name=None, 
                name=file_name, 
                content_type='audio/webm', 
                size=len(file_bytes), 
                charset=None
            )

            result = cloudinary.uploader.upload(
                upload_file,
                resource_type="auto",
                folder="comment_files",
                public_id=f"audio_{message.pk}_{timezone.now().timestamp()}" 
            )

            file_url = result["secure_url"]
            message.file = file_url
            message.save()
            return message
        
        return message
