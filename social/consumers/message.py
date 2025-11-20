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
                        "sender": self.username,
                        "receiver": receiver,
                        "message": message,
                        "time": now
                    }
                )
                return

            # PREPARE FOR AUDIO BYTES
            elif msg_type == "audio_message":
                self.audio_buffer = {
                    "receiver": data.get("receiver"),
                    "file_name": data.get("file_name")
                }
                logger.info(f"Audio metadata received: {self.audio_buffer}")
                return

        # -------------------------- AUDIO BYTES --------------------------
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

        # UNEXPECTED RAW BYTES
        if bytes_data and not self.audio_buffer:
            logger.warning("Received bytes without audio metadata.")
            return

    # -------------------------- SEND TEXT --------------------------
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

    # -------------------------- SAVE AUDIO FILE --------------------------
    @database_sync_to_async
    def save_audio(self, sender, receiver_username, audio_base64):
        """
        Upload audio to Cloudinary (production) or local filesystem (debug).
        Ensures Cloudinary returns a direct URL usable in <audio>.
        """

        Message = get_Message_model()
        receiver = get_user_model_func().objects.get(username=receiver_username)

        # =========== LOCAL MODE (DEBUG=True) ===========
        if settings.DEBUG:
            message = Message.objects.create(
                sender=sender,
                receiver=receiver_user
            )
            message.file.save(file_name, ContentFile(file_bytes))
            return message

        # =========== PRODUCTION MODE (DEBUG=False) ===========
        result = cloudinary.uploader.upload(
            file_bytes,
            resource_type="auto",
            folder="comment_files",
            public_id=file_name
        )

        file_url = result["secure_url"]

        return Message.objects.create(
            sender=sender,
            receiver=receiver_user,
            file=file_url
        )