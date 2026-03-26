import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from asgiref.sync import sync_to_async


class ChannelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = f'channel_{self.channel_id}'
        self.user_group_name = f'user_{self.user.id}_channels'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # Clear typing indicator on disconnect
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'typing_indicator',
                'sender': self.user.username,
                'is_typing': False,
            }
        )
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'mark_as_read':
                await self.mark_channel_as_read()
                await self.send(text_data=json.dumps({
                    'type': 'marked_as_read',
                    'channel_id': self.channel_id,
                    'timestamp': timezone.now().isoformat()
                }))
                await self.channel_layer.group_send(
                    self.user_group_name,
                    {
                        'type': 'unread_update',
                        'channel_id': self.channel_id,
                        'unread_count': 0,
                        'action': 'marked_read'
                    }
                )

            elif message_type == 'get_unread_counts':
                await self.send_unread_counts()

            elif message_type == 'typing':
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        'type': 'typing_indicator',
                        'sender': self.user.username,
                        'is_typing': data.get('is_typing', False),
                    }
                )

        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def mark_channel_as_read(self):
        from social.models import ChannelUserLastSeen, Channel
        channel = await sync_to_async(Channel.objects.get)(channel_id=self.channel_id)
        await sync_to_async(ChannelUserLastSeen.objects.update_or_create)(
            channel=channel,
            user=self.user,
            defaults={'last_seen_at': timezone.now()}
        )

    async def send_unread_counts(self):
        from social.models import Channel
        channels = await sync_to_async(list)(
            Channel.objects.filter(subscriber=self.user)
        )
        for channel in channels:
            unread_count = await sync_to_async(channel.unread_count_for_user)(self.user)
            await self.send(text_data=json.dumps({
                'type': 'unread_update',
                'channel_id': str(channel.channel_id),
                'unread_count': unread_count,
                'channel_name': channel.channel_name
            }))

    async def channel_message(self, event):
        """Triggered when a new message is broadcast to the group."""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'author': event.get('author'),
            'author_avatar': event.get('author_avatar', ''),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'file_url': event.get('file_url'),
            'file_name': event.get('file_name', ''),
            'time': event.get('time'),
            'message_id': event.get('message_id'),
            'reply_to': event.get('reply_to'),
            'link_preview': event.get('link_preview'),
        }))

    async def message_deleted(self, event):
        """Broadcast deletion to all channel members."""
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event.get('message_id'),
        }))

    async def typing_indicator(self, event):
        """Forward typing indicator only to other users."""
        if event['sender'] != self.user.username:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'sender': event['sender'],
                'is_typing': event['is_typing'],
            }))

    async def message_reaction(self, event):
        """Broadcast reaction updates to all channel members."""
        await self.send(text_data=json.dumps({
            'type': 'message_reaction',
            'message_id': event.get('message_id'),
            'reactions': event.get('reactions', {}),
            'actor': event.get('actor'),
            'user_reaction': event.get('user_reaction'),
        }))

    async def unread_update(self, event):
        """Triggered for notification/unread count updates."""
        await self.send(text_data=json.dumps({
            'type': 'unread_update',
            'channel_id': event.get('channel_id'),
            'unread_count': event.get('unread_count'),
            'channel_name': event.get('channel_name', ''),
            'message_preview': event.get('message_preview', ''),
            'action': event.get('action', 'update')
        }))


class UserConsumer(AsyncWebsocketConsumer):
    """Consumer for global user notifications (sidebar unread counts, etc.)"""
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.user_group_name = f'user_{self.user.id}_channels'
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def get_total_followed_unread(self):
        from social.models import Channel
        followed = await sync_to_async(list)(Channel.objects.filter(subscriber=self.user))
        total = 0
        for channel in followed:
            total += await sync_to_async(channel.unread_count_for_user)(self.user)
        return total

    async def unread_update(self, event):
        """Handle real-time notification previews in the sidebar/home view."""
        from social.models import ChannelMessage
        total_count = await self.get_total_followed_unread()

        last_msg = await sync_to_async(
            lambda: ChannelMessage.objects.filter(channel_id=event['channel_id']).order_by('-created_at').first()
        )()

        msg_preview = event.get('message_preview', 'New message')
        msg_type = 'text'

        if last_msg:
            if last_msg.file_type == 'audio':
                msg_preview = 'Audio message 🎤'
                msg_type = 'audio'
            elif last_msg.file_type == 'video':
                msg_preview = 'Video message 📹'
                msg_type = 'video'
            elif last_msg.file_type == 'image':
                msg_preview = 'Photo 📷'
                msg_type = 'image'
            elif last_msg.message:
                msg_preview = last_msg.message[:50]

        event.update({
            'message_preview': msg_preview,
            'message_type': msg_type,
            'total_followed_unread': total_count,
            'timestamp': timezone.now().isoformat()
        })

        await self.send(text_data=json.dumps(event))
