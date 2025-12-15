from channels.generic.websocket import AsyncWebsocketConsumer
import json

class ChannelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = f'channel_{self.channel_id}'
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        print("channel Connected")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        print("Channel Closed")

    async def channel_message(self, event):
        channel_data = {
            'type': 'Response',
            ** event
        }
        await self.send(text_data=json.dumps(channel_data))
