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
    except:
        return 0, False


class ChannelConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        if not self.scope["user"].is_authenticated:
            return

        self.user = self.scope["user"]
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        self.group_name = self.channel_id

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

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

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "username": self.user.username,
                "message": msg.message,
                "file_url": msg.file_url,
                "file_name": msg.file_name,
                "file_type": msg.file_type,
                "message_id": str(msg.channemessage_id),
                "pictureUrl": msg.pictureUrl,
                "time": timezone.now().strftime("%I:%M %p"),
            }
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "Response",
            **event
        }))

    async def like_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "like_response",
            **event
        }))

    @database_sync_to_async
    def save_message(self, username, text, base64_file, file_name, picture):
        Channel, ChannelMessage = get_models()
        User = get_user_model()

        user = User.objects.get(username=username)
        channel = Channel.objects.get(channel_id=self.channel_id)

        msg = ChannelMessage(
            channel=channel,
            author=user,
            message=text or "",
            pictureUrl=picture,
        )

        if base64_file:
            try:
                header, encoded = base64_file.split(";base64,")
                ext = header.split("/")[-1]
                file_name = file_name or f"{uuid.uuid4()}.{ext}"

                decoded = base64.b64decode(encoded)
                content = ContentFile(decoded, name=file_name)
                msg.file.save(file_name, content, save=False)
            except:
                msg.file = None

        msg.save()
        msg.refresh_from_db()
        return msg