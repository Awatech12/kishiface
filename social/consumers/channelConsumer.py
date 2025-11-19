from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.utils import timezone
import json
import uuid
import base64
from django.core.files.base import ContentFile


def get_social_models():
    from social.models import Channel, ChannelMessage
    return Channel, ChannelMessage

def get_user_model_func():
    from django.contrib.auth import get_user_model
    return get_user_model()


class ChannelConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']

        if not self.user or not self.user.is_authenticated:
            return

        self.username = self.user
        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = self.channel_id

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()
        print("CHANNEL CONNECTED")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        print("CHANNEL DISCONNECTED")

    async def receive(self, text_data):
        data = json.loads(text_data)

        username = self.user.username
        message = data.get("message")
        image_base64 = data.get("image")
        pictureUrl = data.get("pictureUrl")
        now = timezone.now()
        formatted_time = now.strftime("%I:%M %p")
        # Save message and get the actual URL of the image file
        saved_image_url = await self.save_message(self.username, message, image_base64, pictureUrl)

        group_data = {
            "type": "chat_message",
            "username": username,
            "message": message,
            "image": saved_image_url,   # <--- URL now
            "pictureUrl": pictureUrl,
            "time": formatted_time
        }

        await self.channel_layer.group_send(self.group_name, group_data)

    async def chat_message(self, event):
        text_data = {
            "type": "Response",
            "username": event["username"],
            "message": event["message"],
            "image": event["image"],
            "pictureUrl": event["pictureUrl"],
            "time": event["time"]
        }

        await self.send(text_data=json.dumps(text_data))

    @database_sync_to_async
    def save_message(self, username, message, image_data, pictureUrl):
        Channel, ChannelMessage = get_social_models()
        channel = Channel.objects.get(channel_id=self.channel_id)

        msg = ChannelMessage(
            channel=channel,
            author=username,
            message=message,
            pictureUrl=pictureUrl,
        )

        # Only process image if it exists
        if image_data:
            # image_data looks like: "data:image/png;base64,AAAAAA..."
            try:
                format, imgstr = image_data.split(";base64,")
                ext = format.split("/")[-1]

                file_name = f"{uuid.uuid4()}.{ext}"
                decoded_image = base64.b64decode(imgstr)

                msg.image.save(file_name, ContentFile(decoded_image), save=False)

            except Exception as e:
                print("IMAGE SAVE ERROR:", str(e))

        msg.save()

        # Return final image URL or None
        return msg.image.url if msg.image else None