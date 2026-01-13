import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from asgiref.sync import sync_to_async

class ChannelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        # Check if user is authenticated
        if not self.user.is_authenticated:
            await self.close()
            return
        
        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = f'channel_{self.channel_id}'
        self.user_group_name = f'user_{self.user.id}_channels'
        
        # Join the specific channel group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        # Join user's personal group for cross-channel unread updates
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        # Leave both groups on disconnect
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket signals from the frontend (e.g., mark as read)"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'mark_as_read':
                await self.mark_channel_as_read()
                
                # Send confirmation back to the sender
                await self.send(text_data=json.dumps({
                    'type': 'marked_as_read',
                    'channel_id': self.channel_id,
                    'timestamp': timezone.now().isoformat()
                }))
                
                # Notify user's other open tabs/devices to clear unread counts
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
                
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def mark_channel_as_read(self):
        """Database operation to update last seen status"""
        from social.models import ChannelUserLastSeen, Channel
        channel = await sync_to_async(Channel.objects.get)(channel_id=self.channel_id)
        await sync_to_async(ChannelUserLastSeen.objects.update_or_create)(
            channel=channel,
            user=self.user,
            defaults={'last_seen_at': timezone.now()}
        )

    async def send_unread_counts(self):
        """Sends unread counts for all subscribed channels to the user"""
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
        """
        Triggered when a new message is broadcasted to the group.
        Includes reply_to metadata for WhatsApp-style real-time UI.
        """
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'author': event.get('author'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'file_url': event.get('file_url'),
            'time': event.get('time'),
            'message_id': event.get('message_id'),
            'created_at': event.get('created_at'),
            'reply_to': event.get('reply_to'), # Critical for Real-Time Replies
        }))

    async def unread_update(self, event):
        """Triggered for notification updates"""
        await self.send(text_data=json.dumps({
            'type': 'unread_update',
            'channel_id': event.get('channel_id'),
            'unread_count': event.get('unread_count'),
            'channel_name': event.get('channel_name', ''),
            'message_preview': event.get('message_preview', ''),
            'action': event.get('action', 'update')
        }))


class UserConsumer(AsyncWebsocketConsumer):
    """
    Consumer for global user notifications (sidebar unread counts, etc.)
    """
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
        """Handle real-time notification previews in the sidebar/home view"""
        from social.models import ChannelMessage
        total_count = await self.get_total_followed_unread()
        
        # Get preview of the actual last message
        last_msg = await sync_to_async(
            lambda: ChannelMessage.objects.filter(channel_id=event['channel_id']).order_by('-created_at').first()
        )()

        msg_preview = event.get('message_preview', "New message")
        msg_type = "text"

        if last_msg:
            if last_msg.file_type == 'audio':
                msg_preview = "Audio message 🎤"
                msg_type = "audio"
            elif last_msg.file_type == 'video':
                msg_preview = "Video message 📹"
                msg_type = "video"
            elif last_msg.file_type == 'image':
                msg_preview = "Photo 📷"
                msg_type = "image"
            elif last_msg.message:
                msg_preview = last_msg.message[:50]

        event.update({
            'message_preview': msg_preview,
            'message_type': msg_type,
            'total_followed_unread': total_count,
            'timestamp': timezone.now().isoformat()
        })
        
        await self.send(text_data=json.dumps(event))