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
from django.core.exceptions import ValidationError
import re
from urllib.parse import urlparse
from html import escape
import bleach


# Security configurations
ALLOWED_HTML_TAGS = []  # Empty list means no HTML tags allowed
ALLOWED_ATTRIBUTES = {}  # Empty dict means no attributes allowed
MAX_TEXT_LENGTHS = {
    'bio': 300,
    'location': 200,
    'content': 10000,  # For posts and messages
    'comment': 5000,
    'conversation': 5000,
    'about': 1000,
    'product_description': 5000,
    'product_name': 100,
    'channel_name': 200,
}


def sanitize_text(text, field_name=None):
    """
    Sanitize text input by removing HTML/JS and limiting length
    """
    if not text:
        return text
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # Escape HTML entities first
    text = escape(text)
    
    # Use bleach to remove any remaining HTML/JS
    text = bleach.clean(text, tags=ALLOWED_HTML_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    
    # Remove script tags and event handlers
    script_patterns = [
        r'<script.*?>.*?</script>',
        r'on\w+\s*=\s*["\'][^"\']*["\']',
        r'javascript:',
        r'data:text/html',
        r'vbscript:',
    ]
    
    for pattern in script_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Limit length based on field
    if field_name and field_name in MAX_TEXT_LENGTHS:
        max_len = MAX_TEXT_LENGTHS[field_name]
        if len(text) > max_len:
            text = text[:max_len]
    
    return text.strip()


def validate_phone_number(phone):
    """Validate and sanitize phone number"""
    if not phone:
        return ""
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone)
    
    # E.164 format validation (max 15 digits)
    if not re.match(r'^\+?[1-9]\d{1,14}$', cleaned):
        raise ValidationError('Please enter a valid phone number in international format')
    
    return cleaned


def validate_url(url):
    """Validate and sanitize URL"""
    if not url:
        return ""
    
    url = url.strip()
    
    # Add https:// if not present
    if url and not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Validate URL format
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            raise ValidationError('Please enter a valid URL')
        
        # Check for dangerous protocols
        if result.scheme not in ['http', 'https']:
            raise ValidationError('Only http and https protocols are allowed')
        
        # Prevent potential XSS in URLs
        if any(char in url for char in ['<', '>', '"', "'", '(', ')', '`']):
            raise ValidationError('URL contains invalid characters')
        
        return url
    except Exception:
        raise ValidationError('Please enter a valid URL')


def validate_file_extension(value):
    """Validate file extensions"""
    if value:
        ext = os.path.splitext(value.name)[1].lower()
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.mov', '.avi', '.mp3', '.wav', '.pdf', '.doc', '.docx']
        
        if ext not in allowed_extensions:
            raise ValidationError(f'File type {ext} is not allowed. Allowed types: {", ".join(allowed_extensions)}')


def validate_file_size(value, max_size_mb=50):
    """Validate file size"""
    if value:
        max_size = max_size_mb * 1024 * 1024  # Convert to bytes
        if value.size > max_size:
            raise ValidationError(f'File size must be under {max_size_mb}MB')


# models.py - Update Profile model
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    followings = models.ManyToManyField('self', symmetrical=False, related_name='followers', blank=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    full_name = models.CharField(max_length=200, blank=True)
    is_verify = models.BooleanField(default=False)
    address = models.TextField()
    website = models.URLField(max_length=500, blank=True, default='')  # Changed from 'address' to 'website'
    bio = models.CharField(max_length=300, blank=True, default='')
    location = models.CharField(max_length=200, blank=True, default='')  # Changed from TextField to CharField
    
    # Conditional picture field from your original code
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

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username

    def clean(self):
        """Validate the data before saving"""
        super().clean()
        
        # Sanitize all text fields
        self.bio = sanitize_text(self.bio, 'bio')
        self.location = sanitize_text(self.location, 'location')
        self.full_name = sanitize_text(self.full_name)
        self.address = sanitize_text(self.address)
        
        # Validate website
        if self.website:
            try:
                self.website = validate_url(self.website)
            except ValidationError as e:
                raise ValidationError({'website': str(e)})
        
        # Validate phone number
        if self.phone:
            try:
                self.phone = validate_phone_number(self.phone)
            except ValidationError as e:
                raise ValidationError({'phone': str(e)})
        
        # Validate picture filename
        if self.picture and hasattr(self.picture, 'name'):
            validate_file_extension(self.picture)
            validate_file_size(self.picture, max_size_mb=10)

    def save(self, *args, **kwargs):
        # Clean the data before saving
        self.full_clean()
        
        # Capitalize location
        if self.location:
            self.location = self.location.strip().title()
        
        # Capitalize user names and save User object
        if self.user:
            if self.user.first_name:
                self.user.first_name = sanitize_text(self.user.first_name).capitalize()
            if self.user.last_name:
                self.user.last_name = sanitize_text(self.user.last_name).capitalize()
            
            # Set full name based on updated names
            self.full_name = f'{self.user.first_name} {self.user.last_name}'.strip()
            self.user.save()
        
        super().save(*args, **kwargs)

    @property
    def is_online(self):
        """
        Returns True if user is marked online AND was seen in the last 60 seconds.
        This prevents users from appearing 'Online' forever if their connection drops abruptly.
        """
        if self.online:
            # Check if last_seen was within the last 1 minute
            return self.last_seen > timezone.now() - timedelta(seconds=60)
        return False

    def get_status_display(self):
        """Returns a string representing the current status (Online or Last Seen)"""
        if self.is_online:
            return "Online"
        
        now = timezone.now()
        diff = now - self.last_seen
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                return f"{diff.seconds // 60}m ago"
            else:
                return f"{diff.seconds // 3600}h ago"
        elif diff.days == 1:
            return "Yesterday"
        else:
            return f"{diff.days}d ago"

    @property
    def is_recently_online(self):
        """Check if user was online in last 5 minutes (for badges/lists)"""
        diff = timezone.now() - self.last_seen
        return diff.total_seconds() < 300

    def update_online_status(self, online=True):
        """Call this from WebSocket to update status efficiently"""
        self.online = online
        self.last_seen = timezone.now()
        self.save(update_fields=['last_seen', 'online'])

    @classmethod
    def mark_user_online(cls, user_id):
        """Static method to mark user online without loading full object"""
        cls.objects.filter(user_id=user_id).update(
            online=True,
            last_seen=timezone.now()
        )

    @classmethod
    def mark_user_offline(cls, user_id):
        """Static method to mark user offline"""
        cls.objects.filter(user_id=user_id).update(online=False)
    
    @property
    def safe_website(self):
        """Return sanitized website URL for display"""
        if not self.website:
            return ""
        
        try:
            return validate_url(self.website)
        except ValidationError:
            return ""
    
    @property
    def display_website(self):
        """Return a display-friendly version of the website"""
        if not self.website:
            return ""
        
        website = self.safe_website
        if not website:
            return ""
        
        # Remove protocol for display
        display_url = website.replace('https://', '').replace('http://', '')
        # Remove www. if present
        if display_url.startswith('www.'):
            display_url = display_url[4:]
        
        # Truncate if too long
        if len(display_url) > 30:
            return display_url[:27] + '...'
        return display_url


class Post(models.Model):
    post_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    likes = models.ManyToManyField(User, related_name='like_post', blank=True)
    reposts = models.ManyToManyField(User, related_name='repost_post', blank=True)  # NEW
    view = models.IntegerField(default=0, null=True, blank=True)
    share = models.IntegerField(default=0, null=True, blank=True)
    content = models.TextField(blank=True, null=True)
    
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
    
    def clean(self):
        """Validate post data"""
        super().clean()
        
        # Sanitize content
        self.content = sanitize_text(self.content, 'content')
        if self.repost_content:
            self.repost_content = sanitize_text(self.repost_content, 'content')
        
        # Validate file fields
        if self.video_file and hasattr(self.video_file, 'name'):
            validate_file_extension(self.video_file)
            validate_file_size(self.video_file, max_size_mb=100)
        
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
        
        # Validate view and share counts (prevent negative values)
        if self.view and self.view < 0:
            self.view = 0
        if self.share and self.share < 0:
            self.share = 0

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
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
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')
    
    def clean(self):
        """Validate image"""
        super().clean()
        if self.image:
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class PostComment(models.Model):
    comment_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='comment_image/', blank=True)
    
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video', folder='comment_files', blank=True)
    else:
        file = models.FileField(upload_to='comment_file', blank=True)
    
    like = models.ManyToManyField(User, related_name='comment_likes', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def clean(self):
        """Validate comment data"""
        super().clean()
        
        # Sanitize comment text
        self.comment = sanitize_text(self.comment, 'comment')
        
        # Validate files
        if self.image and hasattr(self.image, 'name'):
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)
        
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=20)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


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
    conversation = models.TextField(blank=True, null=True)
    
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
    
    def clean(self):
        """Validate message data"""
        super().clean()
        
        # Sanitize conversation text
        self.conversation = sanitize_text(self.conversation, 'conversation')
        
        # Validate file
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
        
        # Sanitize file_type if provided
        if self.file_type:
            self.file_type = sanitize_text(self.file_type)
            if self.file_type not in ['image', 'video', 'audio', 'document']:
                self.file_type = None
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
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
    about = models.TextField(blank=True, null=True)
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
    
    def clean(self):
        """Validate channel data"""
        super().clean()
        
        # Sanitize text fields
        self.channel_name = sanitize_text(self.channel_name, 'channel_name')
        self.about = sanitize_text(self.about, 'about')
        
        # Validate image
        if self.image and hasattr(self.image, 'name') and self.image.name != 'male.png':
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

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
    message = models.TextField(blank=True, null=True)
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
    
    def clean(self):
        """Validate channel message data"""
        super().clean()
        
        # Sanitize message text
        self.message = sanitize_text(self.message, 'content')
        
        # Validate file
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
        
        # Sanitize file_type if provided
        if self.file_type:
            self.file_type = sanitize_text(self.file_type)
            if self.file_type not in ['image', 'video', 'audio', 'document']:
                self.file_type = None
    
    def save(self, *args, **kwargs):
        self.full_clean()
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
    
    def __str__(self):
        return f"{self.author.username}: {self.message[:50]}"


class Market(models.Model):
    product_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product_owner = models.ForeignKey(User, related_name='products', on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    product_price = models.IntegerField()
    product_location = models.CharField(max_length=300)
    product_description = models.TextField(blank=True, null=True)
    product_availability = models.CharField(max_length=150)
    product_condition = models.CharField(max_length=50, choices=[('New', 'New'), ('Used', 'Used - Like New'), ('Fair', 'Used - Fair Condition')], default='New')
    views_count = models.PositiveIntegerField(default=0)  # Track how many people saw the product
    is_promoted = models.BooleanField(default=False)  # For paid ads
    product_category = models.CharField(max_length=100)
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)
    posted_on = models.DateTimeField(auto_now_add=True)
    
    def clean(self):
        """Validate market product data"""
        super().clean()
        
        # Sanitize text fields
        self.product_name = sanitize_text(self.product_name, 'product_name')
        self.product_location = sanitize_text(self.product_location)
        self.product_description = sanitize_text(self.product_description, 'product_description')
        self.product_availability = sanitize_text(self.product_availability)
        self.product_category = sanitize_text(self.product_category)
        
        # Validate product price (prevent negative or excessive prices)
        if self.product_price < 0:
            raise ValidationError({'product_price': 'Price cannot be negative'})
        if self.product_price > 1000000000:  # 1 billion limit
            raise ValidationError({'product_price': 'Price is too high'})
        
        # Validate views_count
        if self.views_count < 0:
            self.views_count = 0
        
        # Validate WhatsApp number if provided
        if self.whatsapp_number:
            try:
                self.whatsapp_number = validate_phone_number(self.whatsapp_number)
            except ValidationError as e:
                raise ValidationError({'whatsapp_number': str(e)})
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class MarketImage(models.Model):
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='images')
    product_image = models.ImageField(upload_to='product_images/')
    
    def clean(self):
        """Validate market image"""
        super().clean()
        if self.product_image:
            validate_file_extension(self.product_image)
            validate_file_size(self.product_image, max_size_mb=10)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']  # Most recent first
        verbose_name_plural = 'Search Histories'
    
    def __str__(self):
        return f"{self.user.username} - {self.query}"
    
    def clean(self):
        """Sanitize search query"""
        super().clean()
        self.query = sanitize_text(self.query)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        
        super().save(*args, **kwargs)
        
        # Optional: Limit history to last 50 searches per user
        user_history = SearchHistory.objects.filter(user=self.user)
        if user_history.count() > 50:
            oldest = user_history.order_by('created_at').first()
            oldest.delete()