from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.utils import timezone
import json
import uuid
import base64
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.conf import settings


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
        
        print(f"DEBUG: Received data - Action: {action}")
        print(f"DEBUG: File data present: {'file' in data}")
        print(f"DEBUG: File name: {data.get('file_name')}")

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
            file_base64 = data.get("file") 
            file_name = data.get("file_name")
            pictureUrl = data.get("pictureUrl")
            now = timezone.now()
            formatted_time = now.strftime("%I:%M %p")
            
            print(f"DEBUG: File base64 preview: {str(file_base64)[:100] if file_base64 else 'None'}")
            
            # Save message and get the actual URL of the file 
            message_instance = await self.save_message(self.username, message, file_base64, file_name, pictureUrl)

            # Get the file URL from the instance
            file_url = None
            if hasattr(message_instance, 'file_url'):
                file_url = message_instance.file_url
            elif message_instance.file:
                file_url = message_instance.file.url
                # Ensure HTTPS in production
                if settings.USE_CLOUDINARY and not settings.DEBUG and file_url.startswith('http://'):
                    file_url = file_url.replace('http://', 'https://', 1)

            group_data = {
                "type": "chat_message",
                "username": username,
                "message": message,
                "file_url": file_url,
                "file_name": message_instance.file_name, 
                "file_type": message_instance.file_type, 
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
            "file_url": event.get("file_url"),
            "file_name": event.get("file_name"),
            "file_type": event.get("file_type"),
            "message_id": event["message_id"], 
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
    def save_message(self, username, message, file_data, file_name, pictureUrl): 
        """Saves the message (and file) to the database and returns the instance."""
        Channel, ChannelMessage = get_social_models()
        user_model = get_user_model()
        author_user = user_model.objects.get(username=username)

        channel = Channel.objects.get(channel_id=self.channel_id)

        msg = ChannelMessage(
            channel=channel,
            author=author_user, 
            message=message,
            pictureUrl=pictureUrl,
        )

        # Only process file if it exists
        if file_data and file_data != "null" and file_data != "None":
            try:
                # Handle the base64 data
                if file_data.startswith('data:'):
                    format, filestr = file_data.split(";base64,")
                else:
                    # Sometimes base64 might come without data: prefix
                    filestr = file_data
                    format = "application/octet-stream"
                
                # Generate file name if not provided
                if not file_name:
                    # Try to get extension from format
                    if '/' in format:
                        ext = format.split("/")[-1].split(';')[0]
                    else:
                        ext = 'bin'
                    file_name = f"{uuid.uuid4()}.{ext}"
                
                decoded_file = base64.b64decode(filestr)
                
                # Check file size (Cloudinary has limits)
                file_size = len(decoded_file)
                print(f"DEBUG: File size: {file_size} bytes")
                
                # Cloudinary limits: 100MB for video, 20MB for images, 20MB for raw
                if file_size > 100 * 1024 * 1024:  # 100MB
                    raise ValueError(f"File too large: {file_size} bytes")
                
                content_file = ContentFile(decoded_file, name=file_name)
                
                # Save to CloudinaryField - Cloudinary handles the upload
                msg.file.save(file_name, content_file, save=False)
                
                # Determine file type for our frontend
                name_lower = file_name.lower()
                if any(ext in name_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
                    msg.file_type = 'image'
                elif any(ext in name_lower for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']):
                    msg.file_type = 'video'
                elif any(ext in name_lower for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']):
                    msg.file_type = 'audio'
                else:
                    msg.file_type = 'document'
                
                msg.file_name = file_name
                
                print(f"DEBUG: File saved. Type: {msg.file_type}, Name: {file_name}")

            except Exception as e:
                print(f"FILE SAVE ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
                msg.file = None
                msg.file_type = None
                msg.file_name = None
        else:
            print("DEBUG: No file data received")
            msg.file = None
            msg.file_type = None
            msg.file_name = None

        # Save the instance
        msg.save()
        
        # Refresh to ensure we have the latest file data
        msg.refresh_from_db()
        
        # **CRITICAL**: If it's a video/audio, ensure Cloudinary processed it
        if msg.file and msg.file_type in ['video', 'audio']:
            print(f"DEBUG: {msg.file_type.upper()} file saved. URL: {msg.file.url}")
            
            # Store a secure URL
            if settings.USE_CLOUDINARY and not settings.DEBUG:
                # Ensure HTTPS for Cloudinary in production
                if msg.file.url.startswith('http://'):
                    msg.file_url = msg.file.url.replace('http://', 'https://', 1)
                else:
                    msg.file_url = msg.file.url
            else:
                msg.file_url = msg.file.url
        elif msg.file:
            msg.file_url = msg.file.url
        else:
            msg.file_url = None
        
        print(f"DEBUG: Final file URL: {msg.file_url}")

        return msg