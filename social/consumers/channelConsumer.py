
from channels.generic.websocket import AsyncWebsocketConsumer
import json
from django.utils import timezone
from asgiref.sync import sync_to_async
from social.models import ChannelUserLastSeen, Channel, ChannelMessage

class ChannelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        
        self.channel_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = f'channel_{self.channel_id}'
        self.user_group_name = f'user_{self.user.id}_channels'
        
        # Join channel group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        # Join user's personal group for unread updates
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"Mobile WebSocket connected: {self.user.username} to channel {self.channel_id}")

    async def disconnect(self, close_code):
        # Leave groups
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )
        
        print(f"Mobile WebSocket disconnected: {self.user.username}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'mark_as_read':
                # Mark channel as read for this user
                await self.mark_channel_as_read()
                
                # Send confirmation
                await self.send(text_data=json.dumps({
                    'type': 'marked_as_read',
                    'channel_id': self.channel_id,
                    'timestamp': timezone.now().isoformat()
                }))
                
                # Notify user's other connections
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
                # Send current unread counts for all channels
                await self.send_unread_counts()
                
        except Exception as e:
            print(f"Error in receive: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def mark_channel_as_read(self):
        """Mark a channel as read for the current user"""
        channel = await sync_to_async(Channel.objects.get)(channel_id=self.channel_id)
        
        await sync_to_async(ChannelUserLastSeen.objects.update_or_create)(
            channel=channel,
            user=self.user,
            defaults={'last_seen_at': timezone.now()}
        )

    async def send_unread_counts(self):
        """Send unread counts for all subscribed channels"""
        # Get all channels user is subscribed to
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
        """Handle new channel messages"""
        # Send message to everyone in the channel
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'author': event.get('author'),
            'message': event.get('message'),
            'file_type': event.get('file_type'),
            'file_url': event.get('file_url'),
            'time': event.get('time'),
            'message_id': event.get('message_id'),
            'created_at': event.get('created_at'),
        }))

    async def unread_update(self, event):
        """Handle unread count updates"""
        # Send unread update to user
        await self.send(text_data=json.dumps({
            'type': 'unread_update',
            'channel_id': event.get('channel_id'),
            'unread_count': event.get('unread_count'),
            'channel_name': event.get('channel_name', ''),
            'message_preview': event.get('message_preview', ''),
            'action': event.get('action', 'update')
        }))
class UserConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.user_group_name = f'user_{self.user.id}_channels'
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept() #

    async def unread_update(self, event):
        """
        Triggered when a new message is sent to a channel.
        We now calculate the TOTAL for followed channels and send it.
        """
        # Calculate total unread only for channels the user follows
        total_unread = await self.get_total_followed_unread()
        
        # Attach the global total to the event data
        event['total_followed_unread'] = total_unread
        await self.send(text_data=json.dumps(event)) #

    async def get_total_followed_unread(self):
        """Helper to sum unread counts for followed channels only"""
        # Get channels where the user is a subscriber
        followed_channels = await sync_to_async(list)(
            Channel.objects.filter(subscriber=self.user)
        )
        total = 0
        for channel in followed_channels:
            total += await sync_to_async(channel.unread_count_for_user)(self.user)
        return total

    async def mark_channel_read(self, channel_id):
        """Updated to send the new total after marking a channel as read"""
        channel = await sync_to_async(Channel.objects.get)(channel_id=channel_id)
        await sync_to_async(ChannelUserLastSeen.objects.update_or_create)(
            channel=channel, user=self.user,
            defaults={'last_seen_at': timezone.now()}
        )
        # Broadcast the new lower total to the header
        new_total = await self.get_total_followed_unread()
        await self.send(text_data=json.dumps({
            'type': 'unread_update',
            'total_followed_unread': new_total,
            'channel_id': channel_id,
            'unread_count': 0
        })) #


