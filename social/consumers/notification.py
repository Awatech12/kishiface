from channels.generic.websocket import AsyncWebsocketConsumer
import json

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.group_name = 'comment_notification'
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        print('Notification Channel Connected')
    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )   
        await self.close()
        print('Notification Channel Closed')

    async def send_notification(self, event):
        data_send = {
            'type': 'Response',
            ** event
        }

        await self.send(text_data= json.dumps(data_send))