from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

def get_models():
    from social.models import Message
    return Message

class MessageChannel(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            return
        self.username = self.user.username
        self.group_name = 'message'
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        print("Message Channel")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        print('Disconnect')
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message')
        receiver = data.get('receiver')
        username = self.username
        now = timezone.now()
        formatted_time = now.strftime("%I:%M %p")
        group_data = {
            'type': 'chat_message',
            'sender': username,
            'receiver': receiver,
            'message': message,
            'time': formatted_time
        }
        await self.save_message(self.user, receiver,  message)
        await self.channel_layer.group_send(
            self.group_name,
            group_data
        )

    async def chat_message(self, event):
        text_data = {
            'type': 'Response',
            'sender': event['sender'],
            'receiver': event['receiver'],
            'message': event['message'],
            'time': event['time']
        }
        await self.send(text_data=json.dumps(text_data))
    @database_sync_to_async
    def save_message(self, sender, receiver, message):
        Message = get_models()
        user = get_user_model()
        msgReceiver = user.objects.get(username=receiver)
        Message.objects.create(
            sender=sender,
            receiver=msgReceiver,
            conversation = message
        )
