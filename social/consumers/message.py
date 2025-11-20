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

def get_Message_model():
    from social.models import Message
    return Message

def get_user_model_func():
    from django.contrib.auth import get_user_model
    return get_user_model()

class MessageChannel(AsyncWebsocketConsumer):
    """
    Production-ready WebSocket consumer for text & audio chat.
    Cloudinary audio upload fully compatible with <audio> tag.
    """

    async def connect(self):
        self.user = self.scope["user"]

        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        self.group_name = "message"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(f"WebSocket connected: {self.user.username}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WebSocket disconnected: {self.user.username}")

    async def receive(self, text_data=None):
        if not text_data:
            return

        data = json.loads(text_data)

        message_text = data.get("message")
        audio_base64 = data.get("audio")
        receiver_username = data.get("receiver")

        audio_url = None

        if audio_base64:
            audio_url = await self.save_audio(self.user, receiver_username, audio_base64)

        if message_text:
            await self.save_message(self.user, receiver_username, message_text)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "sender": self.user.username,
                "receiver": receiver_username,
                "message": message_text,
                "audio_url": audio_url,
                "time": timezone.now().strftime("%I:%M %p"),
            },
        )

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps({
                "type": "chat_response",
                "sender": event["sender"],
                "receiver": event["receiver"],
                "message": event.get("message"),
                "audio_url": event.get("audio_url"),
                "time": event["time"],
            })
        )

    # ---------------------------------------------------------------------
    # DATABASE OPERATIONS
    # ---------------------------------------------------------------------

    @database_sync_to_async
    def save_message(self, sender, receiver_username, text):
        Message = get_Message_model()
        receiver = get_user_model_func().objects.get(username=receiver_username)
        return Message.objects.create(sender=sender, receiver=receiver, conversation=text)

    @database_sync_to_async
    def save_audio(self, sender, receiver_username, audio_base64):
        """
        Upload audio to Cloudinary (production) or local filesystem (debug).
        Ensures Cloudinary returns a direct URL usable in <audio>.
        """

        Message = get_Message_model()
        receiver = get_user_model_func().objects.get(username=receiver_username)

        # Decode base64
        try:
            header, audio_str = audio_base64.split(";base64,")
            ext = header.split("/")[-1]  # webm, ogg, mp3, etc.
            audio_bytes = base64.b64decode(audio_str)
            filename = f"{uuid.uuid4()}.{ext}"
        except Exception as e:
            logger.error(f"Audio decode error: {e}")
            return None

        # Create initial message
        message = Message.objects.create(sender=sender, receiver=receiver)

        # ---------------------- PRODUCTION MODE ----------------------
        if getattr(settings, "USE_CLOUDINARY", False):
            try:
                import cloudinary.uploader

                # Force Cloudinary to return a direct-play URL
                result = cloudinary.uploader.upload(
                    ContentFile(audio_bytes, name=filename),
                    resource_type="video",  # IMPORTANT: audio is treated as video
                    type="upload",          # IMPORTANT: avoid authenticated/private asset URLs
                    folder="message_files",
                    public_id=filename,
                    overwrite=True
                )

                # Save CloudinaryField correctly
                message.file = result
                message.save()

                # Return direct URL to frontend
                return result["secure_url"]

            except Exception as e:
                logger.error("Cloudinary upload failed", exc_info=True)
                return None

        # ----------------------- DEBUG MODE -------------------------
        # Save locally
        message.file.save(filename, ContentFile(audio_bytes))
        return message.file.url