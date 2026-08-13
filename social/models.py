from django.db import models
from cloudinary.models import CloudinaryField
from django.contrib.auth.models import User
from django.conf import settings
from django.templatetags.static import static
from django.utils import timezone
from datetime import date, datetime, timedelta
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
    'post_caption': 2200,
    'poll_question': 300,
    'poll_option': 120,
}

# ─────────────────────────────────────────────────────────────────────────────
# Member Type / Onboarding — "What do you use Marketfy for?"
# One flexible schema instead of 10 separate models: each type has its own
# list of fields, stored together in Profile.member_type_data (JSONField).
# ─────────────────────────────────────────────────────────────────────────────

# Shared choices for the 'days_hours' field type (working days + opening/
# closing time selects), used wherever a schema needs "what days / what
# hours do you work" instead of a free-text box.
DAY_CHOICES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _generate_hour_choices():
    """12-hour clock choices in 30-minute steps, e.g. '9:00 AM', '9:30 PM'."""
    choices = []
    for total_minutes in range(0, 24 * 60, 30):
        h, m = divmod(total_minutes, 60)
        period = 'AM' if h < 12 else 'PM'
        display_h = h % 12 or 12
        choices.append(f'{display_h}:{m:02d} {period}')
    return choices


HOUR_CHOICES = _generate_hour_choices()

MEMBER_TYPE_SCHEMA = {
    'skilled_professional': {
        'label': 'Skilled Professional',
        'emoji': '👨\u200d🔧',
        'blurb': 'Trade or licensed skill — e.g. plumber, electrician, hairstylist',
        'fields': [
            {'key': 'profession',        'label': 'Profession',         'type': 'text',     'max_length': 150, 'required': True, 'placeholder': 'e.g. Plumber'},
            {'key': 'skills',            'label': 'Skills',             'type': 'select_other', 'max_length': 300,
             'choices': ['Plumbing', 'Electrical wiring', 'Carpentry', 'Welding', 'Painting', 'Tiling',
                         'AC repair', 'Generator repair', 'Hairdressing', 'Barbing', 'Makeup artistry']},
            {'key': 'years_experience',  'label': 'Years of Experience','type': 'number'},
            {'key': 'services_offered',  'label': 'Services Offered',   'type': 'textarea',  'max_length': 1000},
            {'key': 'location',          'label': 'Location',           'type': 'text',      'max_length': 200},
            {'key': 'work_radius',       'label': 'Work Radius',        'type': 'select',    'choices': ['Within 5km', 'Within 10km', 'Within 20km', 'Citywide', 'Statewide', 'Nationwide']},
            {'key': 'availability',      'label': 'Availability',       'type': 'select',    'choices': ['Full-time', 'Part-time', 'Weekends only', 'By appointment']},
            {'key': 'portfolio',         'label': 'Portfolio Link',     'type': 'url'},
            {'key': 'certifications',    'label': 'Certifications',     'type': 'text',      'max_length': 300},
            {'key': 'pricing',           'label': 'Pricing',            'type': 'text',      'max_length': 200, 'placeholder': 'e.g. ₦5,000/hr or Negotiable'},
            {'key': 'contact',           'label': 'Contact',            'type': 'text',      'max_length': 150},
        ],
    },
    'job_seeker': {
        'label': 'Job Seeker',
        'emoji': '👔',
        'blurb': 'Looking for employment',
        'fields': [
            {'key': 'desired_job',        'label': 'Desired Job',        'type': 'text',     'max_length': 150, 'required': True},
            {'key': 'skills',             'label': 'Skills',             'type': 'select_other', 'max_length': 300,
             'choices': ['Customer service', 'Sales', 'Accounting', 'Data entry', 'Graphic design', 'Writing',
                         'Marketing', 'IT support', 'Teaching', 'Driving']},
            {'key': 'education',          'label': 'Education',          'type': 'text',     'max_length': 200},
            {'key': 'experience',         'label': 'Experience',         'type': 'textarea', 'max_length': 1000},
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
            {'key': 'preferred_location', 'label': 'Preferred Location', 'type': 'text',     'max_length': 200},
            {'key': 'expected_salary',    'label': 'Expected Salary',    'type': 'text',     'max_length': 100},
            {'key': 'work_mode',          'label': 'Work Mode',          'type': 'select',   'choices': ['Remote', 'On-site', 'Hybrid']},
            {'key': 'availability',       'label': 'Availability',       'type': 'select',   'choices': ['Immediately', 'Within 2 weeks', 'Within a month', 'Flexible']},
        ],
    },
    'business_owner': {
        'label': 'Business Owner',
        'emoji': '🏢',
        'blurb': 'Runs a registered or informal business',
        'fields': [
            {'key': 'business_name',        'label': 'Business Name',        'type': 'text',     'max_length': 150, 'required': True},
            {'key': 'business_category',    'label': 'Business Category',    'type': 'text',     'max_length': 150},
            {'key': 'products_services',    'label': 'Products / Services',  'type': 'textarea', 'max_length': 1000},
            {'key': 'business_location',    'label': 'Business Location',    'type': 'text',     'max_length': 200},
            {'key': 'opening_hours',        'label': 'Opening Hours',        'type': 'days_hours'},
            {'key': 'website',              'label': 'Website',              'type': 'url'},
            {'key': 'business_description', 'label': 'Business Description', 'type': 'textarea', 'max_length': 1000},
        ],
    },
    'teacher_tutor': {
        'label': 'Teacher / Tutor',
        'emoji': '👨\u200d🏫',
        'blurb': 'Teaches or tutors, in-person or online',
        'fields': [
            {'key': 'subjects',        'label': 'Subjects',         'type': 'text',   'max_length': 300, 'required': True, 'placeholder': 'e.g. Mathematics, English, Physics'},
            {'key': 'teaching_level',  'label': 'Teaching Level',   'type': 'select', 'choices': ['Nursery/Primary', 'Secondary', 'Tertiary', 'Adult / Professional']},
            {'key': 'qualifications',  'label': 'Qualifications',   'type': 'text',   'max_length': 300},
            {'key': 'years_experience','label': 'Years of Experience','type': 'number'},
            {'key': 'mode',            'label': 'Mode',             'type': 'select', 'choices': ['In-person', 'Online', 'Both']},
            {'key': 'location',        'label': 'Location',         'type': 'text',   'max_length': 200},
            {'key': 'rate',            'label': 'Rate',             'type': 'text',   'max_length': 150, 'placeholder': 'e.g. ₦3,000/hr'},
            {'key': 'availability',    'label': 'Availability',     'type': 'days_hours'},
        ],
    },
    'freelancer': {
        'label': 'Freelancer',
        'emoji': '🧑\u200d💻',
        'blurb': 'Independent, project-based work — often remote',
        'fields': [
            {'key': 'skills',           'label': 'Skills',           'type': 'select_other', 'max_length': 300, 'required': True,
             'choices': ['Web development', 'Graphic design', 'Content writing', 'Video editing',
                         'Social media management', 'Virtual assistance', 'Translation', 'Photography',
                         'UI/UX design', 'Digital marketing']},
            {'key': 'services_offered', 'label': 'Services Offered', 'type': 'textarea', 'max_length': 1000},
            {'key': 'portfolio_link',   'label': 'Portfolio Link',   'type': 'url'},
            {'key': 'rate',             'label': 'Rate',             'type': 'text',     'max_length': 150},
            {'key': 'availability',     'label': 'Availability',     'type': 'select',   'choices': ['Full-time', 'Part-time', 'Project-based']},
            {'key': 'work_mode',        'label': 'Work Mode',        'type': 'select',   'choices': ['Remote', 'Hybrid', 'On-site']},
            {'key': 'tools_used',       'label': 'Tools Used',       'type': 'text',     'max_length': 300},
        ],
    },
    'artisan_technician': {
        'label': 'Artisan / Technician',
        'emoji': '🛠️',
        'blurb': 'Hands-on trade or repair work',
        'fields': [
            {'key': 'trade',            'label': 'Trade',             'type': 'text',     'max_length': 150, 'required': True, 'placeholder': 'e.g. Carpentry, GSM repair'},
            {'key': 'skills',           'label': 'Skills',            'type': 'select_other', 'max_length': 300,
             'choices': ['Carpentry', 'GSM/Phone repair', 'Electronics repair', 'Shoemaking', 'Tailoring',
                         'Welding', 'Auto mechanic', 'Refrigeration']},
            {'key': 'years_experience', 'label': 'Years of Experience','type': 'number'},
            {'key': 'tools_equipment',  'label': 'Tools / Equipment', 'type': 'text',     'max_length': 300},
            {'key': 'location',         'label': 'Location',          'type': 'text',     'max_length': 200},
            {'key': 'work_radius',      'label': 'Work Radius',       'type': 'select',   'choices': ['Within 5km', 'Within 10km', 'Within 20km', 'Citywide', 'Statewide', 'Nationwide']},
            {'key': 'availability',     'label': 'Availability',      'type': 'select',   'choices': ['Full-time', 'Part-time', 'Weekends only', 'By appointment']},
            {'key': 'pricing',          'label': 'Pricing',           'type': 'text',     'max_length': 200},
            {'key': 'certifications',   'label': 'Certifications',    'type': 'text',     'max_length': 300},
        ],
    },
    'service_provider': {
        'label': 'Service Provider',
        'emoji': '🚚',
        'blurb': 'Delivery, logistics, cleaning, transport and similar services',
        'fields': [
            {'key': 'service_type',      'label': 'Service Type',      'type': 'text',   'max_length': 150, 'required': True, 'placeholder': 'e.g. Dispatch rider, House cleaning'},
            {'key': 'coverage_area',     'label': 'Coverage Area',     'type': 'text',   'max_length': 200},
            {'key': 'vehicle_equipment', 'label': 'Vehicle / Equipment','type': 'text',  'max_length': 200},
            {'key': 'availability',      'label': 'Availability',      'type': 'select', 'choices': ['Full-time', 'Part-time', 'On-demand']},
            {'key': 'pricing',           'label': 'Pricing',           'type': 'text',   'max_length': 200},
            {'key': 'contact',           'label': 'Contact',           'type': 'text',   'max_length': 150},
            {'key': 'license_permit',    'label': 'License / Permit',  'type': 'text',   'max_length': 200},
        ],
    },
    'student_apprentice': {
        'label': 'Student / Apprentice',
        'emoji': '🎓',
        'blurb': 'Currently studying or learning a trade',
        'fields': [
            {'key': 'institution',      'label': 'Institution',        'type': 'text', 'max_length': 200, 'required': True},
            {'key': 'field_of_study',   'label': 'Field of Study',     'type': 'text', 'max_length': 200},
            {'key': 'level',            'label': 'Level / Year',       'type': 'text', 'max_length': 100, 'placeholder': 'e.g. 300 Level, Year 2 apprentice'},
            {'key': 'skills_learning',  'label': 'Skills Learning',    'type': 'select_other', 'max_length': 300,
             'choices': ['Coding/Programming', 'Graphic design', 'Tailoring', 'Catering', 'Hairdressing',
                         'Welding', 'Plumbing', 'Digital marketing']},
            {'key': 'availability',     'label': 'Availability',       'type': 'days_hours'},
            {'key': 'interests',        'label': 'Interests',          'type': 'text', 'max_length': 300},
        ],
    },
    'employer_recruiter': {
        'label': 'Employer / Recruiter',
        'emoji': '👔',
        'blurb': 'Hiring on behalf of a company',
        'fields': [
            {'key': 'company_name',     'label': 'Company Name',      'type': 'text',     'max_length': 200, 'required': True},
            {'key': 'industry',         'label': 'Industry',          'type': 'text',     'max_length': 150},
            {'key': 'company_size',     'label': 'Company Size',      'type': 'select',   'choices': ['1-10', '11-50', '51-200', '201-500', '500+']},
            {'key': 'hiring_for',       'label': 'Hiring For',        'type': 'textarea', 'max_length': 1000},
            {'key': 'company_location', 'label': 'Company Location',  'type': 'text',     'max_length': 200},
            {'key': 'website',          'label': 'Website',           'type': 'url'},
            {'key': 'contact',          'label': 'Contact',           'type': 'text',     'max_length': 150},
        ],
    },
    'other_professional': {
        'label': 'Other Professional',
        'emoji': '🔄',
        'blurb': "Doesn't fit the categories above",
        'fields': [
            {'key': 'description', 'label': 'What do you do?', 'type': 'textarea', 'max_length': 1000, 'required': True},
            {'key': 'skills',      'label': 'Skills',          'type': 'select_other', 'max_length': 300,
             'choices': ['Customer service', 'Public speaking', 'Project management', 'Research']},
            {'key': 'services',    'label': 'Services',        'type': 'text',     'max_length': 300},
            {'key': 'location',    'label': 'Location',        'type': 'text',     'max_length': 200},
            {'key': 'contact',     'label': 'Contact',         'type': 'text',     'max_length': 150},
        ],
    },
}

MEMBER_TYPE_CHOICES = [(key, cfg['label']) for key, cfg in MEMBER_TYPE_SCHEMA.items()]


def sanitize_member_type_data(member_type, raw_data):
    """
    Given a member_type key and a dict of raw submitted values, returns a
    cleaned dict containing only the keys defined in that type's schema,
    sanitized/validated per field 'type'. Unknown member_type -> {}.
    File fields are handled separately by the view (not stored in JSON).
    """
    schema = MEMBER_TYPE_SCHEMA.get(member_type)
    if not schema or not isinstance(raw_data, dict):
        return {}

    cleaned = {}
    for field in schema['fields']:
        key = field['key']
        ftype = field['type']
        if ftype == 'file':
            # Files are stored on their own model field(s), not in the JSON blob.
            continue

        if ftype == 'days_hours':
            # Combines a working-days multi-select with two hour-of-day
            # selects into one stored display string, e.g.
            # "Monday, Wednesday, Friday · 9:00 AM – 5:00 PM".
            days_raw = raw_data.get(key + '__days', [])
            if isinstance(days_raw, str):
                days_raw = [d.strip() for d in days_raw.split(',') if d.strip()]
            valid_days = [d for d in DAY_CHOICES if d in days_raw]

            open_v = str(raw_data.get(key + '__open', '') or '').strip()
            close_v = str(raw_data.get(key + '__close', '') or '').strip()
            if open_v not in HOUR_CHOICES:
                open_v = ''
            if close_v not in HOUR_CHOICES:
                close_v = ''

            parts = []
            if valid_days:
                parts.append(', '.join(valid_days))
            if open_v and close_v:
                parts.append(f'{open_v} – {close_v}')
            elif open_v:
                parts.append(f'From {open_v}')
            elif close_v:
                parts.append(f'Until {close_v}')

            value = ' · '.join(parts)
            if value:
                cleaned[key] = value
            continue

        value = raw_data.get(key, '')
        if value is None:
            value = ''
        value = str(value).strip()

        if not value:
            continue

        if ftype == 'textarea':
            value = sanitize_text(value)[:1000]
        elif ftype == 'text':
            value = sanitize_text(value)[: field.get('max_length', 300)]
        elif ftype == 'number':
            try:
                value = str(max(0, int(float(value))))
            except (ValueError, TypeError):
                continue
        elif ftype == 'url':
            try:
                value = validate_url(value)
            except ValidationError:
                continue
        elif ftype == 'select':
            choices = field.get('choices', [])
            if value not in choices:
                continue
        elif ftype == 'select_other':
            choices = field.get('choices', [])
            if value == 'Other':
                other_raw = raw_data.get(key + '__other', '')
                other_raw = '' if other_raw is None else str(other_raw).strip()
                if not other_raw:
                    continue
                value = sanitize_text(other_raw)[: field.get('max_length', 300)]
            elif value not in choices:
                continue
        cleaned[key] = value

    return cleaned


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


CV_ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx']


def validate_cv_extension(value):
    """Restrict CV/resume uploads to document formats only (server-side —
    the accept="" attribute on the file input is only a client-side hint)."""
    if value and hasattr(value, 'name'):
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in CV_ALLOWED_EXTENSIONS:
            raise ValidationError(
                f'CV must be a {", ".join(CV_ALLOWED_EXTENSIONS)} file, not "{ext}".'
            )



def _validate_single_owner(instance, page_field='business_page', profile_field='profile'):
    """
    Shared validation for professional-content models (services, portfolio
    items, achievements, posts, …) that can be owned by EITHER a BusinessPage
    OR a Profile directly, but never both and never neither.
    """
    page_id    = getattr(instance, f'{page_field}_id', None)
    profile_id = getattr(instance, f'{profile_field}_id', None)
    if page_id and profile_id:
        raise ValidationError('This can belong to a Business Page or a Profile, not both.')
    if not page_id and not profile_id:
        raise ValidationError('This must belong to either a Business Page or a Profile.')


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
        cover_photo = CloudinaryField('cover_photo', folder='profile_covers', blank=True, null=True)
    else:
        picture = models.ImageField(upload_to='profile_image/', default='male.png')
        cover_photo = models.ImageField(upload_to='profile_covers/', blank=True, null=True)
    
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

    # ── Interests (personalized feed signal) ─────────────────────────────
    # Free-form list of interest tags the user picks/edits (e.g. product
    # categories, event types, topics). Used alongside profession/skills to
    # personalize the home feed. Stored as a plain JSON list of strings.
    interests = models.JSONField(default=list, blank=True)

    # ── Member type / onboarding ("What do you use Marketfy for?") ──────
    member_type          = models.CharField(max_length=30, choices=MEMBER_TYPE_CHOICES, blank=True, default='')
    member_type_data     = models.JSONField(default=dict, blank=True)
    member_type_cv        = models.FileField(
        upload_to='member_type/cv/', null=True, blank=True,
        validators=[validate_cv_extension],
    )
    member_type_cv_name   = models.CharField(max_length=255, blank=True, default='')
    onboarding_completed = models.BooleanField(default=False)

    # ── Professional profile sections ────────────────────────────────────
    # Mirrors BusinessPage.enabled_sections / sells_products so a user's own
    # Profile can carry the same optional professional sections (Services,
    # Portfolio, Projects, Achievements, Jobs) that used to live only on a
    # BusinessPage. Which sections are suggested by default depends on the
    # profile's member_type — see PROFESSIONAL_SECTION_DEFAULTS below.
    PROFESSIONAL_SECTION_CHOICES = [
        ('services',     'Services'),
        ('portfolio',    'Portfolio'),
        ('projects',     'Projects'),
        ('achievements', 'Achievements'),
        ('jobs',         'Jobs'),
    ]
    VALID_PROFESSIONAL_SECTIONS = {s[0] for s in PROFESSIONAL_SECTION_CHOICES}

    # Suggested default sections per member_type — the profile owner can
    # still turn any of these on/off from their profile settings.
    PROFESSIONAL_SECTION_DEFAULTS = {
        'skilled_professional': ['services', 'portfolio', 'achievements'],
        'job_seeker':           [],
        'business_owner':       ['services', 'jobs'],
        'teacher_tutor':        ['services', 'achievements'],
        'freelancer':           ['services', 'portfolio', 'projects'],
        'artisan_technician':   ['services', 'portfolio', 'achievements'],
        'service_provider':     ['services', 'jobs'],
        'student_apprentice':   ['portfolio', 'projects', 'achievements'],
        'employer_recruiter':   ['jobs'],
        'other_professional':   ['services', 'portfolio', 'achievements'],
    }

    # Member types that default to selling products from their profile.
    MEMBER_TYPES_SELLING_BY_DEFAULT = {'business_owner'}

    sells_products   = models.BooleanField(default=False)
    enabled_sections = models.JSONField(default=list, blank=True)

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

        # Interests — keep a short, sanitized list of plain strings only.
        if isinstance(self.interests, (list, tuple)):
            cleaned_interests = []
            for tag in self.interests:
                tag = sanitize_text(str(tag))[:60]
                if tag and tag not in cleaned_interests:
                    cleaned_interests.append(tag)
                if len(cleaned_interests) >= 15:
                    break
            self.interests = cleaned_interests
        else:
            self.interests = []

        valid_member_types = [c[0] for c in MEMBER_TYPE_CHOICES]
        if self.member_type and self.member_type not in valid_member_types:
            self.member_type = ''
        if self.member_type:
            self.member_type_data = sanitize_member_type_data(self.member_type, self.member_type_data)
        else:
            self.member_type_data = {}

        if self.member_type_cv and hasattr(self.member_type_cv, 'name'):
            validate_cv_extension(self.member_type_cv)
            validate_file_size(self.member_type_cv, max_size_mb=5)
        elif not self.member_type_cv:
            self.member_type_cv_name = ''

        self.enabled_sections = self._sanitize_enabled_sections(self.enabled_sections)

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

        if self.cover_photo and hasattr(self.cover_photo, 'name'):
            validate_file_extension(self.cover_photo)
            validate_file_size(self.cover_photo, max_size_mb=10)

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

    # ── Cover photo URL helper ─────────────────────────────────────
    @property
    def get_cover_url(self):
        """
        Returns a full usable cover photo URL, or '' if none is set
        (the template falls back to a decorative gradient in that case).
        """
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                cover = self.cover_photo
                public_id = None
                if hasattr(cover, 'public_id') and cover.public_id:
                    public_id = str(cover.public_id).strip()
                elif cover and str(cover).strip() not in ('', 'None'):
                    public_id = str(cover).strip()

                if public_id:
                    return cloudinary.CloudinaryImage(public_id).build_url(secure=True)
                return ''
            else:
                cover = self.cover_photo
                if cover:
                    try:
                        return cover.url
                    except Exception:
                        pass
                return ''
        except Exception:
            return ''

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

    # ── Member type helpers ──────────────────────────────────────
    @property
    def member_type_schema(self):
        """The field list for this profile's chosen member type, or []."""
        return MEMBER_TYPE_SCHEMA.get(self.member_type, {}).get('fields', [])

    @property
    def member_type_label(self):
        return MEMBER_TYPE_SCHEMA.get(self.member_type, {}).get('label', '')

    @property
    def member_type_emoji(self):
        return MEMBER_TYPE_SCHEMA.get(self.member_type, {}).get('emoji', '')

    @property
    def member_type_display_fields(self):
        """
        List of (label, value) pairs for this profile's filled-in type-specific
        fields, for rendering on the profile page. Skips empty values.
        """
        data = self.member_type_data or {}
        out = []
        for field in self.member_type_schema:
            value = data.get(field['key'], '')
            if value:
                out.append((field['label'], value))
        if self.member_type_cv:
            out.append(('CV / Resume', self.member_type_cv.url))
        return out

    @property
    def member_type_cv_display_name(self):
        """Human-friendly filename for the uploaded CV, falling back to the
        stored path's basename if no original filename was recorded."""
        if self.member_type_cv_name:
            return self.member_type_cv_name
        if self.member_type_cv:
            return os.path.basename(self.member_type_cv.name)
        return ''

    def get_member_type_value(self, key, default=''):
        return (self.member_type_data or {}).get(key, default)

    # ── Professional section helpers ────────────────────────────────────
    @classmethod
    def _sanitize_enabled_sections(cls, raw):
        """Keep only known, deduplicated optional-section keys."""
        if not isinstance(raw, (list, tuple, set)):
            return []
        seen = []
        for key in raw:
            key = str(key).strip()
            if key in cls.VALID_PROFESSIONAL_SECTIONS and key not in seen:
                seen.append(key)
        return seen

    @classmethod
    def default_sections_for(cls, member_type):
        """The suggested optional sections for a given member_type."""
        return list(cls.PROFESSIONAL_SECTION_DEFAULTS.get(member_type, []))

    @property
    def is_professional(self):
        """True once the user has picked a member type / profession —
        i.e. their profile has something to show in the Professional tab."""
        return bool(self.member_type or self.profession)

    @property
    def show_products(self):
        return bool(self.sells_products)

    @property
    def show_services(self):
        return 'services' in (self.enabled_sections or [])

    @property
    def show_portfolio(self):
        return 'portfolio' in (self.enabled_sections or [])

    @property
    def show_projects(self):
        return 'projects' in (self.enabled_sections or [])

    @property
    def show_achievements(self):
        return 'achievements' in (self.enabled_sections or [])

    @property
    def show_jobs_section(self):
        return 'jobs' in (self.enabled_sections or [])

    @property
    def service_count(self):
        return self.services.count()

    @property
    def portfolio_count(self):
        return self.portfolio_items.filter(kind=BusinessPortfolioItem.KIND_PORTFOLIO).count()

    @property
    def project_count(self):
        return self.portfolio_items.filter(kind=BusinessPortfolioItem.KIND_PROJECT).count()

    @property
    def achievement_count(self):
        return self.achievements.count()

    @property
    def post_count(self):
        return self.professional_posts.count()

    @property
    def product_count(self):
        return self.user.products.count()

    @property
    def job_count(self):
        return self.user.job_vacancies.count()

    # ── Personalized-feed helpers ──────────────────────────────────────────
    # A lightweight "who this person is / what they care about" keyword bag,
    # built from profession, member type, skills/experience captured in
    # member_type_data, and explicit interest tags. Used by the home feed
    # ranking to score how relevant a piece of content is to this user.
    _WORD_RE = re.compile(r'[a-z0-9]+')

    @classmethod
    def _tokenize(cls, text):
        if not text:
            return set()
        return set(cls._WORD_RE.findall(str(text).lower()))

    @property
    def feed_keywords(self):
        kw = set()
        kw |= self._tokenize(self.profession)
        kw |= self._tokenize(self.member_type)
        kw |= self._tokenize(self.member_type_label)
        for value in (self.member_type_data or {}).values():
            if isinstance(value, (list, tuple)):
                for v in value:
                    kw |= self._tokenize(v)
            else:
                kw |= self._tokenize(value)
        for tag in (self.interests or []):
            kw |= self._tokenize(tag)
        kw |= self._tokenize(self.bio)
        return kw

    @property
    def feed_location_tokens(self):
        return self._tokenize(self.location)


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


class BusinessNotification(models.Model):
    """
    Notifications tied to a BusinessPage:
      - 'new_follower' → sent to the page owner when someone joins/follows the page.
      - 'new_product'  → sent to every follower of the page when the owner
                          uploads a new product/listing.
    Kept separate from FollowNotification (which is strictly for personal
    profile follows) since a BusinessPage can have many followers and many
    products, and a single user can trigger many of these over time.
    """
    NEW_FOLLOWER = 'new_follower'
    NEW_PRODUCT  = 'new_product'
    NEW_COMMENT  = 'new_comment'
    NOTIF_TYPE_CHOICES = [
        (NEW_FOLLOWER, 'New page follower'),
        (NEW_PRODUCT,  'New product'),
        (NEW_COMMENT,  'New comment on a post'),
    ]

    notif_type    = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    business_page = models.ForeignKey(
        'BusinessPage', on_delete=models.CASCADE, related_name='notifications'
    )
    # actor: the user who triggered the notification —
    #   the follower for 'new_follower', the page owner for 'new_product'.
    actor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_business_notifications'
    )
    # to_user: the recipient — the page owner for 'new_follower',
    #   each follower for 'new_product'.
    to_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='business_notifications'
    )
    product = models.ForeignKey(
        'Market', on_delete=models.CASCADE, null=True, blank=True,
        related_name='new_product_notifications',
        help_text='Set for new_product notifications only.'
    )
    post = models.ForeignKey(
        'BusinessPost', on_delete=models.CASCADE, null=True, blank=True,
        related_name='comment_notifications',
        help_text='Set for new_comment notifications only.'
    )
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'BusinessNotification_Table'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['to_user', 'is_read']),
            models.Index(fields=['business_page', 'notif_type']),
        ]

    def __str__(self):
        if self.notif_type == self.NEW_FOLLOWER:
            return f"{self.actor.username} joined {self.business_page.name}"
        return f"{self.business_page.name} posted a new product: {self.product}"


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

    # ── Job enquiry context ───────────────────────────────────────────────────
    # Set when an applicant messages a poster directly from a job vacancy page.
    # Stores a snapshot of the vacancy so the card stays visible even if the
    # listing is later deleted or closed.
    linked_job = models.ForeignKey(
        'JobVacancy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enquiry_messages',
    )
    linked_job_snapshot = models.JSONField(null=True, blank=True)
    # snapshot keys: job_id, title, company, category, category_label, location,
    # salary_range, is_open, image_url, detail_url

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
    def time_posted(self):
        """Human-friendly relative time, e.g. 'Just now', '2 hours ago', 'Yesterday', '3 days ago'."""
        now = timezone.localtime()
        posted = timezone.localtime(self.posted_on)
        seconds = (now - posted).total_seconds()

        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            mins = int(seconds // 60)
            return f"{mins} minute{'s' if mins != 1 else ''} ago"

        days_diff = (now.date() - posted.date()).days

        if days_diff == 0:
            hours = int(seconds // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days_diff == 1:
            return "Yesterday"
        if days_diff < 7:
            return f"{days_diff} days ago"
        if days_diff < 30:
            weeks = days_diff // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days_diff < 365:
            months = days_diff // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days_diff // 365
        return f"{years} year{'s' if years != 1 else ''} ago"

    @property
    def category_icon(self):
        return self.CATEGORY_ICONS.get(self.product_category, '📦')

    @property
    def category_label(self):
        return dict(self.CATEGORY_CHOICES).get(self.product_category, self.product_category)

    @property
    def average_rating(self):
        result = self.reviews.aggregate(avg=models.Avg('rating'))['avg']
        return round(result, 1) if result else 0

    @property
    def review_count(self):
        return self.reviews.count()

    @property
    def rating_breakdown(self):
        """Returns [{'stars': 5, 'count': N, 'pct': 0-100}, ...] for the bar chart, 5→1."""
        total = self.review_count
        counts = {r: 0 for r in range(1, 6)}
        for row in self.reviews.values('rating').annotate(c=models.Count('rating')):
            counts[row['rating']] = row['c']
        return [
            {'stars': s, 'count': counts[s], 'pct': round((counts[s] / total) * 100) if total else 0}
            for s in range(5, 0, -1)
        ]


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


class ProductReview(models.Model):
    """
    Star rating + written review left by a buyer on a Market listing.
    One review per (product, user) — the user can edit/delete their own.
    """
    RATING_CHOICES = [
        (1, '1 – Poor'),
        (2, '2 – Fair'),
        (3, '3 – Good'),
        (4, '4 – Very Good'),
        (5, '5 – Excellent'),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product    = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='reviews')
    user       = models.ForeignKey(User,   on_delete=models.CASCADE, related_name='product_reviews')
    rating     = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment    = models.TextField(max_length=2000, blank=True, default='')
    is_edited  = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProductReview_Table'
        ordering = ['-created_at']
        unique_together = ('product', 'user')
        indexes = [
            models.Index(fields=['product', '-created_at'], name='review_product_time_idx'),
        ]

    def __str__(self):
        return f'{self.user.username} rated {self.product.product_name} {self.rating}★'

    def clean(self):
        super().clean()
        self.comment = sanitize_text(self.comment, 'comment')
        if self.rating not in dict(self.RATING_CHOICES):
            raise ValidationError({'rating': 'Rating must be between 1 and 5.'})
        if self.product_id and self.product.product_owner_id == self.user_id:
            raise ValidationError('You cannot review your own listing.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def star_range(self):
        return range(1, 6)


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
    # ── Event type (LinkedIn-style broad category set) ─────────────────────
    TYPE_TOWN        = 'town'
    TYPE_FESTIVAL     = 'festival'
    TYPE_WEDDING       = 'wedding'
    TYPE_CONFERENCE    = 'conference'
    TYPE_WORKSHOP      = 'workshop'
    TYPE_WEBINAR       = 'webinar'
    TYPE_NETWORKING    = 'networking'
    TYPE_MEETUP        = 'meetup'
    TYPE_SEMINAR       = 'seminar'
    TYPE_TRAINING      = 'training'
    TYPE_CONCERT       = 'concert'
    TYPE_SPORTS        = 'sports'
    TYPE_EXHIBITION    = 'exhibition'
    TYPE_CHARITY       = 'charity'
    TYPE_PARTY         = 'party'
    TYPE_REUNION       = 'reunion'
    TYPE_RELIGIOUS     = 'religious'
    TYPE_PRODUCT_LAUNCH = 'product_launch'
    TYPE_SALE          = 'sale'
    TYPE_OTHER         = 'other'

    TYPE_CHOICES = [
        (TYPE_TOWN,           'Town Meeting'),
        (TYPE_FESTIVAL,       'Festival'),
        (TYPE_WEDDING,        'Wedding'),
        (TYPE_CONFERENCE,     'Conference'),
        (TYPE_WORKSHOP,       'Workshop'),
        (TYPE_WEBINAR,        'Webinar'),
        (TYPE_NETWORKING,     'Networking'),
        (TYPE_MEETUP,         'Meetup'),
        (TYPE_SEMINAR,        'Seminar'),
        (TYPE_TRAINING,       'Training / Class'),
        (TYPE_CONCERT,        'Concert / Live Music'),
        (TYPE_SPORTS,         'Sports'),
        (TYPE_EXHIBITION,     'Exhibition / Expo'),
        (TYPE_CHARITY,        'Charity / Fundraiser'),
        (TYPE_PARTY,          'Party / Social'),
        (TYPE_REUNION,        'Reunion'),
        (TYPE_RELIGIOUS,      'Religious / Faith'),
        (TYPE_PRODUCT_LAUNCH, 'Product Launch'),
        (TYPE_SALE,           'Sale / Promo'),
        (TYPE_OTHER,          'Other'),
    ]

    TYPE_EMOJIS = {
        TYPE_TOWN: '🏛️', TYPE_FESTIVAL: '🎪', TYPE_WEDDING: '💍',
        TYPE_CONFERENCE: '🎤', TYPE_WORKSHOP: '🛠️', TYPE_WEBINAR: '💻',
        TYPE_NETWORKING: '🤝', TYPE_MEETUP: '👥', TYPE_SEMINAR: '📚',
        TYPE_TRAINING: '🎓', TYPE_CONCERT: '🎵', TYPE_SPORTS: '⚽',
        TYPE_EXHIBITION: '🖼️', TYPE_CHARITY: '❤️', TYPE_PARTY: '🎉',
        TYPE_REUNION: '👨‍👩‍👧‍👦', TYPE_RELIGIOUS: '🙏', TYPE_PRODUCT_LAUNCH: '🚀',
        TYPE_SALE: '🏷️', TYPE_OTHER: '✨',
    }

    TYPE_COLORS = {
        TYPE_TOWN: '#0095f6', TYPE_FESTIVAL: '#ff6b35', TYPE_WEDDING: '#e91e8c',
        TYPE_CONFERENCE: '#2563eb', TYPE_WORKSHOP: '#0891b2', TYPE_WEBINAR: '#6366f1',
        TYPE_NETWORKING: '#059669', TYPE_MEETUP: '#0d9488', TYPE_SEMINAR: '#7c3aed',
        TYPE_TRAINING: '#4338ca', TYPE_CONCERT: '#db2777', TYPE_SPORTS: '#16a34a',
        TYPE_EXHIBITION: '#9333ea', TYPE_CHARITY: '#dc2626', TYPE_PARTY: '#f59e0b',
        TYPE_REUNION: '#ea580c', TYPE_RELIGIOUS: '#78350f', TYPE_PRODUCT_LAUNCH: '#111827',
        TYPE_SALE: '#ca8a04', TYPE_OTHER: '#7c3aed',
    }

    title       = models.CharField(max_length=200)
    event_type  = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER, db_index=True)
    date        = models.DateField(db_index=True)
    time        = models.TimeField(null=True, blank=True)
    end_date    = models.DateField(null=True, blank=True, help_text='Optional — for multi-day events')
    end_time    = models.TimeField(null=True, blank=True)
    location    = models.CharField(max_length=300, blank=True, default='')
    description = models.TextField(blank=True, default='')

    # ── Useful info, LinkedIn-events style ──────────────────────────────────
    organizer_name = models.CharField(max_length=200, blank=True, default='')
    contact_email  = models.EmailField(blank=True, default='')
    contact_phone  = models.CharField(max_length=20, blank=True, default='')

    is_virtual   = models.BooleanField(default=False, db_index=True)
    virtual_link = models.URLField(max_length=500, blank=True, default='')

    is_free = models.BooleanField(default=True)
    price   = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    capacity = models.PositiveIntegerField(null=True, blank=True, help_text='Leave blank for unlimited spots')

    is_cancelled = models.BooleanField(default=False, db_index=True)

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

    def clean(self):
        super().clean()
        self.title          = sanitize_text(self.title, 'product_name')
        self.location       = sanitize_text(self.location, 'location')
        self.description    = sanitize_text(self.description, 'product_description')
        self.organizer_name = sanitize_text(self.organizer_name)
        if self.contact_phone:
            try:
                self.contact_phone = validate_phone_number(self.contact_phone)
            except ValidationError:
                self.contact_phone = ''
        if self.virtual_link:
            try:
                self.virtual_link = validate_url(self.virtual_link)
            except ValidationError:
                self.virtual_link = ''
        if self.is_free:
            self.price = None

    @property
    def type_emoji(self):
        return self.TYPE_EMOJIS.get(self.event_type, '📌')

    @property
    def type_color(self):
        return self.TYPE_COLORS.get(self.event_type, '#0095f6')

    @property
    def time_display(self):
        if not self.time:
            return 'All Day'
        h, m = self.time.hour, self.time.minute
        ap = 'AM' if h < 12 else 'PM'
        h12 = h % 12 or 12
        return f'{h12}:{m:02d} {ap}'

    # ── Follower / attendee helpers (LinkedIn-style "Follow"/RSVP) ─────────
    @property
    def follower_count(self):
        return self.follows.count()

    @property
    def going_count(self):
        return self.follows.filter(status=EventFollow.STATUS_GOING).count()

    @property
    def interested_count(self):
        return self.follows.filter(status=EventFollow.STATUS_INTERESTED).count()

    @property
    def is_full(self):
        if not self.capacity:
            return False
        return self.going_count >= self.capacity

    @property
    def spots_left(self):
        if not self.capacity:
            return None
        return max(0, self.capacity - self.going_count)

    @property
    def is_past(self):
        today = timezone.localdate()
        end = self.end_date or self.date
        return end < today

    @property
    def price_display(self):
        if self.is_free:
            return 'Free'
        return f'₦{self.price:,.2f}' if self.price is not None else 'Paid'


class EventFollow(models.Model):
    """
    A user's relationship to a SocialEvent — mirrors LinkedIn's Follow/RSVP
    pattern. 'interested' = loosely tracking it; 'going' = confirmed attending.
    `notify` controls whether the user receives EventNotification updates.
    """
    STATUS_INTERESTED = 'interested'
    STATUS_GOING      = 'going'
    STATUS_CHOICES = [
        (STATUS_INTERESTED, 'Interested'),
        (STATUS_GOING,      'Going'),
    ]

    event      = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name='follows')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followed_events')
    status     = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_INTERESTED)
    notify     = models.BooleanField(default=True, help_text='Receive notifications about this event')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('event', 'user')
        ordering = ['-created_at']
        db_table = 'EventFollow_Table'

    def __str__(self):
        return f'{self.user.username} · {self.status} · {self.event.title}'


class EventNotification(models.Model):
    """
    Notifications sent to a SocialEvent's followers:
      - 'event_updated'   → organizer changed key event details
      - 'event_reminder'  → the event is starting soon
      - 'event_cancelled' → the organizer cancelled the event
      - 'new_comment'     → someone commented on an event the user follows
    """
    EVENT_UPDATED   = 'event_updated'
    EVENT_REMINDER  = 'event_reminder'
    EVENT_CANCELLED = 'event_cancelled'
    NEW_COMMENT     = 'new_comment'
    NOTIF_TYPE_CHOICES = [
        (EVENT_UPDATED,   'Event updated'),
        (EVENT_REMINDER,  'Event reminder'),
        (EVENT_CANCELLED, 'Event cancelled'),
        (NEW_COMMENT,     'New comment'),
    ]

    notif_type = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    event      = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name='notifications')
    actor      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_event_notifications')
    to_user    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_notifications')
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'EventNotification_Table'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['to_user', 'is_read']),
            models.Index(fields=['event', 'notif_type']),
        ]

    def __str__(self):
        return f'{self.get_notif_type_display()} — {self.event.title} → {self.to_user.username}'


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

    # ── Work mode ─────────────────────────────────────────────────────────────
    # Self-declared, LinkedIn-style workplace type: where does the work happen.
    WORK_ONSITE = 'on_site'
    WORK_REMOTE = 'remote'
    WORK_HYBRID = 'hybrid'

    WORK_MODE_CHOICES = [
        (WORK_ONSITE, 'On-site'),
        (WORK_REMOTE, 'Remote'),
        (WORK_HYBRID, 'Hybrid'),
    ]

    # ── Advertiser type ──────────────────────────────────────────────────────
    # Self-declared label so applicants can gauge, at a glance, who is behind
    # a vacancy: an individual, a company/school, or a government body. This
    # is NOT a verification — templates should still show a "verify
    # independently" note for government-tagged posts.
    ADV_PERSONAL        = 'personal'
    ADV_COMPANY_SCHOOL  = 'company_school'
    ADV_GOVERNMENT      = 'government'

    ADVERTISER_CHOICES = [
        (ADV_PERSONAL,       'Personal'),
        (ADV_COMPANY_SCHOOL, 'Company / School'),
        (ADV_GOVERNMENT,     'Government'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    posted_by    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_vacancies')
    category     = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CAT_FULLTIME, db_index=True)
    work_mode    = models.CharField(
        max_length=20, choices=WORK_MODE_CHOICES, default=WORK_ONSITE, db_index=True,
        help_text='Where the work happens — On-site, Remote, or Hybrid (like LinkedIn)',
    )
    advertiser_type = models.CharField(
        max_length=20, choices=ADVERTISER_CHOICES, default=ADV_PERSONAL, db_index=True,
        help_text='Who is behind this vacancy — helps applicants judge how official it is',
    )
    title        = models.CharField(max_length=200)
    company      = models.CharField(max_length=150, blank=True, default='')
    location     = models.CharField(max_length=300, blank=True, default='')
    description  = models.TextField()
    requirements = models.TextField(blank=True, default='')
    contact_info = models.CharField(max_length=300, blank=True, default='',
                                    help_text='Email, phone, or link to apply')
    apply_link   = models.URLField(max_length=500, blank=True, default='',
                                    help_text='Optional external link — official portal, application form, etc.')
    salary_range = models.CharField(max_length=100, blank=True, default='',
                                    help_text='e.g. ₦80,000–₦120,000/month or "Negotiable"')
    if settings.USE_CLOUDINARY:
        cover_image = CloudinaryField('image', folder='job_covers', blank=True, null=True)
    else:
        cover_image = models.ImageField(upload_to='job_covers/', blank=True, null=True)
    # FK to BusinessPage — set when a job vacancy is posted via a business page
    business_page = models.ForeignKey(
        'BusinessPage', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='job_vacancies',
    )
    is_open      = models.BooleanField(default=True, db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'JobVacancy_Table'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} [{self.get_category_display()}] — {self.posted_by.username}'

    def clean(self):
        super().clean()
        self.title        = sanitize_text(self.title)
        self.company      = sanitize_text(self.company)
        self.location     = sanitize_text(self.location, 'location')
        self.description  = sanitize_text(self.description, 'product_description')
        self.requirements = sanitize_text(self.requirements, 'product_description')
        self.contact_info = sanitize_text(self.contact_info)
        self.salary_range = sanitize_text(self.salary_range)
        if self.apply_link:
            try:
                self.apply_link = validate_url(self.apply_link)
            except ValidationError:
                self.apply_link = ''

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

    # ── Work mode display helpers ────────────────────────────────────────────
    @property
    def work_mode_emoji(self):
        return {
            self.WORK_ONSITE: '🏢',
            self.WORK_REMOTE: '🏡',
            self.WORK_HYBRID: '🔀',
        }.get(self.work_mode, '🏢')

    @property
    def work_mode_color(self):
        return {
            self.WORK_ONSITE: '#0f766e',
            self.WORK_REMOTE: '#16a34a',
            self.WORK_HYBRID: '#9333ea',
        }.get(self.work_mode, '#0f766e')

    # ── Advertiser display helpers ──────────────────────────────────────────
    @property
    def advertiser_emoji(self):
        return {
            self.ADV_PERSONAL:       '🙋',
            self.ADV_COMPANY_SCHOOL: '🏢',
            self.ADV_GOVERNMENT:     '🏛️',
        }.get(self.advertiser_type, '🙋')

    @property
    def advertiser_color(self):
        return {
            self.ADV_PERSONAL:       '#64748b',
            self.ADV_COMPANY_SCHOOL: '#0f766e',
            self.ADV_GOVERNMENT:     '#b45309',
        }.get(self.advertiser_type, '#64748b')

    @property
    def is_government_advertiser(self):
        return self.advertiser_type == self.ADV_GOVERNMENT


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

    # ─────────────────────────────────────────────────────────────────────
    # Page type / profession — what kind of professional or business this
    # page represents. Drives which optional sections (Services, Portfolio,
    # Projects, Achievements, Jobs, Products) are suggested by default.
    # Mirrors the shape of MEMBER_TYPE_SCHEMA above, but scoped to Pages.
    # ─────────────────────────────────────────────────────────────────────
    PAGE_TYPE_BUSINESS     = 'business'
    PAGE_TYPE_FREELANCER   = 'freelancer'
    PAGE_TYPE_DEVELOPER    = 'developer'
    PAGE_TYPE_TEACHER      = 'teacher'
    PAGE_TYPE_ARTISAN      = 'artisan'
    PAGE_TYPE_SERVICE      = 'service_provider'
    PAGE_TYPE_CREATIVE     = 'creative'
    PAGE_TYPE_STUDENT      = 'student'
    PAGE_TYPE_SKILLED      = 'skilled_professional'
    PAGE_TYPE_OTHER        = 'other'

    PAGE_TYPE_CHOICES = [
        (PAGE_TYPE_BUSINESS,   'Business Owner'),
        (PAGE_TYPE_FREELANCER, 'Freelancer'),
        (PAGE_TYPE_DEVELOPER,  'Developer / Tech Professional'),
        (PAGE_TYPE_TEACHER,    'Teacher / Tutor'),
        (PAGE_TYPE_ARTISAN,    'Artisan / Technician'),
        (PAGE_TYPE_SERVICE,    'Service Provider'),
        (PAGE_TYPE_CREATIVE,   'Creative / Artist'),
        (PAGE_TYPE_STUDENT,    'Student'),
        (PAGE_TYPE_SKILLED,    'Skilled Professional'),
        (PAGE_TYPE_OTHER,      'Other Professional'),
    ]

    # Which optional sections make sense by default for each page type.
    # The page owner can still turn any of these on/off at creation or edit.
    PAGE_TYPE_SECTION_DEFAULTS = {
        PAGE_TYPE_BUSINESS:   ['services', 'jobs'],
        PAGE_TYPE_FREELANCER: ['services', 'portfolio', 'projects'],
        PAGE_TYPE_DEVELOPER:  ['services', 'portfolio', 'projects', 'achievements'],
        PAGE_TYPE_TEACHER:    ['services', 'achievements'],
        PAGE_TYPE_ARTISAN:    ['services', 'portfolio', 'achievements'],
        PAGE_TYPE_SERVICE:    ['services', 'jobs'],
        PAGE_TYPE_CREATIVE:   ['portfolio', 'projects', 'achievements'],
        PAGE_TYPE_STUDENT:    ['portfolio', 'projects', 'achievements'],
        PAGE_TYPE_SKILLED:    ['services', 'portfolio', 'achievements'],
        PAGE_TYPE_OTHER:      ['services', 'portfolio', 'projects', 'achievements', 'jobs'],
    }

    # Page types that default to selling products, since most professional
    # pages (tutors, freelancers, artisans providing services…) don't.
    PAGE_TYPES_SELLING_BY_DEFAULT = {PAGE_TYPE_BUSINESS}

    OPTIONAL_SECTION_CHOICES = [
        ('services',     'Services'),
        ('portfolio',    'Portfolio'),
        ('projects',     'Projects'),
        ('achievements', 'Achievements'),
        ('jobs',         'Jobs'),
    ]
    VALID_OPTIONAL_SECTIONS = {s[0] for s in OPTIONAL_SECTION_CHOICES}

    page_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_pages')
    name        = models.CharField(max_length=150)
    slug        = models.SlugField(max_length=160, unique=True)
    category    = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='others')
    page_type   = models.CharField(max_length=25, choices=PAGE_TYPE_CHOICES, default=PAGE_TYPE_BUSINESS, db_index=True)
    # Products are opt-in: only professionals/businesses that actually sell
    # physical or digital products should see the Products tab & be able to
    # post Market listings from this page.
    sells_products   = models.BooleanField(default=True)
    # Which optional sections (see OPTIONAL_SECTION_CHOICES) are turned on
    # for this page. Stored as a plain list, e.g. ["services", "portfolio"].
    enabled_sections = models.JSONField(default=list, blank=True)
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

    # ── Business hours ───────────────────────────────────────────────────────
    # Stored as {"mon": {"open": "09:00", "close": "18:00", "closed": false}, ...}
    # A missing/empty dict means hours haven't been set for that page yet.
    DAY_CHOICES = [
        ('mon', 'Monday'), ('tue', 'Tuesday'), ('wed', 'Wednesday'),
        ('thu', 'Thursday'), ('fri', 'Friday'), ('sat', 'Saturday'), ('sun', 'Sunday'),
    ]
    DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    business_hours = models.JSONField(
        default=dict, blank=True,
        help_text='Per-day opening hours, e.g. {"mon": {"open": "09:00", "close": "18:00", "closed": false}}',
    )

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
        self.business_hours = self._sanitize_business_hours(self.business_hours)
        if self.page_type not in dict(self.PAGE_TYPE_CHOICES):
            self.page_type = self.PAGE_TYPE_BUSINESS
        self.enabled_sections = self._sanitize_enabled_sections(self.enabled_sections)

    @classmethod
    def _sanitize_enabled_sections(cls, raw):
        """Keep only known, deduplicated optional-section keys."""
        if not isinstance(raw, (list, tuple, set)):
            return []
        seen = []
        for key in raw:
            key = str(key).strip()
            if key in cls.VALID_OPTIONAL_SECTIONS and key not in seen:
                seen.append(key)
        return seen

    @classmethod
    def default_sections_for(cls, page_type):
        """The suggested optional sections for a given page type."""
        return list(cls.PAGE_TYPE_SECTION_DEFAULTS.get(page_type, cls.PAGE_TYPE_SECTION_DEFAULTS[cls.PAGE_TYPE_OTHER]))

    @classmethod
    def _sanitize_business_hours(cls, raw):
        """Keep only known day keys with valid HH:MM open/close values."""
        if not isinstance(raw, dict):
            return {}
        time_re = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
        clean = {}
        for day in cls.DAY_ORDER:
            entry = raw.get(day)
            if not isinstance(entry, dict):
                continue
            closed = bool(entry.get('closed'))
            open_v = str(entry.get('open', '') or '').strip()
            close_v = str(entry.get('close', '') or '').strip()
            if closed or not time_re.match(open_v) or not time_re.match(close_v):
                clean[day] = {'open': '', 'close': '', 'closed': True}
            else:
                clean[day] = {'open': open_v, 'close': close_v, 'closed': False}
        return clean

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

    # ── Business hours helpers ───────────────────────────────────────────────
    @property
    def has_business_hours(self):
        return any(not v.get('closed') for v in (self.business_hours or {}).values())

    def get_hours_for_day(self, day_key):
        return (self.business_hours or {}).get(day_key, {'open': '', 'close': '', 'closed': True})

    @property
    def today_hours(self):
        day_key = self.DAY_ORDER[timezone.localtime().weekday()]
        return self.get_hours_for_day(day_key)

    @property
    def is_open_now(self):
        """True = open, False = closed, None = no hours configured for today."""
        hours = self.today_hours
        if not hours or hours.get('closed') or not hours.get('open') or not hours.get('close'):
            return False if self.has_business_hours else None
        now_t = timezone.localtime().time()
        try:
            open_t  = datetime.strptime(hours['open'],  '%H:%M').time()
            close_t = datetime.strptime(hours['close'], '%H:%M').time()
        except (ValueError, TypeError):
            return None
        if open_t <= close_t:
            return open_t <= now_t <= close_t
        # Overnight hours, e.g. 18:00 → 02:00
        return now_t >= open_t or now_t <= close_t

    @property
    def hours_display(self):
        """Ordered list for template display: [{key, label, open, close, closed}, ...]."""
        labels = dict(self.DAY_CHOICES)
        today_key = self.DAY_ORDER[timezone.localtime().weekday()]
        out = []
        for key in self.DAY_ORDER:
            h = self.get_hours_for_day(key)
            out.append({
                'key': key,
                'label': labels[key],
                'open': h.get('open', ''),
                'close': h.get('close', ''),
                'closed': h.get('closed', True),
                'is_today': key == today_key,
            })
        return out

    # ── Average page rating ──────────────────────────────────────────────────
    # Derived from ProductReview entries left on this page's Market listings —
    # no separate BusinessPage review model needed.
    @property
    def average_rating(self):
        result = ProductReview.objects.filter(
            product__business_page=self
        ).aggregate(avg=models.Avg('rating'))['avg']
        return round(result, 1) if result else 0

    @property
    def review_count(self):
        return ProductReview.objects.filter(product__business_page=self).count()

    @property
    def post_count(self):
        return self.posts.count()

    # ── Professional page sections ───────────────────────────────────────────
    @property
    def page_type_label(self):
        return dict(self.PAGE_TYPE_CHOICES).get(self.page_type, 'Business Owner')

    @property
    def show_products(self):
        return bool(self.sells_products)

    @property
    def show_services(self):
        return 'services' in (self.enabled_sections or [])

    @property
    def show_portfolio(self):
        return 'portfolio' in (self.enabled_sections or [])

    @property
    def show_projects(self):
        return 'projects' in (self.enabled_sections or [])

    @property
    def show_achievements(self):
        return 'achievements' in (self.enabled_sections or [])

    @property
    def show_jobs_section(self):
        return 'jobs' in (self.enabled_sections or [])

    @property
    def service_count(self):
        return self.services.count()

    @property
    def portfolio_count(self):
        return self.portfolio_items.filter(kind=BusinessPortfolioItem.KIND_PORTFOLIO).count()

    @property
    def project_count(self):
        return self.portfolio_items.filter(kind=BusinessPortfolioItem.KIND_PROJECT).count()

    @property
    def achievement_count(self):
        return self.achievements.count()


# ─────────────────────────────────────────────────────────────────────────────
# Optional professional-page sections — Services, Portfolio/Projects,
# Achievements. Jobs already exist via JobVacancy.business_page and Products
# via Market.business_page, so no new models are needed for those two.
# ─────────────────────────────────────────────────────────────────────────────

class BusinessService(models.Model):
    """A service offered by a professional/business page — e.g. 'Logo design',
    'AC repair', 'Home tutoring'. Shown in the optional Services section."""
    service_id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # A service belongs to EITHER a BusinessPage OR a user's Profile directly
    # (never both, never neither) — see clean(). Profile-owned services are
    # the default now; business_page stays for pages kept as a separate
    # company/brand identity.
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='services', null=True, blank=True)
    profile       = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='services', null=True, blank=True)
    title         = models.CharField(max_length=150)
    description   = models.TextField(blank=True, default='')
    price_text    = models.CharField(max_length=150, blank=True, default='',
                                      help_text='e.g. ₦15,000, Starting from ₦5,000/hr, or Negotiable')

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='business_service_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='business_service_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'BusinessService_Table'
        ordering = ['order', '-created_at']

    def __str__(self):
        # business_page is nullable (profile-owned services have no page),
        # so never dereference it directly here — use the owner-agnostic
        # helper instead, which falls back to the profile's username.
        return f'{self.title} — {self.owner_name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.description = sanitize_text(self.description, 'about')
        self.price_text  = sanitize_text(self.price_text)
        if not self.title:
            raise ValidationError({'title': 'Service title is required.'})
        _validate_single_owner(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def get_image_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.image:
                    pid = str(getattr(self.image, 'public_id', None) or self.image).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return ''
            return self.image.url if self.image else ''
        except Exception:
            return ''

    @property
    def owner(self):
        """Either the owning BusinessPage or the owning Profile."""
        return self.business_page or self.profile

    @property
    def owner_user(self):
        return self.business_page.owner if self.business_page_id else self.profile.user

    @property
    def owner_name(self):
        if self.business_page_id:
            return self.business_page.name
        return self.profile.full_name or self.profile.user.username


class BusinessPortfolioItem(models.Model):
    """A single Portfolio piece or Project shown on a professional page.
    Same shape for both — 'kind' distinguishes a past-work sample
    (portfolio) from a featured/ongoing body of work (project)."""
    KIND_PORTFOLIO = 'portfolio'
    KIND_PROJECT   = 'project'
    KIND_CHOICES = [
        (KIND_PORTFOLIO, 'Portfolio piece'),
        (KIND_PROJECT,   'Project'),
    ]

    item_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='portfolio_items', null=True, blank=True)
    profile       = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='portfolio_items', null=True, blank=True)
    kind          = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_PORTFOLIO, db_index=True)
    title         = models.CharField(max_length=150)
    description   = models.TextField(blank=True, default='')
    link_url      = models.URLField(max_length=500, blank=True, default='')
    is_ongoing    = models.BooleanField(default=False, help_text='Only meaningful for projects.')

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='business_portfolio_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='business_portfolio_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'BusinessPortfolioItem_Table'
        ordering = ['order', '-created_at']

    def __str__(self):
        return f'{self.title} ({self.get_kind_display()})'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.description = sanitize_text(self.description, 'about')
        if self.kind not in dict(self.KIND_CHOICES):
            self.kind = self.KIND_PORTFOLIO
        if self.link_url:
            try:
                self.link_url = validate_url(self.link_url)
            except ValidationError:
                self.link_url = ''
        if not self.title:
            raise ValidationError({'title': 'Title is required.'})
        _validate_single_owner(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def get_image_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.image:
                    pid = str(getattr(self.image, 'public_id', None) or self.image).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return ''
            return self.image.url if self.image else ''
        except Exception:
            return ''

    @property
    def owner(self):
        return self.business_page or self.profile

    @property
    def owner_user(self):
        return self.business_page.owner if self.business_page_id else self.profile.user


class BusinessAchievement(models.Model):
    """A certification, award, or milestone shown on a professional page."""
    achievement_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page  = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='achievements', null=True, blank=True)
    profile        = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='achievements', null=True, blank=True)
    title          = models.CharField(max_length=150)
    issuer         = models.CharField(max_length=150, blank=True, default='')
    description    = models.TextField(blank=True, default='')
    date_achieved  = models.DateField(blank=True, null=True)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='business_achievement_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='business_achievement_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'BusinessAchievement_Table'
        ordering = ['order', '-date_achieved', '-created_at']

    def __str__(self):
        # business_page is nullable (profile-owned achievements have no
        # page) — use the owner-agnostic helper, never business_page.name
        # directly, or this raises AttributeError for profile-owned rows.
        return f'{self.title} — {self.owner_name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.issuer      = sanitize_text(self.issuer)
        self.description = sanitize_text(self.description, 'about')
        if not self.title:
            raise ValidationError({'title': 'Achievement title is required.'})
        _validate_single_owner(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def get_image_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.image:
                    pid = str(getattr(self.image, 'public_id', None) or self.image).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return ''
            return self.image.url if self.image else ''
        except Exception:
            return ''

    @property
    def owner(self):
        return self.business_page or self.profile

    @property
    def owner_user(self):
        return self.business_page.owner if self.business_page_id else self.profile.user

    @property
    def owner_name(self):
        if self.business_page_id:
            return self.business_page.name
        return self.profile.full_name or self.profile.user.username


# ─────────────────────────────────────────────────────────────────────────────
# Business page updates — image / video / text / poll posts
# ─────────────────────────────────────────────────────────────────────────────

class BusinessPost(models.Model):
    """
    A single update posted to a BusinessPage's feed. One of four kinds:
      - image : one or more photos (see BusinessPostImage), + optional caption
      - video : a single short video (15–90s guideline, enforced client-side),
                + optional caption
      - text  : caption only, no media
      - poll  : caption used as an optional intro line; the actual question and
                options live on the related BusinessPostPoll / BusinessPostPollOption
    """
    TYPE_IMAGE = 'image'
    TYPE_VIDEO = 'video'
    TYPE_TEXT  = 'text'
    TYPE_POLL  = 'poll'
    POST_TYPE_CHOICES = [
        (TYPE_IMAGE, 'Image'),
        (TYPE_VIDEO, 'Video'),
        (TYPE_TEXT,  'Text update'),
        (TYPE_POLL,  'Poll'),
    ]

    MIN_VIDEO_SECONDS = 15
    MAX_VIDEO_SECONDS = 90

    # Content category — a lightweight tag independent of post_type (which
    # describes the *media*: image/video/text/poll). Lets a professional
    # page label what a post is *about*, e.g. a work update vs a tutorial.
    CATEGORY_UPDATE       = 'update'
    CATEGORY_WORK         = 'work'
    CATEGORY_PROJECT      = 'project'
    CATEGORY_TUTORIAL     = 'tutorial'
    CATEGORY_ANNOUNCEMENT = 'announcement'
    POST_CATEGORY_CHOICES = [
        (CATEGORY_UPDATE,       'General Update'),
        (CATEGORY_WORK,         'Work Update'),
        (CATEGORY_PROJECT,      'Project'),
        (CATEGORY_TUTORIAL,     'Tutorial'),
        (CATEGORY_ANNOUNCEMENT, 'Announcement'),
    ]

    post_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='posts', null=True, blank=True)
    profile       = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='professional_posts', null=True, blank=True)
    post_type     = models.CharField(max_length=10, choices=POST_TYPE_CHOICES, default=TYPE_TEXT, db_index=True)
    post_category = models.CharField(max_length=15, choices=POST_CATEGORY_CHOICES, default=CATEGORY_UPDATE, db_index=True)
    caption       = models.TextField(blank=True, default='')

    if settings.USE_CLOUDINARY:
        video = CloudinaryField('video', folder='business_post_videos', resource_type='video', blank=True, null=True)
    else:
        video = models.FileField(upload_to='business_post_videos/', blank=True, null=True)

    # Client-reported duration (seconds) — used only to nudge the 15–90s
    # guideline in the UI; actual media length can't be verified server-side
    # without a transcoding pipeline, so this is best-effort, not enforced.
    video_duration_seconds = models.PositiveIntegerField(blank=True, null=True)

    is_pinned  = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'BusinessPost_Table'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f'{self.get_post_type_display()} post by {self.owner_name}'

    def clean(self):
        super().clean()
        if self.post_type not in dict(self.POST_TYPE_CHOICES):
            raise ValidationError({'post_type': 'Invalid post type.'})
        if self.post_category not in dict(self.POST_CATEGORY_CHOICES):
            self.post_category = self.CATEGORY_UPDATE
        self.caption = sanitize_text(self.caption, 'post_caption')
        _validate_single_owner(self)

        if self.post_type == self.TYPE_TEXT and not self.caption:
            raise ValidationError({'caption': 'Text updates need some text.'})

        if self.post_type == self.TYPE_VIDEO:
            if self.video:
                validate_file_extension(self.video)
                validate_file_size(self.video, max_size_mb=100)
            elif not self.pk:
                raise ValidationError({'video': 'Please attach a video.'})

        if self.video_duration_seconds is not None and self.video_duration_seconds < 0:
            self.video_duration_seconds = None

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def get_video_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.video:
                    pid = str(getattr(self.video, 'public_id', None) or self.video).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryVideo(pid).build_url(secure=True)
                return ''
            else:
                return self.video.url if self.video else ''
        except Exception:
            return ''

    @property
    def video_duration_display(self):
        secs = self.video_duration_seconds
        if not secs:
            return ''
        m, s = divmod(int(secs), 60)
        return f'{m}:{s:02d}' if m else f'0:{s:02d}'

    @property
    def vibe_count(self):
        return self.vibes.count()

    @property
    def comment_count(self):
        return self.comments.count()

    @property
    def category_label(self):
        return dict(self.POST_CATEGORY_CHOICES).get(self.post_category, 'General Update')

    @property
    def top_vibe_emoji(self):
        row = (
            self.vibes.values('vibe_type')
            .annotate(cnt=models.Count('id'))
            .order_by('-cnt')
            .first()
        )
        if not row:
            return ''
        return BusinessPostVibe.VIBE_EMOJIS.get(row['vibe_type'], '')

    @property
    def time_posted(self):
        now = timezone.localtime()
        posted = timezone.localtime(self.created_at)
        seconds = (now - posted).total_seconds()
        if seconds < 60:
            return 'Just now'
        if seconds < 3600:
            mins = int(seconds // 60)
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        days_diff = (now.date() - posted.date()).days
        if days_diff == 0:
            hours = int(seconds // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days_diff == 1:
            return 'Yesterday'
        if days_diff < 7:
            return f'{days_diff} days ago'
        if days_diff < 30:
            weeks = days_diff // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days_diff < 365:
            months = days_diff // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days_diff // 365
        return f"{years} year{'s' if years != 1 else ''} ago"

    @property
    def owner(self):
        """Either the owning BusinessPage or the owning Profile."""
        return self.business_page or self.profile

    @property
    def owner_user(self):
        return self.business_page.owner if self.business_page_id else self.profile.user

    @property
    def owner_name(self):
        if self.business_page_id:
            return self.business_page.name
        return self.profile.full_name or self.profile.user.username

    @property
    def owner_picture_url(self):
        if self.business_page_id:
            return self.business_page.get_logo_url
        return self.profile.get_picture_url

    @property
    def owner_url_kwargs(self):
        """Handy for templates that need to link back to whichever owner posted this."""
        if self.business_page_id:
            return {'type': 'page', 'slug': self.business_page.slug}
        return {'type': 'profile', 'username': self.profile.user.username}


class BusinessPostImage(models.Model):
    """One photo within an 'image' type BusinessPost — supports multi-image posts."""
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post     = models.ForeignKey(BusinessPost, on_delete=models.CASCADE, related_name='images')
    order    = models.PositiveSmallIntegerField(default=0)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='business_post_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='business_post_images/', blank=True, null=True)

    class Meta:
        ordering = ['order']

    def clean(self):
        super().clean()
        if self.image:
            validate_file_extension(self.image)
            validate_file_size(self.image, max_size_mb=10)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def get_image_url(self):
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                import cloudinary
                if self.image:
                    pid = str(getattr(self.image, 'public_id', None) or self.image).strip()
                    if pid and pid not in ('', 'None'):
                        return cloudinary.CloudinaryImage(pid).build_url(secure=True)
                return ''
            else:
                return self.image.url if self.image else ''
        except Exception:
            return ''


class BusinessPostPoll(models.Model):
    """The poll attached to a 'poll' type BusinessPost — one per post."""
    poll_id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post           = models.OneToOneField(BusinessPost, on_delete=models.CASCADE, related_name='poll')
    question       = models.CharField(max_length=300)
    allow_multiple = models.BooleanField(default=False, help_text='Let voters pick more than one option.')
    closes_at      = models.DateTimeField(blank=True, null=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question

    def clean(self):
        super().clean()
        self.question = sanitize_text(self.question, 'poll_question')
        if not self.question:
            raise ValidationError({'question': 'A poll needs a question.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_closed(self):
        return bool(self.closes_at and timezone.now() >= self.closes_at)

    @property
    def total_votes(self):
        return BusinessPostPollVote.objects.filter(option__poll=self).values('user_id').distinct().count()

    def voted_option_ids(self, user):
        if not user or not user.is_authenticated:
            return set()
        return set(
            BusinessPostPollVote.objects.filter(option__poll=self, user=user)
            .values_list('option_id', flat=True)
        )


class BusinessPostPollOption(models.Model):
    option_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll      = models.ForeignKey(BusinessPostPoll, on_delete=models.CASCADE, related_name='options')
    text      = models.CharField(max_length=120)
    order     = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text

    def clean(self):
        super().clean()
        self.text = sanitize_text(self.text, 'poll_option')
        if not self.text:
            raise ValidationError({'text': 'Option text is required.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def vote_count(self):
        return self.votes.count()

    def vote_pct(self, total_votes=None):
        total = total_votes if total_votes is not None else self.poll.total_votes
        if not total:
            return 0
        return round((self.vote_count / total) * 100)


class BusinessPostPollVote(models.Model):
    vote_id  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    option   = models.ForeignKey(BusinessPostPollOption, on_delete=models.CASCADE, related_name='votes')
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_poll_votes')
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['option', 'user'], name='unique_vote_per_option_per_user'),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# BusinessPostVibe / BusinessPostComment — reactions & comments on posts,
# mirroring the JobVibe/JobComment and EventVibe/EventComment pattern so the
# existing generic _card_vibe_* / _card_comments_* view helpers can be reused.
# ─────────────────────────────────────────────────────────────────────────────

class BusinessPostVibe(models.Model):
    """Vibe reactions on BusinessPost updates. One per user per post."""

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

    post       = models.ForeignKey(BusinessPost, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User,         on_delete=models.CASCADE, related_name='business_post_vibes')
    vibe_type  = models.CharField(max_length=10, choices=VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')
        ordering = ['created_at']
        db_table = 'BusinessPostVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on post {self.post_id}"


class BusinessPostComment(models.Model):
    """Comments on BusinessPost updates."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post       = models.ForeignKey(BusinessPost, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User,         on_delete=models.CASCADE, related_name='business_post_comments')
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
        db_table = 'BusinessPostComment_Table'

    def __str__(self):
        return f"{self.author.username} on post {self.post_id}: {self.text[:50]}"
