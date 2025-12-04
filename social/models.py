from django.db import models
from cloudinary.models import CloudinaryField
from django.contrib.auth.models import User
from django.conf import settings
from django.templatetags.static import static
from datetime import date, timedelta
import calendar
import uuid
import os
def get_default_profile_image():
    if settings.DEBUG:  # Local development
        return 'male.png'  # Make sure this file exists in MEDIA_ROOT
    else:  # Production
        return 'male_rzf6mv'
# Create your models here.

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    followings = models.ManyToManyField('self', symmetrical=False, related_name='followers', blank=True)
    phone = models.CharField(max_length=20)
    full_name = models.CharField(max_length=200, blank=True)
    is_verify = models.BooleanField(default=False)
    address = models.TextField()
    bio = models.CharField(max_length=300)
    location = models.TextField()
    if settings.USE_CLOUDINARY:
        picture = CloudinaryField('picture', folder='profile_image', default='v1763882783/male_rzf6mv.png')
    else:
        picture = models.ImageField(
            upload_to='profile_image/',
            default='male.png'
        )
    created_at = models.DateTimeField(auto_now_add=True)
    # Helper for follower 
    def save(self, *args, **kwargs):
        self.address = self.address.title()
        self.user.first_name=self.user.first_name.capitalize()
        self.user.last_name=self.user.last_name.capitalize()
        self.full_name = f'{self.user.first_name} {self.user.last_name}'
        self.user.save()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username


class Post(models.Model):
    post_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    likes = models.ManyToManyField(User, related_name='like_post', blank=True)
    content = models.TextField()
    if settings.USE_CLOUDINARY:
        video_file = CloudinaryField('video', resource_type='video',folder='post_files',blank=True)
    else:
        video_file = models.FileField(upload_to='post_file', blank=True)
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video',folder='post_files',blank=True)
    else:
        file = models.FileField(upload_to='post_file', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.author.username

class PostImage(models.Model):
    post=models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')


class PostComment(models.Model):
    comment_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    image = models.ImageField(upload_to='comment_image/', blank=True)
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video',folder='comment_files',blank=True)
    else:
        file = models.FileField(upload_to='comment_file', blank=True)
    like = models.ManyToManyField(User, related_name='comment_likes', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_receiver')
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_sender')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True)
    message=models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


# --- START MESSAGE MODEL CORRECTION ---
class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receiver')
    conversation = models.TextField()
    
    # Use CloudinaryField if USE_CLOUDINARY is True, matching the folder in message.py
    if settings.USE_CLOUDINARY:
        file = CloudinaryField(
            'audio_message',
            resource_type='video', # Cloudinary requires 'video' for audio files
            folder='message_files', 
            blank=True
        )
    else:
        file = models.FileField(upload_to='message_file', blank=True) # Changed to 'message_file' for clarity
        
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    @property
    def chat_date_label(self):
        message_date = self.created_at.date()
        today = date.today()
        yesterday = today - timedelta(days=1)
        if message_date == today:
            return "Today"
        elif message_date == yesterday:
            return "Yesterday"
        elif today - message_date < timedelta(days=7):
            return calendar.day_name[message_date.weekday()]
        else:
            return self.created_at.strftime("%B %d, %Y")
    @property
    def chat_time(self):
        return self.created_at.strftime("%I:%M %p")
# --- END MESSAGE MODEL CORRECTION ---


class Channel(models.Model):
    channel_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    channel_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_author')
    channel_name = models.CharField(max_length=200)
    about = models.TextField()
    subscriber = models.ManyToManyField(User, blank=True, related_name='channel_subscriber')
    image=models.ImageField(upload_to='channel_image', default='male.png')
    created_at = models.DateTimeField(auto_now_add=True)
# --- CRITICAL: CORRECTED ChannelMessage MODEL ---
class ChannelMessage(models.Model):
    channemessage_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    channel = models.ForeignKey("social.Channel", on_delete=models.CASCADE, related_name="channel_messages")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    pictureUrl = models.TextField(blank=True)
    message = models.TextField(blank=True)
    like = models.ManyToManyField(User, blank=True, related_name='message_likers')

    if settings.USE_CLOUDINARY:
        file = CloudinaryField(
            'channel_file',
            resource_type='raw',
            folder='channel_files',
            blank=True,
            null=True,
            use_filename=True,
            unique_filename=True,
            overwrite=False,
        )
    else:
        file = models.FileField(upload_to='channel_files', blank=True, null=True)

    file_type = models.CharField(max_length=50, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def detect_file_type(self, name):
        name = name.lower()
        if any(x in name for x in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
            return "image"
        if any(x in name for x in ['.mp4', '.mov', '.avi', '.mkv', '.webm']):
            return "video"
        if any(x in name for x in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']):
            return "audio"
        return "document"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = os.path.basename(self.file.name)
            self.file_type = self.detect_file_type(self.file_name)

            url = str(self.file.url)
            if settings.USE_CLOUDINARY and not settings.DEBUG and url.startswith("http://"):
                self.file_url = url.replace("http://", "https://", 1)
            else:
                self.file_url = url
        else:
            self.file_name = None
            self.file_type = None
            self.file_url = None

        super().save(*args, **kwargs)

    @property
    def chat_date_label(self):
        d = self.created_at.date()
        t = date.today()
        if d == t:
            return "Today"
        if d == t - timedelta(days=1):
            return "Yesterday"
        if (t - d).days < 7:
            return calendar.day_name[d.weekday()]
        return self.created_at.strftime("%B %d, %Y")

    @property
    def chat_time(self):
        return self.created_at.strftime("%I:%M %p")

    def like_count(self):
        return self.like.count()



# --- END CORRECTED ChannelMessage MODEL ---

class Market(models.Model):
    product_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product_owner = models.ForeignKey(User, related_name='products', on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    product_price = models.IntegerField()
    product_location = models.CharField(max_length=300)
    product_description = models.TextField()
    product_availability = models.CharField(max_length=150)
    product_category = models.CharField(max_length=100)
    posted_on = models.DateTimeField(auto_now_add=True)

class MarketImage(models.Model):
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='images')
    product_image = models.ImageField(upload_to='product_images/')
