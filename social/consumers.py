from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async 
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.utils import timezone
import json


def get_social_models():
    from social.models import Channel, ChannelMessage
    return Channel, ChannelMessage
def get_user_model_func():
    from django.contrib.auth import get_user_model
    return get_user_model()
class ChannelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        
        self.user = self.scope['user']
        if not self.user:
            return
        self.username = self.user
        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = self.channel_id
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        print('channel Connect')
        
    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        print('channel Discard')

    async def receive(self, text_data):
        data = json.loads(text_data)
        username = self.user.username
        message = data.get('message')
        image = data.get('image')
        pictureUrl=data.get('pictureUrl')
        group_data = {
            'type':'chat_message',
            'username': username,
            'message': message,
            'image':image,
             'pictureUrl':pictureUrl,
             'time': str(naturaltime(timezone.now()))
        }
        await self.save_message(self.username, message, image, pictureUrl)
        await self.channel_layer.group_send(
            self.group_name,
            group_data
        )
        
    async def chat_message(self, event):
        text_data = {
            'type':'Response',
            'username': event['username'],
            'message': event['message'],
            'image': event['image'],
            'pictureUrl': event['pictureUrl'],
            'time': event['time']
        }

        await self.send(text_data=json.dumps(text_data))
    @database_sync_to_async
    def save_message(self, username, message, image, pictureUrl):
        Channel, ChannelMessage = get_social_models()
        channel=Channel.objects.get(channel_id=self.channel_id)
        ChannelMessage.objects.create(
            channel=channel,
            author=username,
            message=message,
            pictureUrl=pictureUrl,
            image = image
        ) 