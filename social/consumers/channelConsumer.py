from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.utils import timezone
import json
import uuid
import base64
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model


def get_social_models():
    # Deferred import to prevent circular dependency
    from social.models import Channel, ChannelMessage
    return Channel, ChannelMessage

def get_user_model_func():
    return get_user_model()


@database_sync_to_async
def like_unlike_message(message_id, user):
    """Handles the liking and unliking of a ChannelMessage."""
    Channel, ChannelMessage = get_social_models()
    try:
        # Use the primary key (channemessage_id) to get the message
        message = ChannelMessage.objects.get(channemessage_id=message_id)
        
        is_liked = False
        
        # Check if the user has already liked the message
        if user in message.like.all():
            # Unlike the message
            message.like.remove(user)
            is_liked = False
        else:
            # Like the message
            message.like.add(user)
            is_liked = True
        
        # Return the new count and whether the user currently likes it
        return message.like_count(), is_liked

    except ChannelMessage.DoesNotExist:
        return 0, False # Return 0 count if message not found


class ChannelConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']

        if not self.user or not self.user.is_authenticated:
            # Optionally close connection if user is not authenticated
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
        action = data.get("action")

        if action == "like_unlike":
            # --- LIKE/UNLIKE ACTION ---
            message_id = data.get("message_id")
            
            # Perform the database update asynchronously
            new_like_count, is_liked = await like_unlike_message(message_id, self.user)
            
            # Broadcast the update to all clients in the group
            await self.channel_layer.group_send(self.group_name, {
                "type": "like_update",
                "message_id": message_id,
                "like_count": new_like_count,
                "user_liked": is_liked
            })

        else: 
            # --- NEW MESSAGE ACTION ---
            username = self.user.username
            message = data.get("message")
            # 👇 UPDATED: Get generic file data and name
            file_base64 = data.get("file") 
            file_name = data.get("file_name")
            # 👆
            pictureUrl = data.get("pictureUrl")
            now = timezone.now()
            formatted_time = now.strftime("%I:%M %p")
            
            # Save message and get the actual URL of the file 
            # 👇 Updated call to save_message
            message_instance = await self.save_message(self.username, message, file_base64, file_name, pictureUrl)

            group_data = {
                "type": "chat_message",
                "username": username,
                "message": message,
                # 👇 UPDATED: Broadcast generic file details
                "file_url": message_instance.file.url if message_instance.file else None,
                "file_name": message_instance.file_name,
                "file_type": message_instance.file_type, 
                # 👆
                "message_id": str(message_instance.channemessage_id), 
                "pictureUrl": pictureUrl,
                "time": formatted_time
            }

            await self.channel_layer.group_send(self.group_name, group_data)

    async def chat_message(self, event):
        """Sends new chat message data to the WebSocket."""
        text_data = {
            "type": "Response",
            "username": event["username"],
            "message": event["message"],
            # 👇 UPDATED: Send generic file details
            "file_url": event["file_url"],
            "file_name": event["file_name"],
            "file_type": event["file_type"],
            # 👆
            "message_id": event["message_id"], # Included for real-time liking
            "pictureUrl": event["pictureUrl"],
            "time": event["time"]
        }

        await self.send(text_data=json.dumps(text_data))

    async def like_update(self, event):
        """Sends like update data to the WebSocket."""
        text_data = {
            "type": "like_response",
            "message_id": event["message_id"],
            "like_count": event["like_count"],
            "user_liked": event["user_liked"]
        }
        await self.send(text_data=json.dumps(text_data))

    @database_sync_to_async
    # 👇 UPDATED: Receive file_data and file_name
    def save_message(self, username, message, file_data, file_name, pictureUrl): 
        """Saves the message (and file) to the database and returns the instance."""
        Channel, ChannelMessage = get_social_models()
        user_model = get_user_model()
        author_user = user_model.objects.get(username=username)

        channel = Channel.objects.get(channel_id=self.channel_id)

        msg = ChannelMessage(
            channel=channel,
            author=author_user, # Use the User object
            message=message,
            pictureUrl=pictureUrl,
            # 👇 CRITICAL FIX: Set file_name (can be None)
            file_name=file_name,
        )

        # Only process file if it exists
        if file_data:
            try:
                # file_data looks like: "data:image/png;base64,AAAAAA..."
                format, filestr = file_data.split(";base64,")
                ext = format.split("/")[-1]

                # Use the original file name if available, otherwise use a UUID
                if not file_name:
                    file_name = f"{uuid.uuid4()}.{ext}"
                
                decoded_file = base64.b64decode(filestr)

                # 👇 Changed from msg.image to msg.file
                msg.file.save(file_name, ContentFile(decoded_file), save=False) 
                
            except Exception as e:
                print("FILE SAVE ERROR:", str(e))

        msg.save()

        # Return the message instance
        return msg
