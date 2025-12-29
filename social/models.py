from django.db import models
from cloudinary.models import CloudinaryField
from django.contrib.auth.models import User
from django.conf import settings
from django.templatetags.static import static
from django.utils import timezone
from datetime import date, timedelta
import calendar
import uuid
import os
from mimetypes import guess_type

 
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
    
    # Conditional picture field
    if settings.USE_CLOUDINARY:
        picture = CloudinaryField('picture', folder='profile_image', default='logo_iowyea')
    else:
        picture = models.ImageField(
            upload_to='profile_image/',
            default='male.png'
        )
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    online = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        # Capitalize address
        self.address = self.address.title()
        
        # Capitalize user names
        if self.user.first_name:
            self.user.first_name = self.user.first_name.capitalize()
        if self.user.last_name:
            self.user.last_name = self.user.last_name.capitalize()
        
        # Set full name
        self.full_name = f'{self.user.first_name} {self.user.last_name}'
        
        # Save user first
        self.user.save()
        
        # Save profile
        super().save(*args, **kwargs)

    def update_online_status(self, online=True):
        """Update online status - call this from WebSocket"""
        self.online = online
        self.last_seen = timezone.now()
        self.save(update_fields=['last_seen', 'online'])

    def get_status(self):
        """Always show accurate time since last seen"""
        now = timezone.now()
        diff = now - self.last_seen
        
        if diff.seconds < 60:
            return "Just now"
        elif diff.seconds < 3600:
            return f"{diff.seconds // 60}m ago"
        elif diff.days == 0:
            return f"{diff.seconds // 3600}h ago"
        elif diff.days == 1:
            return "Yesterday"
        else:
            return f"{diff.days}d ago"


    @property
    def is_recently_online(self):
        """Check if user was online in last 5 minutes"""
        diff = timezone.now() - self.last_seen
        return diff.seconds < 300

    @classmethod
    def mark_user_online(cls, user_id):
        """Mark user as online (static method)"""
        cls.objects.filter(user_id=user_id).update(
            online=True,
            last_seen=timezone.now()
        )

    @classmethod
    def mark_user_offline(cls, user_id):
        """Mark user as offline (static method)"""
        cls.objects.filter(user_id=user_id).update(online=False)

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username

class Post(models.Model):
    post_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    likes = models.ManyToManyField(User, related_name='like_post', blank=True)
    view = models.IntegerField(default=0, null=True, blank=True)
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
    
    def preview_type(self):
        if self.images.exists():
            return 'image'
        if self.video_file:
            return 'video'
        if self.file:
            return 'audio'
        return 'text'
    
    def preview_url(self):
        if self.images.exists():
            return self.images.first().image.url
        if self.video_file:
            return self.video_file.url
        if self.file:
            return self.file.url
        return None
    
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
    LIKE = 'like'
    COMMENT = 'comment'

    TYPES = (
        (LIKE, 'Like'),
        (COMMENT, 'Comment'),
    )

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_notifications'
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    notification_type = models.CharField(
        max_length=20,
        choices=TYPES,
        blank=True,
        null=True
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

class FollowNotification(models.Model):
    from_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_follow_notifications'
    )
    to_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_follow_notifications'
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['from_user', 'to_user']
    
    def __str__(self):
        return f"{self.from_user.username} followed {self.to_user.username}"

# --- START MESSAGE MODEL CORRECTION ---
class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receiver')
    conversation = models.TextField()
    
    # Add file_type field
    file_type = models.CharField(max_length=20, blank=True, null=True)  # 'image', 'video', 'audio'
    
    # Use CloudinaryField if USE_CLOUDINARY is True
    if settings.USE_CLOUDINARY:
        from cloudinary.models import CloudinaryField
        file = CloudinaryField(
            'message_file',
            resource_type='auto',
            folder='message_files',
            blank=True,
            null=True
        )
    else:
        file = models.FileField(upload_to='message_files/', blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    # Add like field
    like = models.ManyToManyField(User, related_name='liked_messages', blank=True)
    
    # REMOVED: message_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    def __str__(self):
        return f"{self.sender} to {self.receiver}: {self.conversation[:50]}"
    
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
# In models.py, update the ChannelMessage model
class ChannelMessage(models.Model):
    channelmessage_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    channel = models.ForeignKey(
        "Channel",
        on_delete=models.CASCADE,
        related_name="channel_messages"
    )
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField(blank=True)
    like = models.ManyToManyField(User, blank=True, related_name='message_likers')
    # Fields to store file info
    file_type = models.CharField(max_length=50, blank=True, null=True)
     # Use CloudinaryField if USE_CLOUDINARY is True, matching the folder in message.py
    if settings.USE_CLOUDINARY:
        file = CloudinaryField(
            'channelMessage_files',
            resource_type='auto', # Cloudinary requires 'video' for audio files
            folder='channelMessage_files', 
            blank=True,
            null=True
        )
    else:
        file = models.FileField(upload_to='message_file', blank=True, null=True) # Changed to 'message_file' for clarity
     
    created_at = models.DateTimeField(auto_now_add=True)

    # --- Utility Properties ---

    @property
    def chat_date_label(self):
        """
        Returns "Today", "Yesterday", weekday, or formatted date
        """
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
        """
        Returns time in 12-hour format
        """
        return self.created_at.strftime("%I:%M %p")

    def like_count(self):
        """
        Returns total number of likes
        """
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



class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']  # Most recent first
        verbose_name_plural = 'Search Histories'
    
    def __str__(self):
        return f"{self.user.username} - {self.query}"
    
    def save(self, *args, **kwargs):
        # Optional: Limit history to last 50 searches per user
        super().save(*args, **kwargs)
        
        # Keep only last 50 searches per user
        user_history = SearchHistory.objects.filter(user=self.user)
        if user_history.count() > 50:
            oldest = user_history.order_by('created_at').first()
            oldest.delete()