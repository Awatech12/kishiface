import json
import uuid
import base64
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

def get_models():
    from social.models import Message
    return Message

def get_user_model_func():
    from django.contrib.auth import get_user_model
    return get_user_model()

class MessageChannel(AsyncWebsocketConsumer):
    """
    WebSocket consumer for group chat supporting text and audio.
    Audio is sent as base64 and saved to either local storage (DEBUG)
    or Cloudinary (production).
    """

    async def connect(self):
        self.user = self.scope['user']
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # All users join the same group
        self.group_name = 'message'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"WebSocket connected: {self.user.username}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WebSocket disconnected: {self.user.username}")

    async def receive(self, text_data=None):
        """
        Handle incoming messages:
        - text messages: "message"
        - audio messages: "audio" (base64 string)
        """
        if not text_data:
            return

        data = json.loads(text_data)
        message_text = data.get("message")
        audio_base64 = data.get("audio")
        receiver_username = data.get("receiver")

        file_url = None

        if audio_base64:
            file_url = await self.save_audio(self.user, receiver_username, audio_base64)

        if message_text:
            await self.save_message(self.user, receiver_username, message_text)

        # Broadcast to all members of the group
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "sender": self.user.username,
                "receiver": receiver_username,
                "message": message_text,
                "audio_url": file_url,
                "time": timezone.now().strftime("%I:%M %p")
            }
        )

    async def chat_message(self, event):
        """
        Send message to WebSocket client.
        """
        await self.send(text_data=json.dumps({
            "type": "chat_response",
            "sender": event["sender"],
            "receiver": event["receiver"],
            "message": event.get("message", ""),
            "audio_url": event.get("audio_url", ""),
            "time": event["time"]
        }))

    # -------------------------- Database Operations --------------------------

    @database_sync_to_async
    def save_message(self, sender, receiver_username, message_text):
        Message = get_models()
        receiver_user = get_user_model_func().objects.get(username=receiver_username)
        return Message.objects.create(sender=sender, receiver=receiver_user, conversation=message_text)

    @database_sync_to_async
    def save_audio(self, sender, receiver_username, audio_base64):
        """
        Save base64 audio to either local FileField (DEBUG) or Cloudinary (production)
        """
        Message = get_models()
        receiver_user = get_user_model_func().objects.get(username=receiver_username)

        try:
            header, audio_str = audio_base64.split(";base64,")
            ext = header.split("/")[-1]
            audio_bytes = base64.b64decode(audio_str)
            file_name = f"{uuid.uuid4()}.{ext}"
        except Exception as e:
            logger.error(f"Audio decode error: {e}")
            return None

        message = Message.objects.create(sender=sender, receiver=receiver_user)

        if getattr(settings, "USE_CLOUDINARY", False):
            import cloudinary.uploader
            try:
                result = cloudinary.uploader.upload(
                    ContentFile(audio_bytes, name=file_name),
                    resource_type="auto",
                    folder="message_files",
                    public_id=file_name
                )
                message.file = result["secure_url"]
                message.save()
                return result["secure_url"]
            except Exception as e:
                logger.error(f"Cloudinary upload failed: {e}", exc_info=True)
                return None
        else:
            message.file.save(file_name, ContentFile(audio_bytes))
            return message.file.url
