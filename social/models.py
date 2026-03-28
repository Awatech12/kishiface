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
    
    created_at = models.DateTimeField(auto_now_add=True)
    online = models.BooleanField(default=False)

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username

    def clean(self):
        super().clean()
        self.bio = sanitize_text(self.bio, 'bio')
        self.location = sanitize_text(self.location, 'location')
        self.full_name = sanitize_text(self.full_name)
        self.address = sanitize_text(self.address)
        
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

class Post(models.Model):
    post_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    likes = models.ManyToManyField(User, related_name='like_post', blank=True)
    reposts = models.ManyToManyField(User, related_name='repost_post', blank=True)  
    view = models.IntegerField(default=0, null=True, blank=True)
    share = models.IntegerField(default=0, null=True, blank=True)
    content = models.TextField(blank=True, null=True)
    
    mood = models.CharField(max_length=50, blank=True, null=True)
    custom_mood = models.CharField(max_length=50, blank=True, null=True)
    mood_emoji = models.CharField(max_length=10, blank=True, null=True)
    
    is_repost = models.BooleanField(default=False)
    original_post = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='reposts_made')
    repost_content = models.TextField(blank=True, null=True)  
    
    if settings.USE_CLOUDINARY:
        video_file = CloudinaryField('video', resource_type='video', folder='post_files', blank=True)
    else:
        video_file = models.FileField(upload_to='post_file', blank=True)
    
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video', folder='post_files', blank=True)
    else:
        file = models.FileField(upload_to='post_file', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    link_preview = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.author.username
    
    def clean(self):
        """Validate post data"""
        super().clean()
        
        self.content = sanitize_text(self.content, 'content')
        if self.repost_content:
            self.repost_content = sanitize_text(self.repost_content, 'content')
        
        if self.video_file and hasattr(self.video_file, 'name'):
            validate_file_extension(self.video_file)
            validate_file_size(self.video_file, max_size_mb=100)
        
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=50)
        
        if self.view and self.view < 0:
            self.view = 0
        if self.share and self.share < 0:
            self.share = 0
        
        valid_moods = ['slay', 'vibing', 'sheesh', 'periodt', 'no-cap', 'bussin', 'mid', 'cringe']
        if self.mood and self.mood not in valid_moods:
            self.mood = None
        
        if self.custom_mood and len(self.custom_mood) > 50:
            self.custom_mood = self.custom_mood[:50]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def preview_type(self):
        if self.is_repost and self.original_post:
            return self.original_post.preview_type()
        if self.images.exists():
            return 'image'
        if self.video_file:
            return 'video'
        if self.file:
            return 'audio'
        if self.content:
            return 'text'
        if self.mood or self.custom_mood:
            return 'mood'
        return 'empty'
    
    def preview_url(self):
        if self.is_repost and self.original_post:
            return self.original_post.preview_url()
        if self.images.exists():
            return self.images.first().image.url
        if self.video_file:
            return self.video_file.url
        if self.file:
            return self.file.url
        return None
    
    def get_original_author(self):
        if self.is_repost and self.original_post:
            return self.original_post.author
        return self.author
    
    def get_original_post_id(self):
        if self.is_repost and self.original_post:
            return self.original_post.post_id
        return self.post_id
    
    def get_republished_content(self):
        if self.is_repost and self.original_post:
            return self.original_post.content
        return self.content
    
    def get_mood_display(self):
        mood_emojis = {
            'slay': '💅', 'vibing': '🎵', 'sheesh': '🥶', 'periodt': '⏸️',
            'no-cap': '🎯', 'bussin': '🔥', 'mid': '😐', 'cringe': '😬'
        }
        if self.custom_mood:
            import re
            emoji_pattern = re.compile("["
                u"\U0001F300-\U0001F6FF"
                u"\U0001F1E0-\U0001F1FF"
                u"\U00002700-\U000027BF"
                u"\U0001F900-\U0001F9FF"
                u"\U0001FA70-\U0001FAFF"
                u"\U00002600-\U000026FF"
                u"\U00002B50-\U00002B50"
                u"\U0001F004-\U0001F0CF"
                "]+", flags=re.UNICODE)
            if emoji_pattern.search(self.custom_mood):
                return self.custom_mood
            else:
                return f"{self.mood_emoji or '✨'} {self.custom_mood}"
        elif self.mood:
            emoji = mood_emojis.get(self.mood, '✨')
            return f"{emoji} {self.mood}"
        return None
    
    def get_mood_color(self):
        mood_colors = {
            'slay': '#ff1493', 'vibing': '#9933ff', 'sheesh': '#00cc66',
            'periodt': '#ff6b00', 'no-cap': '#ff4444', 'bussin': '#ffd700',
            'mid': '#808080', 'cringe': '#8b4513'
        }
        if self.custom_mood:
            return '#0095f6'
        return mood_colors.get(self.mood, '#0095f6')
    
    def get_mood_hashtag(self):
        if self.custom_mood:
            import re
            clean_mood = re.sub(r'[^\w\s]', '', self.custom_mood)
            clean_mood = clean_mood.replace(' ', '')
            return f"#{clean_mood}"
        elif self.mood:
            return f"#{self.mood}"
        return None
    
    def get_mood_emoji_only(self):
        mood_emojis = {
            'slay': '💅', 'vibing': '🎵', 'sheesh': '🥶', 'periodt': '⏸️',
            'no-cap': '🎯', 'bussin': '🔥', 'mid': '😐', 'cringe': '😬'
        }
        if self.mood_emoji:
            return self.mood_emoji
        elif self.mood:
            return mood_emojis.get(self.mood, '✨')
        return '✨'
    
    def has_mood(self):
        return bool(self.mood or self.custom_mood)
    
    def get_mood_type(self):
        if self.custom_mood:
            return 'custom'
        elif self.mood:
            return 'predefined'
        return None
    
    def get_mood_data(self):
        return {
            'has_mood': self.has_mood(),
            'mood': self.mood,
            'custom_mood': self.custom_mood,
            'emoji': self.get_mood_emoji_only(),
            'display': self.get_mood_display(),
            'color': self.get_mood_color(),
            'hashtag': self.get_mood_hashtag(),
            'type': self.get_mood_type()
        }
    
    def get_engagement_rate(self):
        total_engagement = self.likes.count() + self.reposts.count() + (self.comments.count() if hasattr(self, 'comments') else 0)
        if self.view and self.view > 0:
            return (total_engagement / self.view) * 100
        return 0
    
    def get_vibe_score(self):
        """
        Calculate an engagement score based on all vibe types with different weights.
        Higher weight for more intense/positive reactions.
        """
        # Get all vibes for this post
        vibes = self.vibes.all()
        
        if not vibes.exists():
            return 0
        
        # Weight mapping for different vibe types
        vibe_weights = {
            'fire':   4,  # 🔥 Most intense positive
            'love':   4,  # ❤️ Strong positive (NEW)
            'real':   3,  # 💯 Strong approval
            'vibing': 2,  # 🎵 Moderate engagement
            'chill':  1,  # 🧊 Light positive
            'dead':   1,  # 😂 Laughter (can be positive)
            'cringe': 1,  # 😬 Negative reaction (still engagement)
        }
        
        # Calculate weighted score
        total_score = 0
        vibe_counts = {}
        
        for vibe in vibes:
            weight = vibe_weights.get(vibe.vibe_type, 1)
            total_score += weight
            vibe_counts[vibe.vibe_type] = vibe_counts.get(vibe.vibe_type, 0) + 1
        
        # Apply mood boost if post has mood
        if self.has_mood():
            total_score = int(total_score * 1.2)
        
        # Add bonus for variety (posts with multiple different vibe types get extra points)
        variety_bonus = len(vibe_counts) * 0.5
        total_score = round(total_score + variety_bonus, 1)
        
        return total_score
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['mood']),
            models.Index(fields=['custom_mood']),
            # ── Feed algorithm indexes ──────────────────────────────────────
            # Covers the engagement-score query:
            #   WHERE author_id IN (...) AND created_at >= cutoff
            #   ORDER BY db_score DESC, created_at DESC
            models.Index(fields=['author', 'created_at'], name='post_author_created_idx'),
            # Partial-style workaround: index is_repost + created_at so the
            # "repost fan-out" branch of the OR filter uses an index seek
            models.Index(fields=['is_repost', 'created_at'], name='post_repost_created_idx'),
        ]


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')
    
    def clean(self):
        super().clean()
        if self.image:
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# =============================================================================
# PostVibe — replaces simple Like with 7 mood-based reactions (added LOVE)
# Real-time updates via PostVibeConsumer (WebSocket)
# =============================================================================

class PostVibe(models.Model):
    """Stores vibe reactions on posts. One vibe per user per post (toggle/switch)."""

    FIRE    = 'fire'
    REAL    = 'real'
    VIBING  = 'vibing'
    DEAD    = 'dead'
    CRINGE  = 'cringe'
    CHILL   = 'chill'
    LOVE    = 'love'  # NEW: Love reaction

    VIBE_CHOICES = [
        (FIRE,   '🔥 Fire'),
        (REAL,   '💯 Real'),
        (VIBING, '🎵 Vibing'),
        (DEAD,   '😂 Dead'),
        (CRINGE, '😬 Cringe'),
        (CHILL,  '🧊 Chill'),
        (LOVE,   '❤️ Love'),  # NEW: Love option
    ]

    # Lookup maps used by the consumer and views
    VIBE_EMOJIS = {
        FIRE:   '🔥',
        REAL:   '💯',
        VIBING: '🎵',
        DEAD:   '😂',
        CRINGE: '😬',
        CHILL:  '🧊',
        LOVE:   '❤️',  # NEW
    }

    VIBE_LABELS = {
        FIRE:   'Fire',
        REAL:   'Real',
        VIBING: 'Vibing',
        DEAD:   'Dead',
        CRINGE: 'Cringe',
        CHILL:  'Chill',
        LOVE:   'Love',  # NEW
    }

    VIBE_COLORS = {
        FIRE:   '#ff4500',
        REAL:   '#ff0080',
        VIBING: '#3b82f6',
        DEAD:   '#f59e0b',
        CRINGE: '#8b5cf6',
        CHILL:  '#06b6d4',
        LOVE:   '#e11d48',  # NEW: Deep pink/red for love
    }

    post       = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_vibes')
    vibe_type  = models.CharField(max_length=10, choices=VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')   # one vibe per user per post
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'vibe_type']),
            # Interest-profile query: WHERE user_id=? AND created_at >= cutoff
            models.Index(fields=['user', 'created_at'], name='postvibe_user_created_idx'),
        ]

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on post {self.post_id}"


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
        super().clean()
        self.comment = sanitize_text(self.comment, 'comment')
        if self.image and hasattr(self.image, 'name'):
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=20)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            # Feed algorithm: WHERE author_id=? AND created_at >= cutoff
            models.Index(fields=['author', 'created_at'], name='postcomment_author_created_idx'),
        ]


class CommentReply(models.Model):
    reply_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey(PostComment, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    reply_text = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='reply_image/', blank=True)
    
    if settings.USE_CLOUDINARY:
        file = CloudinaryField('audio', resource_type='video', folder='reply_files', blank=True)
    else:
        file = models.FileField(upload_to='reply_file', blank=True)
    
    like = models.ManyToManyField(User, related_name='reply_likes', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)
    
    def clean(self):
        super().clean()
        self.reply_text = sanitize_text(self.reply_text, 'reply')
        if self.image and hasattr(self.image, 'name'):
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)
        if self.file and hasattr(self.file, 'name'):
            validate_file_extension(self.file)
            validate_file_size(self.file, max_size_mb=20)
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f'Reply by {self.author.username} on {self.created_at}'
    
    class Meta:
        ordering = ['-created_at']


# =============================================================================
# Notification — covers like / comment / repost / mention
# =============================================================================

class Notification(models.Model):
    LIKE    = 'like'
    COMMENT = 'comment'
    REPOST  = 'repost'
    MENTION = 'mention'
    REPLY   = 'reply'

    TYPES = (
        (LIKE,    'Like'),
        (COMMENT, 'Comment'),
        (REPOST,  'Repost'),
        (MENTION, 'Mention'),
        (REPLY,   'Reply'),
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
    # Populated only for 'mention' notifications — links directly to the comment
    comment = models.ForeignKey(
        'PostComment',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='mention_notifications'
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
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        return f'{self.actor} → {self.recipient} [{self.notification_type}]'


# =============================================================================
# FollowNotification — fires when someone follows you
# =============================================================================

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
    product_category = models.CharField(max_length=100)
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)
    ad_url          = models.URLField(max_length=500, blank=True, null=True)
    email           = models.EmailField(max_length=254, blank=True, null=True)
    instagram_handle= models.CharField(max_length=50, blank=True, null=True)
    twitter_handle  = models.CharField(max_length=50, blank=True, null=True)
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


# =============================================================================
# UserFeedProfile — adaptive vibe-taste profile for the Kvibe feed algorithm.
#
# After adding this class run:
#   python manage.py makemigrations
#   python manage.py migrate
# =============================================================================

class UserFeedProfile(models.Model):
    """
    One row per user.  Stores the evolving taste signals used by the feed
    ranking algorithm (_get_feed_page in views.py).

    vibe_weights
        JSON dict mapping each vibe type to a float weight (default 0.5).
        Incremented +0.1 each time the user reacts with that vibe (cap 3.0).
        Gives heavier ranking weight to posts whose vibe distribution matches
        what the user actually reacts to.  Example after a week of use:
            {"fire": 1.8, "love": 1.2, "real": 0.7, "chill": 0.5, ...}

    interacted_authors
        Ordered list (newest first) of up to 50 author user-ids this user
        has liked, vibed, or commented on.  Used for long-term author affinity
        scoring that survives beyond the 30-day rolling DB query window.

    last_updated
        Auto-timestamp of the last weight mutation — available for future
        periodic decay jobs if you want to slowly return unused weights to 0.5.

    last_feed_visit
        Datetime of the last home feed page-1 load for this user.
        Written by _get_feed_page() in views.py.  Used on the next visit
        to inject all posts from followed accounts since that timestamp,
        ensuring no post is invisible due to the _FEED_SAMPLE pool cap.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='feed_profile',
    )
    vibe_weights       = models.JSONField(default=dict,  blank=True)
    interacted_authors = models.JSONField(default=list,  blank=True)
    last_updated       = models.DateTimeField(auto_now=True)

    # ── Fix 1: last_feed_visit ────────────────────────────────────────────────
    # Stamped by _get_feed_page() on every first-page load (cursor_dt=None).
    # The feed algorithm reads this to inject unseen posts from followed
    # accounts posted since the user's last visit, preventing posts from
    # being permanently buried by the _FEED_SAMPLE cap when the user has
    # been away for a day or more.
    last_feed_visit = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp of the last time this user loaded the home feed. '
                  'Used by the feed algorithm to surface missed posts.',
    )

    class Meta:
        db_table = 'UserFeedProfile_Table'

    def __str__(self):
        return f'FeedProfile({self.user.username})'

    # ── Constants ────────────────────────────────────────────────────────────
    _DEFAULT_WEIGHT = 0.5
    _MAX_WEIGHT     = 3.0
    _BUMP           = 0.1
    _MAX_AUTHORS    = 50
    _VIBE_TYPES     = ['fire', 'real', 'vibing', 'dead', 'cringe', 'chill', 'love']

    # ── Read helpers ─────────────────────────────────────────────────────────

    def get_weights(self) -> dict:
        """Return full weight dict with defaults filled in for any missing type."""
        base = {v: self._DEFAULT_WEIGHT for v in self._VIBE_TYPES}
        base.update(self.vibe_weights or {})
        return base

    # ── Write helpers (called from views._feed_record_* and consumer) ────────

    def record_vibe(self, vibe_type: str, author_id: int):
        """
        Bump the weight for `vibe_type` by _BUMP (capped at _MAX_WEIGHT) and
        prepend `author_id` to interacted_authors (capped at _MAX_AUTHORS).
        Called every time the user toggles a vibe ON or switches vibe types.
        """
        weights = self.get_weights()
        weights[vibe_type] = min(
            self._MAX_WEIGHT,
            weights.get(vibe_type, self._DEFAULT_WEIGHT) + self._BUMP,
        )
        self.vibe_weights = weights
        self._prepend_author(author_id)
        self.save(update_fields=['vibe_weights', 'interacted_authors', 'last_updated'])

    def record_like(self, author_id: int):
        """
        Record that the user liked a post by `author_id`.
        Only updates author affinity — no vibe weight change.
        """
        self._prepend_author(author_id)
        self.save(update_fields=['interacted_authors', 'last_updated'])

    def record_comment(self, author_id: int):
        """
        Record that the user commented on a post by `author_id`.
        Only updates author affinity — no vibe weight change.
        """
        self._prepend_author(author_id)
        self.save(update_fields=['interacted_authors', 'last_updated'])

    def record_view(self, author_id: int):
        """
        Record that the user viewed (played or opened) a post by `author_id`.

        Views are a PASSIVE signal — lighter than likes/vibes/comments — so we
        only prepend the author when they are NOT already near the top of the
        interacted_authors list (within the first 10 positions).  This prevents
        a single creator whose videos auto-play from monopolising the affinity
        list and crowding out creators the user actually engages with actively.

        No vibe weight change — viewing has no bearing on content-type taste.
        No direct DB save for every view (high-volume endpoint).  Instead we
        only write when the author genuinely moves in the list, keeping the
        write amplification low even during heavy scrolling sessions.
        """
        authors = list(self.interacted_authors or [])
        # If already in the top-10 "recent" window, skip the write entirely.
        top_slice = authors[:10]
        if author_id in top_slice:
            return
        # Otherwise nudge them into the list (deduplicate + cap as usual).
        if author_id in authors:
            authors.remove(author_id)
        authors.insert(0, author_id)
        self.interacted_authors = authors[: self._MAX_AUTHORS]
        self.save(update_fields=['interacted_authors', 'last_updated'])

    # ── Internal ─────────────────────────────────────────────────────────────

    def _prepend_author(self, author_id: int):
        """Insert author_id at position 0, deduplicate, cap at _MAX_AUTHORS."""
        authors = list(self.interacted_authors or [])
        if author_id in authors:
            authors.remove(author_id)
        authors.insert(0, author_id)
        self.interacted_authors = authors[: self._MAX_AUTHORS]
