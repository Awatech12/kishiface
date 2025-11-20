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


def get_message_model():
    from social.models import Message
    return Message


def get_user_model_func():
    from django.contrib.auth import get_user_model
    return get_user_model()


class MessageChannel(AsyncWebsocketConsumer):
    """
    FULL TEXT + AUDIO CHAT CONSUMER
    Works in Debug + Production.
    Cloudinary audio upload is fully supported.
    """

    # ---------------------------------------------------
    # CONNECT
    # ---------------------------------------------------
    async def connect(self):

        self.user = self.scope["user"]
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Single group for your chat
        self.group_name = "message_group"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"WebSocket CONNECTED: {self.user.username}")

    # ---------------------------------------------------
    # DISCONNECT
    # ---------------------------------------------------
    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        logger.info(f"WebSocket DISCONNECTED: {self.user.username}")

    # ---------------------------------------------------
    # RECEIVE MESSAGE FROM BROWSER
    # ---------------------------------------------------
    async def receive(self, text_data=None):
        if not text_data:
            return

        data = json.loads(text_data)

        msg_text = data.get("message")
        receiver_username = data.get("receiver")
        audio_base64 = data.get("audio")

        audio_url = None

        # ----- SAVE AUDIO -----
        if audio_base64:
            audio_url = await self.save_audio(
                self.user,
                receiver_username,
                audio_base64
            )

        # ----- SAVE TEXT -----
        if msg_text:
            await self.save_text_message(
                self.user,
                receiver_username,
                msg_text
            )

        # ----- SEND TO GROUP -----
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "sender": self.user.username,
                "receiver": receiver_username,
                "message": msg_text,
                "audio_url": audio_url,
                "time": timezone.now().strftime("%I:%M %p"),
            }
        )

    # ---------------------------------------------------
    # SEND MESSAGE TO BROWSER
    # ---------------------------------------------------
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "chat_response",
            "sender": event["sender"],
            "receiver": event["receiver"],
            "message": event.get("message"),
            "audio_url": event.get("audio_url"),
            "time": event["time"],
        }))

    # ---------------------------------------------------
    # SAVE TEXT MESSAGE
    # ---------------------------------------------------
    @database_sync_to_async
    def save_text_message(self, sender, receiver_username, text):

        Message = get_message_model()
        User = get_user_model_func()
        receiver = User.objects.get(username=receiver_username)

        return Message.objects.create(
            sender=sender,
            receiver=receiver,
            conversation=text
        )

    # ---------------------------------------------------
    # SAVE AUDIO MESSAGE (DEBUG + PRODUCTION)
    # ---------------------------------------------------
    @database_sync_to_async
    def save_audio(self, sender, receiver_username, audio_base64):

        Message = get_message_model()
        User = get_user_model_func()
        receiver = User.objects.get(username=receiver_username)

        # -----------------------------
        # Decode Base64
        # -----------------------------
        try:
            header, audio_str = audio_base64.split(";base64,")
            ext = header.split("/")[-1]        # webm / ogg / mp3
            audio_bytes = base64.b64decode(audio_str)
        except Exception as e:
            logger.error(f"Audio decode error → {e}")
            return None

        # Generate UUID and Filename separately
        file_uuid = str(uuid.uuid4())
        filename = f"{file_uuid}.{ext}"

        # Create message row BEFORE saving file
        msg = Message.objects.create(
            sender=sender,
            receiver=receiver
        )

        # -----------------------------
        # PRODUCTION → CLOUDINARY UPLOAD
        # -----------------------------
        if getattr(settings, "USE_CLOUDINARY", False):
            try:
                import cloudinary.uploader

                result = cloudinary.uploader.upload(
                    ContentFile(audio_bytes, name=filename),
                    resource_type="video",   # REQUIRED for audio upload
                    type="upload",           # ensures public URL
                    folder="chat_audio",
                    public_id=file_uuid,     # FIX: Use ID without extension
                    format=ext,              # FIX: Explicitly set format
                    overwrite=True
                )

                msg.file = result
                msg.save()

                return result["secure_url"]

            except Exception as e:
                logger.error("CLOUDINARY AUDIO UPLOAD ERROR", exc_info=True)
                return None

        # -----------------------------
        # DEBUG → LOCAL FILE SAVE
        # -----------------------------
        msg.file.save(filename, ContentFile(audio_bytes))
        return msg.file.url
