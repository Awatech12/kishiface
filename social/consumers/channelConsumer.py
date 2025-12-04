import json
import base64
import uuid
from django.core.files.base import ContentFile
from django.utils import timezone
from django.contrib.auth import get_user_model
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings

def get_models():
    from social.models import Channel, ChannelMessage
    return Channel, ChannelMessage

@database_sync_to_async
def toggle_like(msg_id, user):
    Channel, ChannelMessage = get_models()
    try:
        msg = ChannelMessage.objects.get(channemessage_id=msg_id)
        liked = user not in msg.like.all()
        if liked:
            msg.like.add(user)
        else:
            msg.like.remove(user)
        return msg.like_count(), liked
    except Exception as e:
        print("Toggle like error:", e)
        return 0, False

class ChannelConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        if not self.scope["user"].is_authenticated:
            return
        self.user = self.scope["user"]
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.group_name = f"channel_{self.channel_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        print(f"User {self.user.username} connected to {self.group_name}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        if action == "like_unlike":
            like_count, liked = await toggle_like(data["message_id"], self.user)
            await self.channel_layer.group_send(self.group_name, {
                "type": "like_update",
                "message_id": data["message_id"],
                "like_count": like_count,
                "user_liked": liked,
            })
            return

        msg = await self.save_message(
            self.user.username,
            data.get("message"),
            data.get("file"),
            data.get("file_name"),
            data.get("pictureUrl"),
        )

        await self.channel_layer.group_send(self.group_name, {
            "type": "chat_message",
            "username": self.user.username,
            "message": msg.message,
            "file_url": msg.file_url,
            "file_name": msg.file_name,
            "file_type": msg.file_type,
            "message_id": str(msg.channemessage_id),
            "pictureUrl": msg.pictureUrl,
            "time": timezone.now().strftime("%I:%M %p"),
        })

    async def chat_message(self, event):
        # Send new message to client
        await self.send(text_data=json.dumps({
            "type": "Response",
            "username": event["username"],
            "message": event["message"],
            "file_url": event["file_url"],
            "file_name": event["file_name"],
            "file_type": event["file_type"],
            "message_id": event["message_id"],
            "pictureUrl": event["pictureUrl"],
            "time": event["time"],
        }))

    async def like_update(self, event):
        # Send like update to client
        await self.send(text_data=json.dumps({
            "type": "like_response",
            "message_id": event["message_id"],
            "like_count": event["like_count"],
            "user_liked": event["user_liked"],
        }))

    @database_sync_to_async
    def save_message(self, username, text, base64_file, file_name, picture):
        Channel, ChannelMessage = get_models()
        User = get_user_model()
        user = User.objects.get(username=username)
        channel = Channel.objects.get(channel_id=self.channel_id)

        msg = ChannelMessage(channel=channel, author=user, message=text or "", pictureUrl=picture)

        if base64_file:
            try:
                if ";base64," in base64_file:
                    header, encoded = base64_file.split(";base64,")
                    mime_type = header.split(":")[-1]
                    ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"
                else:
                    encoded = base64_file
                    ext = "bin"

                file_name = file_name or f"{uuid.uuid4()}.{ext}"
                decoded = base64.b64decode(encoded)
                content = ContentFile(decoded, name=file_name)

                if settings.USE_CLOUDINARY:
                    from cloudinary.uploader import upload as cloudinary_upload
                    resource_type = "raw"
                    if mime_type.startswith("image"):
                        resource_type = "image"
                    elif mime_type.startswith("video") or mime_type.startswith("audio"):
                        resource_type = "video"

                    upload_result = cloudinary_upload(
                        file=content,
                        folder="channel_files",
                        resource_type=resource_type,
                        use_filename=True,
                        unique_filename=True,
                        overwrite=False,
                    )
                    msg.file_url = upload_result.get("secure_url")
                    msg.file_name = upload_result.get("original_filename")
                    msg.file_type = msg.detect_file_type(msg.file_name)
                else:
                    msg.file.save(file_name, content, save=False)
                    msg.file_name = msg.file.name
                    msg.file_type = msg.detect_file_type(msg.file_name)
                    msg.file_url = msg.file.url
            except Exception as e:
                print("File upload error:", e)

        msg.save()
        msg.refresh_from_db()
        return msg