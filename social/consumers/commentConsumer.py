from channels.generic.websocket import AsyncWebsocketConsumer
import json

class CommentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.post_id = self.scope['url_route']['kwargs']['post_id']
        self.group_name = f'post_{self.post_id}'
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        print('Comment Channel Connected')

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        print('comment channel Disconnected')

    async def new_comment(self, event):
        text_data = {
            'comment_id': str(event['comment_id']),
            'author_username': event['author_username'],
            'author_first': event['author_first'],
            'author_last': event['author_last'],
            'is_verify': event['is_verify'],
            'profile_pic': event['profile_pic'],
            'comment': event['comment'],
            'image_url': event['image_url'],
            'file_url':event['file_url'],
            'post_id': str(event['post_id']),
            'created_at': event['created_at'],
            'user_id': event['user_id']

        }
        await self.send(text_data=json.dumps(text_data))