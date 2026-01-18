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
    reposts = models.ManyToManyField(User, related_name='repost_post', blank=True)  # NEW
    view = models.IntegerField(default=0, null=True, blank=True)
    share = models.IntegerField(default=0, null=True, blank=True)
    content = models.TextField()
    
    # Repost related fields - NEW
    is_repost = models.BooleanField(default=False)
    original_post = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='reposts_made')
    repost_content = models.TextField(blank=True, null=True)  # Optional caption for repost
    
    if settings.USE_CLOUDINARY:
        video_file = CloudinaryField('video', resource_type='video', folder='post_files', blank=True)
    else:
        video_file = models.FileField(upload_to='post_file', blank=True)
    
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video', folder='post_files', blank=True)
    else:
        file = models.FileField(upload_to='post_file', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.author.username
    
    def preview_type(self):
        if self.is_repost and self.original_post:
            # For reposts, show the original post's media type
            return self.original_post.preview_type()
        if self.images.exists():
            return 'image'
        if self.video_file:
            return 'video'
        if self.file:
            return 'audio'
        return 'text'
    
    def preview_url(self):
        if self.is_repost and self.original_post:
            # For reposts, show the original post's media
            return self.original_post.preview_url()
        if self.images.exists():
            return self.images.first().image.url
        if self.video_file:
            return self.video_file.url
        if self.file:
            return self.file.url
        return None
    
    def get_original_author(self):
        """Get the original author for reposts"""
        if self.is_repost and self.original_post:
            return self.original_post.author
        return self.author
    
    def get_original_post_id(self):
        """Get the original post ID for reposts"""
        if self.is_repost and self.original_post:
            return self.original_post.post_id
        return self.post_id
    
    def get_republished_content(self):
        """Get content for display, handling reposts"""
        if self.is_repost and self.original_post:
            return self.original_post.content
        return self.content

 
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

class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receiver')
    conversation = models.TextField()
    
    # Add reply_to field for message replies
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, 
                                null=True, blank=True, related_name='replies')
    
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




class Channel(models.Model):
    # Original Fields
    channel_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_channels')
    channel_name = models.CharField(max_length=200)
    about = models.TextField(blank=True)
    subscriber = models.ManyToManyField(User, blank=True, related_name='subscribed_channels')
    image = models.ImageField(upload_to='channel_image', default='male.png')
    created_at = models.DateTimeField(auto_now_add=True)
    admins = models.ManyToManyField(User, blank=True, related_name='admin_of_channel')
    # NEW FIELDS for Admin Controls
    # stores users who are banned/blocked from re-joining or viewing the channel
    blocked_users = models.ManyToManyField(User, blank=True, related_name='blocked_from_channels')
    
    # If True, only the channel_owner can send messages. Regular subscribers can only read.
    is_broadcast_only = models.BooleanField(default=False)

    def is_user_admin(self, user):
        return user == self.channel_owner or self.admins.filter(id=user.id).exists()

    def __str__(self):
        return self.channel_name

    def unread_count_for_user(self, user):
        """
        Calculates the number of messages sent after the user's last visit.
        Note: Requires ChannelUserLastSeen and ChannelMessage models to exist.
        """
        if not user.is_authenticated:
            return 0
        
        # We import inside the method to avoid circular import issues if models are in the same file
        from .models import ChannelMessage, ChannelUserLastSeen
        
        # Get user's last seen timestamp for this specific channel
        last_seen = ChannelUserLastSeen.objects.filter(
            channel=self,
            user=user
        ).first()
        
        if last_seen:
            # Count messages created after the 'last_seen_at' timestamp
            return ChannelMessage.objects.filter(
                channel=self,
                created_at__gt=last_seen.last_seen_at
            ).exclude(author=user).count()
        
        # If the user has never opened the channel, count all messages they didn't author
        return ChannelMessage.objects.filter(
            channel=self
        ).exclude(author=user).count()

    class Meta:
        verbose_name = "Channel"
        verbose_name_plural = "Channels"
        ordering = ['-created_at']
class ChannelUserLastSeen(models.Model):
    """Tracks when a user last viewed a channel"""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    last_seen_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        unique_together = ['channel', 'user']
    
    def __str__(self):
        return f"{self.user.username} last saw {self.channel.channel_name} at {self.last_seen_at}"

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
    # Add reply_to field for message replies
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, 
                                null=True, blank=True, related_name='replies')
    file_type = models.CharField(max_length=50, blank=True, null=True)
    
    if settings.USE_CLOUDINARY:
        file = CloudinaryField(
            'channelMessage_files',
            resource_type='auto',
            folder='channelMessage_files', 
            blank=True,
            null=True
        )
    else:
        file = models.FileField(upload_to='message_file', blank=True, null=True)
     
    created_at = models.DateTimeField(auto_now_add=True)

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
    
    def __str__(self):
        return f"{self.author.username}: {self.message[:50]}"
    
class Market(models.Model):
    product_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product_owner = models.ForeignKey(User, related_name='products', on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    product_price = models.IntegerField()
    product_location = models.CharField(max_length=300)
    product_description = models.TextField()
    product_availability = models.CharField(max_length=150)
    product_condition = models.CharField(max_length=50, choices=[('New', 'New'), ('Used', 'Used - Like New'), ('Fair', 'Used - Fair Condition')], default='New')
    views_count = models.PositiveIntegerField(default=0) # Track how many people saw the product
    is_promoted = models.BooleanField(default=False) # For paid ads
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