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
    'comment': 5000,
    'conversation': 5000,
    'about': 1000,
    'product_description': 5000,
    'product_name': 100,
    'channel_name': 200,
    'profession': 150,
}

def sanitize_text(text, field_name=None):
    """
    Sanitize text input by removing HTML/JS and limiting length.
    Now supports punctuation like ?, ', and " correctly.
    """
    if not text:
        return text
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # IMPORTANT: We removed 'text = escape(text)' here.
    # bleach.clean handles security escaping automatically without double-encoding symbols.
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
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.mov', '.avi', '.mp3', '.wav', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt']
        
        if ext not in allowed_extensions:
            raise ValidationError(f'File type {ext} is not allowed. Allowed types: {", ".join(allowed_extensions)}')


def validate_file_size(value, max_size_mb=50):
    """Validate file size"""
    if value:
        max_size = max_size_mb * 1024 * 1024  # Convert to bytes
        if value.size > max_size:
            raise ValidationError(f'File size must be under {max_size_mb}MB')



class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    followings = models.ManyToManyField('self', symmetrical=False, related_name='followers', blank=True)
    blocked_users = models.ManyToManyField('self', symmetrical=False, related_name='blocked_by', blank=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    full_name = models.CharField(max_length=200, blank=True)
    is_verify = models.BooleanField(default=False)
    address = models.TextField(null=True, blank=True)
    website = models.URLField(max_length=500, blank=True, default='')
    bio = models.CharField(max_length=300, blank=True, default='')
    location = models.CharField(max_length=200, blank=True, default='')

    # ── Privacy settings ─────────────────────────────────────────
    PRIVACY_PUBLIC        = 'public'
    PRIVACY_FOLLOWERS     = 'followers_only'
    PRIVACY_PRIVATE       = 'private'
    PRIVACY_CHOICES = [
        (PRIVACY_PUBLIC,    'Everyone'),
        (PRIVACY_FOLLOWERS, 'Followers only'),
        (PRIVACY_PRIVATE,   'Nobody (Hidden)'),
    ]
    privacy_level = models.CharField(
        max_length=20,
        choices=PRIVACY_CHOICES,
        default=PRIVACY_PUBLIC,
        db_index=True,
        help_text='Controls who can view this profile details',
    )
    
    if settings.USE_CLOUDINARY:
        picture = CloudinaryField('picture', folder='profile_image', default='logo_iowyea')
    else:
        picture = models.ImageField(upload_to='profile_image/', default='male.png')
    
    # ── Gender ────────────────────────────────────────────────
    GENDER_MALE        = 'male'
    GENDER_FEMALE      = 'female'
    GENDER_NON_BINARY  = 'non_binary'
    GENDER_PREFER_NOT  = 'prefer_not_to_say'
    GENDER_CHOICES = [
        (GENDER_MALE,       'Male'),
        (GENDER_FEMALE,     'Female'),
        (GENDER_NON_BINARY, 'Non-binary'),
        (GENDER_PREFER_NOT, 'Prefer not to say'),
    ]
    gender = models.CharField(
        max_length=20,
        choices=GENDER_CHOICES,
        blank=True,
        default='',
    )

    date_of_birth = models.DateField(null=True, blank=True)

    # ── Gender / DOB visibility toggles ─────────────────────────
    show_gender       = models.BooleanField(default=True,  help_text='Show gender on public profile')
    show_dob          = models.BooleanField(default=False, help_text='Show date of birth on public profile')

    profession       = models.CharField(max_length=150, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    online = models.BooleanField(default=False)

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username

    def clean(self):
        super().clean()
        self.bio          = sanitize_text(self.bio, 'bio')
        self.location     = sanitize_text(self.location, 'location')
        self.full_name    = sanitize_text(self.full_name)
        self.address      = sanitize_text(self.address)
        self.profession      = sanitize_text(self.profession,      'profession')
        if self.website:
            try:
                self.website = validate_url(self.website)
            except ValidationError as e:
                raise ValidationError({'website': str(e)})
        
        if self.phone:
            try:
                self.phone = validate_phone_number(self.phone)
            except ValidationError as e:
                raise ValidationError({'phone': str(e)})
        
        # Validate privacy_level against allowed values
        valid_privacy = [c[0] for c in self.PRIVACY_CHOICES]
        if self.privacy_level not in valid_privacy:
            self.privacy_level = self.PRIVACY_PUBLIC

        if self.picture and hasattr(self.picture, 'name'):
            validate_file_extension(self.picture)
            validate_file_size(self.picture, max_size_mb=10)

    # ── Privacy helpers ─────────────────────────────────────────
    def can_view_details(self, viewer):
        """
        Returns True if `viewer` (a User or AnonymousUser) is allowed
        to see this profile's personal details (bio, phone, location etc.)
        based on the owner's privacy_level setting.

        Rules:
          public        → everyone can see
          followers_only→ only users who follow this profile can see
          private       → only the owner themselves can see
        """
        owner = self.user

        # The owner always sees everything
        if hasattr(viewer, 'is_authenticated') and viewer.is_authenticated:
            if viewer == owner:
                return True

        if self.privacy_level == self.PRIVACY_PUBLIC:
            return True

        if self.privacy_level == self.PRIVACY_FOLLOWERS:
            if not hasattr(viewer, 'is_authenticated') or not viewer.is_authenticated:
                return False
            # viewer must follow the owner
            try:
                viewer_profile = viewer.profile
                return viewer_profile.followings.filter(pk=self.pk).exists()
            except Exception:
                return False

        # PRIVACY_PRIVATE — only owner (already handled above)
        return False

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.location:
            self.location = self.location.strip().title()
        
        if self.user:
            if self.user.first_name:
                self.user.first_name = sanitize_text(self.user.first_name).capitalize()
            if self.user.last_name:
                self.user.last_name = sanitize_text(self.user.last_name).capitalize()
            
            self.full_name = f'{self.user.first_name} {self.user.last_name}'.strip()
            self.user.save()
        
        super().save(*args, **kwargs)

    # ── Online status ────────────────────────────────────────────
    @property
    def is_online(self):
        return self.online

    def get_status_display(self):
        return "Online" if self.online else "Offline"

    def update_online_status(self, online=True):
        self.online = online
        self.save(update_fields=['online'])

    @classmethod
    def mark_user_online(cls, user_id):
        cls.objects.filter(user_id=user_id).update(online=True)

    @classmethod
    def mark_user_offline(cls, user_id):
        cls.objects.filter(user_id=user_id).update(online=False)

    # ── Block helpers ────────────────────────────────────────────
    def block(self, profile):
        """Block another profile. Also removes any existing follow relationship."""
        self.blocked_users.add(profile)
        self.followings.remove(profile)
        profile.followings.remove(self)

    def unblock(self, profile):
        self.blocked_users.remove(profile)

    def has_blocked(self, profile):
        return self.blocked_users.filter(pk=profile.pk).exists()

    def is_blocked_by(self, profile):
        return profile.blocked_users.filter(pk=self.pk).exists()

    # ── Picture URL helper ───────────────────────────────────────
    @property
    def get_picture_url(self):
        """
        Always returns a full usable picture URL in both environments.

        Production (USE_CLOUDINARY=True):
          Builds https://res.cloudinary.com/... from the stored public_id.
          Falls back to the default avatar if picture is blank.

        Debug (USE_CLOUDINARY=False):
          Returns the /media/... path via Django storage.
          Falls back to /static/images/male.png if file is missing.
        """
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                pic = self.picture
                # CloudinaryField exposes .public_id; plain string fallback
                public_id = None
                if hasattr(pic, 'public_id') and pic.public_id:
                    public_id = str(pic.public_id).strip()
                elif pic and str(pic).strip() not in ('', 'None'):
                    public_id = str(pic).strip()

                if public_id:
                    return cloudinary.CloudinaryImage(public_id).build_url(secure=True)

                # No picture stored — return the default avatar
                return cloudinary.CloudinaryImage('logo_iowyea').build_url(secure=True)

            else:
                # Debug: standard ImageField
                pic = self.picture
                if pic:
                    try:
                        url = pic.url
                        if url:
                            return url
                    except Exception:
                        pass
                # Fallback to a static default image
                from django.templatetags.static import static
                return static('images/male.png')

        except Exception:
            pass

        return 'https://placehold.co/40x40/dbdbdb/8e8e8e?text=U'

    # ── Website helpers ──────────────────────────────────────────
    @property
    def safe_website(self):
        if not self.website:
            return ""
        try:
            return validate_url(self.website)
        except ValidationError:
            return ""
    
    @property
    def display_website(self):
        if not self.website:
            return ""
        website = self.safe_website
        if not website:
            return ""
        display_url = website.replace('https://', '').replace('http://', '')
        if display_url.startswith('www.'):
            display_url = display_url[4:]
        if len(display_url) > 30:
            return display_url[:27] + '...'
        return display_url


class UserReport(models.Model):
    REASON_CHOICES = [
        ('spam',          'Spam or fake account'),
        ('harassment',    'Harassment or bullying'),
        ('hate_speech',   'Hate speech or discrimination'),
        ('inappropriate', 'Inappropriate content'),
        ('impersonation', 'Impersonation'),
        ('other',         'Something else'),
    ]

    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('reviewed',  'Reviewed'),
        ('resolved',  'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    reporter    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_made')
    reported    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_received')
    reason      = models.CharField(max_length=20, choices=REASON_CHOICES)
    note        = models.TextField(blank=True, default='')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'UserReport_Table'
        unique_together = ('reporter', 'reported', 'reason')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reporter.username} reported {self.reported.username} for {self.reason}"  

class BlockedUser(models.Model):
    blocker  = models.ForeignKey(User, related_name='blocking',  on_delete=models.CASCADE, db_index=True)
    blocked  = models.ForeignKey(User, related_name='blocked_by', on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')
        indexes = [
            # Speeds up the bidirectional blocked-user lookup in _get_feed_page:
            # BlockedUser.objects.filter(Q(blocker=user) | Q(blocked=user))
            models.Index(fields=['blocker'], name='blockeduser_blocker_idx'),
            models.Index(fields=['blocked'], name='blockeduser_blocked_idx'),
        ]


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
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, 
                                null=True, blank=True, related_name='replies')
    file_type = models.CharField(max_length=20, blank=True, null=True) 
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
    like = models.ManyToManyField(User, related_name='liked_messages', blank=True)
    link_preview = models.JSONField(null=True, blank=True)
    # ── Product enquiry context ───────────────────────────────────────────────
    # Set when a buyer messages a seller directly from a marketplace listing.
    # Stores a snapshot of the product so the card stays visible even if the
    # listing is later deleted.
    linked_product = models.ForeignKey(
        'Market',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enquiry_messages',
    )
    linked_product_snapshot = models.JSONField(null=True, blank=True)
    # snapshot keys: name, price, condition, category, location, image_url, product_id

    def __str__(self):
        return f"{self.sender} to {self.receiver}: {self.conversation[:50]}"
    
    def clean(self):
        super().clean()
        self.conversation = sanitize_text(self.conversation, 'conversation')
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
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


class MessageReaction(models.Model):
    """Stores emoji reactions on direct messages."""
    REACTION_CHOICES = [
        ('❤️',  'Heart'),
        ('😂',  'Laugh'),
        ('😮',  'Wow'),
        ('😢',  'Sad'),
        ('😡',  'Angry'),
        ('👍',  'Thumbs Up'),
        ('🔥',  'Fire'),
        ('🎉',  'Party'),
    ]

    message  = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='message_reactions')
    emoji    = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to message {self.message_id}"


class Channel(models.Model):
    channel_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_channels')
    channel_name = models.CharField(max_length=200)
    about = models.TextField(blank=True, null=True)
    subscriber = models.ManyToManyField(User, blank=True, related_name='subscribed_channels')
    image = models.ImageField(upload_to='channel_image', default='male.png')
    created_at = models.DateTimeField(auto_now_add=True)
    admins = models.ManyToManyField(User, blank=True, related_name='admin_of_channel')
    blocked_users = models.ManyToManyField(User, blank=True, related_name='blocked_from_channels')
    is_broadcast_only = models.BooleanField(default=False)

    def is_user_admin(self, user):
        return user == self.channel_owner or self.admins.filter(id=user.id).exists()

    def __str__(self):
        return self.channel_name
    
    def clean(self):
        super().clean()
        self.channel_name = sanitize_text(self.channel_name, 'channel_name')
        self.about = sanitize_text(self.about, 'about')
        if self.image and hasattr(self.image, 'name') and self.image.name != 'male.png':
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def unread_count_for_user(self, user):
        if not user.is_authenticated:
            return 0
        from .models import ChannelMessage, ChannelUserLastSeen
        last_seen = ChannelUserLastSeen.objects.filter(channel=self, user=user).first()
        if last_seen:
            return ChannelMessage.objects.filter(
                channel=self,
                created_at__gt=last_seen.last_seen_at
            ).exclude(author=user).count()
        return ChannelMessage.objects.filter(channel=self).exclude(author=user).count()

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
    link_preview = models.JSONField(null=True, blank=True)

    def clean(self):
        super().clean()
        self.message = sanitize_text(self.message, 'content')
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
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


class ChannelMessageReaction(models.Model):
    """Stores emoji reactions on channel messages. One reaction per user per message (toggle/switch)."""
    REACTION_CHOICES = [
        ('❤️',  'Heart'),
        ('😂',  'Laugh'),
        ('😮',  'Wow'),
        ('😢',  'Sad'),
        ('😡',  'Angry'),
        ('👍',  'Thumbs Up'),
        ('🔥',  'Fire'),
        ('🎉',  'Party'),
    ]

    message    = models.ForeignKey(ChannelMessage, on_delete=models.CASCADE, related_name='reactions')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_message_reactions')
    emoji      = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to channel message {self.message_id}"


class Market(models.Model):

    # ── Jumia-style product categories ───────────────────────────────────────
    CATEGORY_CHOICES = [
        # Electronics & Tech
        ('phones',          'Phones & Tablets'),
        ('computers',       'Computers & Laptops'),
        ('electronics',     'Electronics & Gadgets'),
        ('accessories',     'Phone Accessories'),
        ('tv_audio',        'TVs & Audio'),
        ('cameras',         'Cameras & Photography'),
        ('gaming',          'Gaming'),
        # Fashion & Lifestyle
        ('fashion_men',     "Men's Fashion"),
        ('fashion_women',   "Women's Fashion"),
        ('fashion_kids',    "Kids' Fashion"),
        ('watches',         'Watches & Jewelry'),
        ('shoes',           'Shoes & Sneakers'),
        ('bags',            'Bags & Luggage'),
        # Home & Living
        ('home_appliances', 'Home Appliances'),
        ('furniture',       'Furniture & Décor'),
        ('kitchen',         'Kitchen & Dining'),
        ('garden',          'Garden & Outdoor'),
        # Health & Beauty
        ('beauty',          'Beauty & Skincare'),
        ('health',          'Health & Wellness'),
        # Food & Groceries
        ('food',            'Food & Groceries'),
        ('drinks',          'Drinks & Beverages'),
        # Vehicles & Property
        ('vehicles',        'Vehicles & Parts'),
        ('properties',      'Properties & Real Estate'),
        # Business & Services
        ('office',          'Office & Stationery'),
        ('agriculture',     'Agriculture & Farming'),
        ('services',        'Services & Gigs'),
        # Sports & Leisure
        ('sports',          'Sports & Fitness'),
        ('books',           'Books & Education'),
        ('toys',            'Toys & Baby Items'),
        # Other
        ('others',          'Others'),
    ]

    CATEGORY_ICONS = {
        'phones':          '📱',
        'computers':       '💻',
        'electronics':     '⚡',
        'accessories':     '🎧',
        'tv_audio':        '📺',
        'cameras':         '📷',
        'gaming':          '🎮',
        'fashion_men':     '👔',
        'fashion_women':   '👗',
        'fashion_kids':    '🧒',
        'watches':         '⌚',
        'shoes':           '👟',
        'bags':            '👜',
        'home_appliances': '🏠',
        'furniture':       '🛋️',
        'kitchen':         '🍳',
        'garden':          '🌿',
        'beauty':          '💄',
        'health':          '💊',
        'food':            '🛒',
        'drinks':          '🥤',
        'vehicles':        '🚗',
        'properties':      '🏡',
        'office':          '🖊️',
        'agriculture':     '🌾',
        'services':        '🛠️',
        'sports':          '⚽',
        'books':           '📚',
        'toys':            '🧸',
        'others':          '📦',
    }

    VALID_CATEGORIES = {c[0] for c in CATEGORY_CHOICES}

    product_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product_owner = models.ForeignKey(User, related_name='products', on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    product_price = models.IntegerField()
    product_location = models.CharField(max_length=300)
    product_description = models.TextField(blank=True, null=True)
    product_availability = models.CharField(max_length=150)
    product_condition = models.CharField(max_length=50, choices=[('New', 'New'), ('Used', 'Used - Like New'), ('Fair', 'Used - Fair Condition')], default='New')
    views_count = models.PositiveIntegerField(default=0)
    is_promoted = models.BooleanField(default=False)
    product_category = models.CharField(
        max_length=100,
        choices=CATEGORY_CHOICES,
        default='others',
        db_index=True,
    )
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)
    ad_url          = models.URLField(max_length=500, blank=True, null=True)
    email           = models.EmailField(max_length=254, blank=True, null=True)
    instagram_handle= models.CharField(max_length=50, blank=True, null=True)
    twitter_handle  = models.CharField(max_length=50, blank=True, null=True)
    # FK to BusinessPage — set when a market listing is posted via a business page
    business_page   = models.ForeignKey(
        'BusinessPage', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='market_listings',
    )
    posted_on = models.DateTimeField(auto_now_add=True)
    
    def clean(self):
        super().clean()
        self.product_name = sanitize_text(self.product_name, 'product_name')
        self.product_location = sanitize_text(self.product_location)
        self.product_description = sanitize_text(self.product_description, 'product_description')
        self.product_availability = sanitize_text(self.product_availability)
        self.product_category = sanitize_text(self.product_category)
        if self.product_price < 0:
            raise ValidationError({'product_price': 'Price cannot be negative'})
        if self.product_price > 1000000000:
            raise ValidationError({'product_price': 'Price is too high'})
        if self.views_count < 0:
            self.views_count = 0
        if self.whatsapp_number:
            try:
                self.whatsapp_number = validate_phone_number(self.whatsapp_number)
            except ValidationError as e:
                raise ValidationError({'whatsapp_number': str(e)})
        # FIX 8: Enforce safe URL schemes — block javascript:, data:, vbscript: etc.
        if self.ad_url:
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(self.ad_url)
            if _parsed.scheme not in ('http', 'https'):
                raise ValidationError({'ad_url': 'Only http:// and https:// URLs are allowed.'})
        # FIX 7: Sanitize email (remove XSS chars) — keep as plain text value
        if self.email:
            import re as _re
            self.email = _re.sub(r'[<>\'";\x60]', '', self.email).strip()[:254]
        # FIX 9: Strip XSS chars and @ from handles, not just @
        if self.instagram_handle:
            import re as _re2
            self.instagram_handle = _re2.sub(r'[^a-zA-Z0-9._]', '', self.instagram_handle.lstrip('@').strip())[:50]
        if self.twitter_handle:
            import re as _re3
            self.twitter_handle = _re3.sub(r'[^a-zA-Z0-9._]', '', self.twitter_handle.lstrip('@').strip())[:50]
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def category_icon(self):
        return self.CATEGORY_ICONS.get(self.product_category, '📦')

    @property
    def category_label(self):
        return dict(self.CATEGORY_CHOICES).get(self.product_category, self.product_category)


class MarketImage(models.Model):
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    product = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='images')
    product_image = models.ImageField(upload_to='product_images/')
    
    def clean(self):
        super().clean()
        if self.product_image:
            validate_file_extension(self.product_image)
            validate_file_size(self.product_image, max_size_mb=10)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Wishlist(models.Model):
    """
    Saved-for-later products. One row per (user, product) pair —
    a simple "heart/bookmark" join table on top of the existing Market model.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product    = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Wishlist_Table'
        ordering = ['-created_at']
        unique_together = ('user', 'product')
        indexes = [
            models.Index(fields=['user', 'created_at'], name='wishlist_user_time_idx'),
        ]

    def __str__(self):
        return f'{self.user.username} saved {self.product.product_name}'


class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Search Histories'
    
    def __str__(self):
        return f"{self.user.username} - {self.query}"
    
    def clean(self):
        super().clean()
        self.query = sanitize_text(self.query)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        user_history = SearchHistory.objects.filter(user=self.user)
        if user_history.count() > 50:
            oldest = user_history.order_by('created_at').first()
            oldest.delete()


class LoginAttempt(models.Model):
    """
    Layer 2 brute-force protection (Layer 1 = django-axes in settings.py).
    Tracks failed login attempts per username in the DB.
    Works on every deployment — no cache/Redis dependency.
    Auto-cleans entries older than 24 hours on every write.
    """
    username     = models.CharField(max_length=254, db_index=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    succeeded    = models.BooleanField(default=False)

    class Meta:
        db_table = 'LoginAttempt_Table'
        ordering = ['-attempted_at']
        indexes  = [
            models.Index(fields=['username', 'attempted_at'], name='login_attempt_user_time_idx'),
        ]

    def __str__(self):
        status = 'success' if self.succeeded else 'failed'
        return f'{self.username} — {status} at {self.attempted_at}'

    @classmethod
    def is_blocked(cls, username):
        """
        Returns (blocked: bool, seconds_left: int).
        Blocks after 10 failed attempts within 15 minutes.
        This runs alongside axes — catches attackers who rotate IPs/VPNs.
        """
        from django.utils import timezone as tz
        from datetime import timedelta
        LIMIT        = 10
        WINDOW_MINS  = 15
        window_start = tz.now() - timedelta(minutes=WINDOW_MINS)

        recent = cls.objects.filter(
            username=username.lower(),
            attempted_at__gte=window_start,
            succeeded=False,
        ).count()

        if recent >= LIMIT:
            oldest = cls.objects.filter(
                username=username.lower(),
                attempted_at__gte=window_start,
                succeeded=False,
            ).order_by('attempted_at').first()
            if oldest:
                unlock_at    = oldest.attempted_at + timedelta(minutes=WINDOW_MINS)
                seconds_left = max(0, int((unlock_at - tz.now()).total_seconds()))
            else:
                seconds_left = 0
            return True, seconds_left
        return False, 0

    @classmethod
    def record(cls, username, succeeded):
        """Record an attempt and clean up entries older than 24 hours."""
        from django.utils import timezone as tz
        from datetime import timedelta
        cls.objects.create(username=username.lower(), succeeded=succeeded)
        # Keep table small — delete old entries
        cls.objects.filter(
            attempted_at__lt=tz.now() - timedelta(hours=24)
        ).delete()

    @classmethod
    def clear(cls, username):
        """Clear all failed attempts for a username on successful login."""
        cls.objects.filter(username=username.lower(), succeeded=False).delete()

# =============================================================================
# SecretQuestion — stores user's chosen security question & hashed answer
# for the "Forgot Password" flow.
# =============================================================================

_SECRET_QUESTIONS = [
    ('pet',      "What was the name of your first pet?"),
    ('school',   "What primary school did you attend?"),
    ('city',     "In what city were you born?"),
    ('mother',   "What is your mother's maiden name?"),
    ('friend',   "What is the name of your childhood best friend?"),
    ('car',      "What was the make of your first car?"),
    ('street',   "What street did you grow up on?"),
    ('nickname', "What nickname did your family call you as a child?"),
]

class SecretQuestion(models.Model):
    """
    One row per user.  Stores the security question chosen at registration
    and the bcrypt-style hash of the answer (via Django's make_password).
    Used only for the no-email "Forgot Password" reset flow.
    """
    QUESTION_CHOICES = _SECRET_QUESTIONS

    user     = models.OneToOneField(User, on_delete=models.CASCADE, related_name='secret_question')
    question = models.CharField(max_length=20, choices=QUESTION_CHOICES)
    answer_hash = models.CharField(max_length=255)   # Django make_password hash
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'SecretQuestion_Table'

    def __str__(self):
        return f'SecretQuestion({self.user.username})'

    def set_answer(self, raw_answer: str):
        from django.contrib.auth.hashers import make_password
        # Normalise: strip, lowercase so casing doesn't matter
        self.answer_hash = make_password(raw_answer.strip().lower())

    def check_answer(self, raw_answer: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return check_password(raw_answer.strip().lower(), self.answer_hash)

    @classmethod
    def question_label(cls, key: str) -> str:
        return dict(cls.QUESTION_CHOICES).get(key, key)



class SocialEvent(models.Model):
    TYPE_TOWN     = 'town'
    TYPE_FESTIVAL = 'festival'
    TYPE_WEDDING  = 'wedding'
    TYPE_OTHER    = 'other'

    TYPE_CHOICES = [
        (TYPE_TOWN,     'Town Meeting'),
        (TYPE_FESTIVAL, 'Festival'),
        (TYPE_WEDDING,  'Wedding'),
        (TYPE_OTHER,    'Other'),
    ]

    title       = models.CharField(max_length=200)
    event_type  = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER, db_index=True)
    date        = models.DateField(db_index=True)
    time        = models.TimeField(null=True, blank=True)
    location    = models.CharField(max_length=300, blank=True, default='')
    description = models.TextField(blank=True, default='')

    if settings.USE_CLOUDINARY:
        cover_image = CloudinaryField('image', folder='event_covers', blank=True, null=True)
    else:
        cover_image = models.ImageField(upload_to='event_covers/', blank=True, null=True)

    created_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='social_events',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'SocialEvent_Table'
        ordering  = ['date', 'time']

    def __str__(self):
        return f'{self.title} ({self.get_event_type_display()}) — {self.date}'

    @property
    def type_emoji(self):
        return {
            self.TYPE_TOWN:     '🏛️',
            self.TYPE_FESTIVAL: '🎪',
            self.TYPE_WEDDING:  '💍',
            self.TYPE_OTHER:    '✨',
        }.get(self.event_type, '📌')

    @property
    def type_color(self):
        return {
            self.TYPE_TOWN:     '#0095f6',
            self.TYPE_FESTIVAL: '#ff6b35',
            self.TYPE_WEDDING:  '#e91e8c',
            self.TYPE_OTHER:    '#7c3aed',
        }.get(self.event_type, '#0095f6')

    @property
    def time_display(self):
        if not self.time:
            return 'All Day'
        h, m = self.time.hour, self.time.minute
        ap = 'AM' if h < 12 else 'PM'
        h12 = h % 12 or 12
        return f'{h12}:{m:02d} {ap}'


# ─── Job Vacancy ─────────────────────────────────────────────────────────────

class JobVacancy(models.Model):
    CAT_GIG          = 'gig'
    CAT_FULLTIME     = 'fulltime'
    CAT_APPRENTICE   = 'apprenticeship'

    CATEGORY_CHOICES = [
        (CAT_GIG,        'Gig'),
        (CAT_FULLTIME,   'Full-time'),
        (CAT_APPRENTICE, 'Apprenticeship'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    posted_by    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_vacancies')
    category     = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CAT_FULLTIME, db_index=True)
    title        = models.CharField(max_length=200)
    company      = models.CharField(max_length=150, blank=True, default='')
    location     = models.CharField(max_length=300, blank=True, default='')
    description  = models.TextField()
    requirements = models.TextField(blank=True, default='')
    contact_info = models.CharField(max_length=300, blank=True, default='',
                                    help_text='Email, phone, or link to apply')
    salary_range = models.CharField(max_length=100, blank=True, default='',
                                    help_text='e.g. ₦80,000–₦120,000/month or "Negotiable"')
    if settings.USE_CLOUDINARY:
        cover_image = CloudinaryField('image', folder='job_covers', blank=True, null=True)
    else:
        cover_image = models.ImageField(upload_to='job_covers/', blank=True, null=True)
    is_open      = models.BooleanField(default=True, db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'JobVacancy_Table'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} [{self.get_category_display()}] — {self.posted_by.username}'

    @property
    def category_emoji(self):
        return {
            self.CAT_GIG:        '🛠️',
            self.CAT_FULLTIME:   '💼',
            self.CAT_APPRENTICE: '🎓',
        }.get(self.category, '📌')

    @property
    def category_color(self):
        return {
            self.CAT_GIG:        '#ff6b35',
            self.CAT_FULLTIME:   '#0095f6',
            self.CAT_APPRENTICE: '#7c3aed',
        }.get(self.category, '#0095f6')


# =============================================================================
# JobVibe / JobComment — reactions on JobVacancy feed cards
# =============================================================================

class JobVibe(models.Model):
    """Vibe reactions on JobVacancy cards in the feed. One per user per job."""

    FIRE   = 'fire'
    REAL   = 'real'
    VIBING = 'vibing'
    DEAD   = 'dead'
    CRINGE = 'cringe'
    CHILL  = 'chill'
    LOVE   = 'love'

    VIBE_CHOICES = [
        (FIRE,   '🔥 Fire'),
        (REAL,   '💯 Real'),
        (VIBING, '🎵 Vibing'),
        (DEAD,   '😂 Dead'),
        (CRINGE, '😬 Cringe'),
        (CHILL,  '🧊 Chill'),
        (LOVE,   '❤️ Love'),
    ]

    VIBE_EMOJIS = {FIRE:'🔥', REAL:'💯', VIBING:'🎵', DEAD:'😂', CRINGE:'😬', CHILL:'🧊', LOVE:'❤️'}
    VIBE_COLORS = {FIRE:'#ff4500', REAL:'#ff0080', VIBING:'#3b82f6', DEAD:'#f59e0b', CRINGE:'#8b5cf6', CHILL:'#06b6d4', LOVE:'#e11d48'}

    job        = models.ForeignKey(JobVacancy, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User,       on_delete=models.CASCADE, related_name='job_vibes')
    vibe_type  = models.CharField(max_length=10, choices=VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('job', 'user')
        ordering = ['created_at']
        db_table = 'JobVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on job {self.job_id}"


class JobComment(models.Model):
    """Comments on Job Vacancy feed cards."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job        = models.ForeignKey(JobVacancy, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User,       on_delete=models.CASCADE, related_name='job_comments')
    text       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        self.text = sanitize_text(self.text, 'comment')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        db_table = 'JobComment_Table'

    def __str__(self):
        return f"{self.author.username} on {self.job.title}: {self.text[:50]}"


# =============================================================================
# EventVibe / EventComment — reactions on SocialEvent feed cards
# =============================================================================

class EventVibe(models.Model):
    """Vibe reactions on SocialEvent cards in the feed. One per user per event."""

    FIRE   = 'fire'
    REAL   = 'real'
    VIBING = 'vibing'
    DEAD   = 'dead'
    CRINGE = 'cringe'
    CHILL  = 'chill'
    LOVE   = 'love'

    VIBE_CHOICES = [
        (FIRE,   '🔥 Fire'),
        (REAL,   '💯 Real'),
        (VIBING, '🎵 Vibing'),
        (DEAD,   '😂 Dead'),
        (CRINGE, '😬 Cringe'),
        (CHILL,  '🧊 Chill'),
        (LOVE,   '❤️ Love'),
    ]

    VIBE_EMOJIS = {FIRE:'🔥', REAL:'💯', VIBING:'🎵', DEAD:'😂', CRINGE:'😬', CHILL:'🧊', LOVE:'❤️'}
    VIBE_COLORS = {FIRE:'#ff4500', REAL:'#ff0080', VIBING:'#3b82f6', DEAD:'#f59e0b', CRINGE:'#8b5cf6', CHILL:'#06b6d4', LOVE:'#e11d48'}

    event      = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User,        on_delete=models.CASCADE, related_name='event_vibes')
    vibe_type  = models.CharField(max_length=10, choices=VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('event', 'user')
        ordering = ['created_at']
        db_table = 'EventVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on event {self.event_id}"


class EventComment(models.Model):
    """Comments on Social Event feed cards."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event      = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User,        on_delete=models.CASCADE, related_name='event_comments')
    text       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        self.text = sanitize_text(self.text, 'comment')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        db_table = 'EventComment_Table'

    def __str__(self):
        return f"{self.author.username} on {self.event.title}: {self.text[:50]}"

# =============================================================================
# BusinessPage — business pages with follow system
# Listings/products for a page use the existing Market model with
# the business_page FK.  No separate product model is needed.
# Run: python manage.py makemigrations && python manage.py migrate
# =============================================================================

class BusinessPage(models.Model):

    CATEGORY_CHOICES = [
        ('retail',       'Retail & Shopping'),
        ('food',         'Food & Beverage'),
        ('fashion',      'Fashion & Apparel'),
        ('electronics',  'Electronics & Tech'),
        ('beauty',       'Beauty & Wellness'),
        ('education',    'Education & Training'),
        ('services',     'Professional Services'),
        ('agriculture',  'Agriculture & Farming'),
        ('real_estate',  'Real Estate & Property'),
        ('logistics',    'Logistics & Delivery'),
        ('auto',         'Automobiles & Vehicles'),
        ('others',       'Others'),
    ]

    page_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_pages')
    name        = models.CharField(max_length=150)
    slug        = models.SlugField(max_length=160, unique=True)
    category    = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='others')
    tagline     = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    location    = models.CharField(max_length=200, blank=True, default='')
    website     = models.URLField(max_length=500, blank=True, default='')
    whatsapp    = models.CharField(max_length=20,  blank=True, default='')
    phone       = models.CharField(max_length=20,  blank=True, default='')
    email       = models.EmailField(max_length=254, blank=True, default='')
    # ── Social media ──────────────────────────────────────────────────────────
    instagram   = models.CharField(max_length=100, blank=True, default='',
                                   help_text='Username or @handle')
    youtube     = models.URLField(max_length=300,  blank=True, default='',
                                   help_text='Full channel URL')
    facebook    = models.URLField(max_length=300,  blank=True, default='',
                                   help_text='Full page URL')
    twitter     = models.CharField(max_length=100, blank=True, default='',
                                   help_text='Username or @handle')
    tiktok      = models.CharField(max_length=100, blank=True, default='',
                                   help_text='Username or @handle')
    followers   = models.ManyToManyField(User, blank=True, related_name='followed_business_pages')
    is_verified = models.BooleanField(default=False)
    is_active   = models.BooleanField(default=True)

    if settings.USE_CLOUDINARY:
        logo        = CloudinaryField('logo',        folder='business_logos',  blank=True, null=True)
        cover_photo = CloudinaryField('cover_photo', folder='business_covers', blank=True, null=True)
    else:
        logo        = models.ImageField(upload_to='business_logos/',  blank=True, null=True)
        cover_photo = models.ImageField(upload_to='business_covers/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'BusinessPage_Table'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} (@{self.slug})'

    def clean(self):
        super().clean()
        self.name        = sanitize_text(self.name)
        self.tagline     = sanitize_text(self.tagline)
        self.description = sanitize_text(self.description, 'about')
        self.location    = sanitize_text(self.location, 'location')
        if self.website:
            try:
                self.website = validate_url(self.website)
            except ValidationError:
                self.website = ''
        if self.youtube:
            try:
                self.youtube = validate_url(self.youtube)
            except ValidationError:
                self.youtube = ''
        if self.facebook:
            try:
                self.facebook = validate_url(self.facebook)
            except ValidationError:
                self.facebook = ''
        if self.whatsapp:
            try:
                self.whatsapp = validate_phone_number(self.whatsapp)
            except ValidationError:
                self.whatsapp = ''
        if self.phone:
            try:
                self.phone = validate_phone_number(self.phone)
            except ValidationError:
                self.phone = ''
        # Strip leading @ and non-safe chars from handle-style fields
        if self.instagram:
            self.instagram = re.sub(r'[^a-zA-Z0-9._]', '', self.instagram.lstrip('@').strip())[:100]
        if self.twitter:
            self.twitter = re.sub(r'[^a-zA-Z0-9._]', '', self.twitter.lstrip('@').strip())[:100]
        if self.tiktok:
            self.tiktok = re.sub(r'[^a-zA-Z0-9._]', '', self.tiktok.lstrip('@').strip())[:100]

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name)[:140] or 'page'
            slug, n = base, 1
            while BusinessPage.objects.filter(slug=slug).exclude(page_id=self.page_id).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def follower_count(self):
        return self.followers.count()

    @property
    def listing_count(self):
        return self.market_listings.count()

    @property
    def get_logo_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.logo:
                    pid = str(getattr(self.logo, 'public_id', None) or self.logo).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return 'https://placehold.co/120x120/f97316/ffffff?text=B'
            else:
                return self.logo.url if self.logo else ''
        except Exception:
            return 'https://placehold.co/120x120/f97316/ffffff?text=B'

    @property
    def get_cover_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.cover_photo:
                    pid = str(getattr(self.cover_photo, 'public_id', None) or self.cover_photo).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return ''
            else:
                return self.cover_photo.url if self.cover_photo else ''
        except Exception:
            return ''
