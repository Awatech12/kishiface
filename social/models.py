from django.db import models
from django.contrib.postgres.indexes import GinIndex
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
# Member Type / Onboarding — "What do you use KishiHub for?"
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
            {'key': 'skills',            'label': 'Skills',             'type': 'skills_multi', 'max_length': 300,
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
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
        ],
    },
    'job_seeker': {
        'label': 'Job Seeker',
        'emoji': '👔',
        'blurb': 'Looking for employment',
        'fields': [
            {'key': 'desired_job',        'label': 'Desired Job',        'type': 'text',     'max_length': 150, 'required': True},
            {'key': 'skills',             'label': 'Skills',             'type': 'skills_multi', 'max_length': 300,
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
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
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
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
        ],
    },
    'freelancer': {
        'label': 'Freelancer',
        'emoji': '🧑\u200d💻',
        'blurb': 'Independent, project-based work — often remote',
        'fields': [
            {'key': 'skills',           'label': 'Skills',           'type': 'skills_multi', 'max_length': 300, 'required': True,
             'choices': ['Web development', 'Graphic design', 'Content writing', 'Video editing',
                         'Social media management', 'Virtual assistance', 'Translation', 'Photography',
                         'UI/UX design', 'Digital marketing']},
            {'key': 'services_offered', 'label': 'Services Offered', 'type': 'textarea', 'max_length': 1000},
            {'key': 'portfolio_link',   'label': 'Portfolio Link',   'type': 'url'},
            {'key': 'rate',             'label': 'Rate',             'type': 'text',     'max_length': 150},
            {'key': 'availability',     'label': 'Availability',     'type': 'select',   'choices': ['Full-time', 'Part-time', 'Project-based']},
            {'key': 'work_mode',        'label': 'Work Mode',        'type': 'select',   'choices': ['Remote', 'Hybrid', 'On-site']},
            {'key': 'tools_used',       'label': 'Tools Used',       'type': 'text',     'max_length': 300},
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
        ],
    },
    'artisan_technician': {
        'label': 'Artisan / Technician',
        'emoji': '🛠️',
        'blurb': 'Hands-on trade or repair work',
        'fields': [
            {'key': 'trade',            'label': 'Trade',             'type': 'text',     'max_length': 150, 'required': True, 'placeholder': 'e.g. Carpentry, GSM repair'},
            {'key': 'skills',           'label': 'Skills',            'type': 'skills_multi', 'max_length': 300,
             'choices': ['Carpentry', 'GSM/Phone repair', 'Electronics repair', 'Shoemaking', 'Tailoring',
                         'Welding', 'Auto mechanic', 'Refrigeration']},
            {'key': 'years_experience', 'label': 'Years of Experience','type': 'number'},
            {'key': 'tools_equipment',  'label': 'Tools / Equipment', 'type': 'text',     'max_length': 300},
            {'key': 'location',         'label': 'Location',          'type': 'text',     'max_length': 200},
            {'key': 'work_radius',      'label': 'Work Radius',       'type': 'select',   'choices': ['Within 5km', 'Within 10km', 'Within 20km', 'Citywide', 'Statewide', 'Nationwide']},
            {'key': 'availability',     'label': 'Availability',      'type': 'select',   'choices': ['Full-time', 'Part-time', 'Weekends only', 'By appointment']},
            {'key': 'pricing',          'label': 'Pricing',           'type': 'text',     'max_length': 200},
            {'key': 'certifications',   'label': 'Certifications',    'type': 'text',     'max_length': 300},
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
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
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
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
            {'key': 'skills_learning',  'label': 'Skills Learning',    'type': 'skills_multi', 'max_length': 300,
             'choices': ['Coding/Programming', 'Graphic design', 'Tailoring', 'Catering', 'Hairdressing',
                         'Welding', 'Plumbing', 'Digital marketing']},
            {'key': 'availability',     'label': 'Availability',       'type': 'days_hours'},
            {'key': 'interests',        'label': 'Interests',          'type': 'text', 'max_length': 300},
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
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
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
        ],
    },
    'other_professional': {
        'label': 'Other Professional',
        'emoji': '🔄',
        'blurb': "Doesn't fit the categories above",
        'fields': [
            {'key': 'description', 'label': 'What do you do?', 'type': 'textarea', 'max_length': 1000, 'required': True},
            {'key': 'skills',      'label': 'Skills',          'type': 'skills_multi', 'max_length': 300,
             'choices': ['Customer service', 'Public speaking', 'Project management', 'Research']},
            {'key': 'services',    'label': 'Services',        'type': 'text',     'max_length': 300},
            {'key': 'location',    'label': 'Location',        'type': 'text',     'max_length': 200},
            {'key': 'contact',     'label': 'Contact',         'type': 'text',     'max_length': 150},
            {'key': 'cv',                 'label': 'CV / Resume',        'type': 'file'},
        ],
    },
}

MEMBER_TYPE_CHOICES = [(key, cfg['label']) for key, cfg in MEMBER_TYPE_SCHEMA.items()]

# ─────────────────────────────────────────────────────────────────────────────
# "What I'm Looking For" — a short, member-type-aware statement of intent
# (job, hiring, clients, collaborators, etc.), shown on the profile and
# editable from the same edit UI as everything else. Kept as its own small
# schema (rather than free text) so it stays scannable and filterable, the
# same way member_type_data does for the bigger onboarding fields.
# Each entry is (key, label). A generic fallback list is used for profiles
# with no member_type set yet.
# ─────────────────────────────────────────────────────────────────────────────
LOOKING_FOR_SCHEMA = {
    'skilled_professional': [('clients', 'Clients / customers'), ('jobs', 'Full-time or contract work'), ('collaboration', 'Collaboration opportunities')],
    'job_seeker':           [('job', 'A job'), ('internship', 'An internship'), ('mentorship', 'Mentorship')],
    'business_owner':       [('customers', 'Customers'), ('hiring', 'Hiring talent'), ('partnerships', 'Business partnerships'), ('investors', 'Investors')],
    'teacher_tutor':        [('students', 'Students'), ('teaching_jobs', 'Teaching opportunities'), ('collaboration', 'Collaboration with other educators')],
    'freelancer':           [('freelance_work', 'Freelance work'), ('clients', 'Clients'), ('collaboration', 'Collaboration opportunities')],
    'artisan_technician':   [('clients', 'Clients / customers'), ('jobs', 'Full-time or contract work')],
    'service_provider':     [('clients', 'Clients / customers'), ('partnerships', 'Business partnerships')],
    'student_apprentice':   [('internship', 'Internships'), ('mentorship', 'Mentorship'), ('entry_level_jobs', 'Entry-level jobs')],
    'employer_recruiter':   [('candidates', 'Candidates to hire'), ('partnerships', 'Recruitment partnerships')],
    'other_professional':   [('opportunities', 'Opportunities'), ('collaboration', 'Collaboration')],
}
LOOKING_FOR_GENERIC_CHOICES = [
    ('job', 'A job'), ('hiring', 'Hiring'), ('freelance_work', 'Freelance work'),
    ('clients', 'Clients'), ('business_opportunities', 'Business opportunities'),
    ('collaboration', 'Collaboration'), ('students_customers', 'Students / customers'),
]
LOOKING_FOR_LABELS = dict(LOOKING_FOR_GENERIC_CHOICES)
for _choices in LOOKING_FOR_SCHEMA.values():
    LOOKING_FOR_LABELS.update(dict(_choices))


def _clean_skills_list(choices, selected_raw, other_raw):
    """
    Shared cleaner for 'skills_multi' fields — used both by
    sanitize_member_type_data (full onboarding/member-type submit) and by
    Profile.set_skills (targeted skills-only edit from the profile-edit UI),
    so there's exactly one place that defines what a valid skill looks like.
    `selected_raw` is the list of checked known-choice values; `other_raw` is
    either a list of extra free-text skills or a comma-separated string of
    them. Returns a deduplicated (case-insensitive) list of plain strings,
    capped at 20.
    """
    if isinstance(selected_raw, str):
        selected_raw = [selected_raw] if selected_raw else []
    if isinstance(other_raw, (list, tuple)):
        other_items = [str(s).strip() for s in other_raw if str(s).strip()]
    else:
        other_raw = '' if other_raw is None else str(other_raw)
        other_items = [s.strip() for s in other_raw.split(',') if s.strip()]

    cleaned_skills = []
    for item in list(selected_raw) + other_items:
        item = sanitize_text(str(item))[:60]
        if not item:
            continue
        if item.lower() in {s.lower() for s in cleaned_skills}:
            continue
        cleaned_skills.append(item)
        if len(cleaned_skills) >= 20:
            break
    return cleaned_skills


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

        if ftype == 'skills_multi':
            # Multiple checkbox-selected skills from this field's `choices`,
            # plus optional free-text "other" skills the user typed in
            # (comma-separated). Stored as a deduplicated JSON list of
            # plain strings — this is the real "Skills" data shown as chips
            # on the profile, not something derived from profession/category.
            selected_raw = raw_data.get(key, [])
            other_raw = raw_data.get(key + '__other', '')
            cleaned_skills = _clean_skills_list(field.get('choices', []), selected_raw, other_raw)
            if cleaned_skills:
                cleaned[key] = cleaned_skills
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


CERTIFICATE_ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png']


def validate_certificate_extension(value):
    """Restrict certificate/result uploads (WAEC, NECO, etc.) to document or
    scanned-image formats — same server-side-vs-client-hint reasoning as
    validate_cv_extension above."""
    if value and hasattr(value, 'name'):
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in CERTIFICATE_ALLOWED_EXTENSIONS:
            raise ValidationError(
                f'Document must be a {", ".join(CERTIFICATE_ALLOWED_EXTENSIONS)} file, not "{ext}".'
            )



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

    # ── Languages (professional service signal) ───────────────────────────
    # Free-form list of languages the user can communicate in, each with an
    # optional proficiency level — mirrors a LinkedIn-style "Languages"
    # section so clients/employers/collaborators can judge fit for
    # cross-language work at a glance. Stored as a JSON list of
    # {'name': str, 'proficiency': str} dicts.
    # Kept as plain, already-display-ready strings (not slug/label pairs) so
    # templates can print an item's proficiency directly with no lookup.
    LANGUAGE_PROFICIENCY_CHOICES = ['Native', 'Fluent', 'Professional', 'Conversational', 'Basic']
    LANGUAGE_PROFICIENCY_DEFAULT = 'Conversational'
    languages = models.JSONField(default=list, blank=True)

    # ── Member type / onboarding ("What do you use KishiHub for?") ──────
    member_type          = models.CharField(max_length=30, choices=MEMBER_TYPE_CHOICES, blank=True, default='')
    member_type_data     = models.JSONField(default=dict, blank=True)

    # ── "What I'm Looking For" — structured intent, see LOOKING_FOR_SCHEMA.
    # Stored as a list of choice keys (usually one, but a profile can select
    # more than one) so it can be displayed/edited/filtered without parsing
    # free text.
    looking_for           = models.JSONField(default=list, blank=True)
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
        ('experience',   'Experience'),
        ('education',    'Education'),
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
        'skilled_professional': ['experience', 'education', 'services', 'portfolio', 'achievements'],
        'job_seeker':           ['experience', 'education'],
        'business_owner':       ['experience', 'services', 'jobs'],
        'teacher_tutor':        ['experience', 'education', 'services', 'achievements'],
        'freelancer':           ['experience', 'services', 'portfolio', 'projects'],
        'artisan_technician':   ['experience', 'services', 'portfolio', 'achievements'],
        'service_provider':     ['experience', 'services', 'jobs'],
        'student_apprentice':   ['education', 'portfolio', 'projects', 'achievements'],
        'employer_recruiter':   ['experience', 'jobs'],
        'other_professional':   ['experience', 'education', 'services', 'portfolio', 'achievements'],
    }

    # Member types that default to selling products from their profile.
    MEMBER_TYPES_SELLING_BY_DEFAULT = {'business_owner'}

    sells_products   = models.BooleanField(default=False)
    enabled_sections = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    online = models.BooleanField(default=False)

    class Meta:
        db_table = 'Profile_Table'
        indexes = [
            GinIndex(fields=['bio'], name='profile_bio_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['profession'], name='profile_prof_trgm', opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return self.user.username

    def clean(self):
        super().clean()
        self.bio          = sanitize_text(self.bio, 'bio')
        self.location     = sanitize_text(self.location, 'location')
        self.full_name    = sanitize_text(self.full_name)
        self.address      = sanitize_text(self.address)
        self.profession      = sanitize_text(self.profession,      'profession')

        # "What I'm Looking For" — keep only keys valid for this profile's
        # current member type (falling back to the generic list if no
        # member_type is set), deduplicated and capped.
        valid_looking_for = dict(LOOKING_FOR_SCHEMA.get(self.member_type, LOOKING_FOR_GENERIC_CHOICES))
        if isinstance(self.looking_for, (list, tuple)):
            cleaned_looking_for = []
            for key in self.looking_for:
                key = str(key).strip()
                if key in valid_looking_for and key not in cleaned_looking_for:
                    cleaned_looking_for.append(key)
                if len(cleaned_looking_for) >= 3:
                    break
            self.looking_for = cleaned_looking_for
        else:
            self.looking_for = []

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

        # Languages — list of {'name', 'proficiency'} dicts, deduplicated by
        # case-insensitive name and capped so the section stays scannable.
        # Accepts plain strings too (defaults to 'conversational') so older
        # or hand-built payloads don't get silently dropped.
        if isinstance(self.languages, (list, tuple)):
            valid_proficiencies = {p.lower(): p for p in self.LANGUAGE_PROFICIENCY_CHOICES}
            cleaned_languages = []
            seen_names = set()
            for entry in self.languages:
                if isinstance(entry, dict):
                    name = sanitize_text(str(entry.get('name', '') or ''))[:60]
                    proficiency_raw = str(entry.get('proficiency', '') or '').strip().lower()
                else:
                    name = sanitize_text(str(entry))[:60]
                    proficiency_raw = ''
                if not name:
                    continue
                dedupe_key = name.lower()
                if dedupe_key in seen_names:
                    continue
                proficiency = valid_proficiencies.get(proficiency_raw, self.LANGUAGE_PROFICIENCY_DEFAULT)
                seen_names.add(dedupe_key)
                cleaned_languages.append({'name': name, 'proficiency': proficiency})
                if len(cleaned_languages) >= 12:
                    break
            self.languages = cleaned_languages
        else:
            self.languages = []

        valid_member_types = [c[0] for c in MEMBER_TYPE_CHOICES]
        if self.member_type and self.member_type not in valid_member_types:
            self.member_type = ''
        if self.member_type:
            self.member_type_data = sanitize_member_type_data(self.member_type, self.member_type_data)
        else:
            self.member_type_data = {}

        if self.member_type_cv and hasattr(self.member_type_cv, 'name'):
            # Only re-validate when a *new* file was just assigned this
            # request (FieldFile._committed is False for an unsaved
            # assignment, True for a value that's already persisted).
            # Without this guard, every unrelated profile save (cover
            # photo, bio, etc.) re-ran extension validation against the
            # already-stored CV, and storage backends that don't keep the
            # original extension in the saved file name (e.g. Cloudinary
            # for raw/document uploads) made that re-check fail forever,
            # blocking all future profile updates.
            if not self.member_type_cv._committed:
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
        # member_type_cv is excluded here: it's already validated at upload
        # time (in the onboarding/update_profile views, and via the
        # _committed-guarded check below). Re-validating it on every save
        # via full_clean() checks the *already-stored* file, and some
        # storage backends (e.g. Cloudinary, for raw/document uploads)
        # strip the extension from the stored filename -- which permanently
        # fails validate_cv_extension and blocks all future saves for that
        # user, even ones unrelated to the CV.
        self.full_clean(exclude=['member_type_cv'])
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

    # ── Has the user actually uploaded a photo? ──────────────────
    @property
    def has_custom_picture(self):
        """True once the user has uploaded a real profile photo, as
        opposed to still sitting on the default placeholder avatar.
        get_picture_url always returns *some* URL (it falls back to the
        default), so it can't be used to detect "no photo set" — this
        checks the same public_id/blank conditions get_picture_url does,
        just to report presence instead of building a URL. Used by
        Profile Strength."""
        try:
            if getattr(settings, 'USE_CLOUDINARY', False):
                pic = self.picture
                public_id = None
                if hasattr(pic, 'public_id') and pic.public_id:
                    public_id = str(pic.public_id).strip()
                elif pic and str(pic).strip() not in ('', 'None'):
                    public_id = str(pic).strip()
                return bool(public_id) and public_id != 'logo_iowyea'
            else:
                pic = self.picture
                return bool(pic) and getattr(pic, 'name', '') not in ('', 'male.png')
        except Exception:
            return False

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

    # Keys that get their own dedicated profile section (Skills chips) and
    # so are always left out of member_type_display_fields — the full
    # exclusion set (including every key the What I Do sentence composer
    # below might use) is defined as _DISPLAY_FIELD_EXCLUDE further down,
    # once that composer's field list is in view.
    _SKILLS_FIELD_KEYS = {'skills', 'skills_learning'}

    @staticmethod
    def _format_mtd_value(value):
        """member_type_data values are usually plain strings, but
        'skills_multi' fields store a list — format either into a display
        string with no per-caller special-casing needed."""
        if isinstance(value, (list, tuple)):
            return ', '.join(str(v) for v in value if v)
        return value

    @property
    def member_type_display_fields(self):
        """
        List of (label, value) pairs for this profile's filled-in type-specific
        fields, for rendering on the profile page. Skips empty values, the
        skills field, and whichever field is already shown as the headline /
        What I Do sentence (see _DISPLAY_FIELD_EXCLUDE) — so nothing repeats.
        """
        data = self.member_type_data or {}
        headline_field = self.member_type_headline_field
        skip_keys = self._DISPLAY_FIELD_EXCLUDE | ({headline_field['key']} if headline_field else set())
        out = []
        for field in self.member_type_schema:
            if field['key'] in skip_keys:
                continue
            value = data.get(field['key'], '')
            if value:
                out.append((field['label'], self._format_mtd_value(value)))
        if self.member_type_cv:
            out.append(('CV / Resume', self.member_type_cv.url))
        return out

    @property
    def member_type_headline_field(self):
        """
        The schema field treated as this member type's 'headline' — i.e. the
        single most identifying detail (e.g. Profession for a Skilled
        Professional, Desired Job for a Job Seeker, Business Name for a
        Business Owner). This is the field marked 'required' in
        MEMBER_TYPE_SCHEMA, since every type defines exactly one. Falls back
        to the first field if none are marked required.
        """
        fields = self.member_type_schema
        for field in fields:
            if field.get('required') and field['key'] not in self._SKILLS_FIELD_KEYS:
                return field
        for field in fields:
            if field['key'] not in self._SKILLS_FIELD_KEYS:
                return field
        return fields[0] if fields else None

    @property
    def member_type_headline_value(self):
        """The filled-in value of member_type_headline_field, or ''."""
        field = self.member_type_headline_field
        if not field:
            return ''
        return self._format_mtd_value(self.get_member_type_value(field['key']))

    @property
    def member_type_secondary_field(self):
        """
        A secondary supporting field for this type, preferring a
        location-like field (location, business_location, coverage_area,
        preferred_location, company_location) since that's the most useful
        second detail to surface alongside the headline.
        """
        fields = self.member_type_schema
        for field in fields:
            if 'location' in field['key'] or field['key'] == 'coverage_area':
                return field
        return None

    @property
    def member_type_secondary_value(self):
        """The filled-in value of member_type_secondary_field, or ''."""
        field = self.member_type_secondary_field
        if not field:
            return ''
        return self.get_member_type_value(field['key'])

    @property
    def kishihub_use_headline(self):
        """
        Short 'what this person uses KishiHub for' summary, meant for post
        author sub-lines, e.g. 'Skilled Professional · Plumber'. Falls back
        to just the member type label if the headline field isn't filled in,
        and to legacy profession/location if no member type is set at all.
        """
        label = self.member_type_label
        if not label:
            return self.profession or ''
        value = self.member_type_headline_value
        return f'{label} · {value}' if value else label

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

    # ── Real Skills — the user's actual selected/entered skills, not
    #    anything derived from profession or business category. ──────────
    @property
    def skills_list(self):
        """The skills this profile actually selected/entered during
        onboarding or profile editing (member_type_data['skills'] or
        ['skills_learning'] for students), as a clean list of strings for
        chip display. Never derived from profession or business category."""
        raw = self.get_member_type_value('skills') or self.get_member_type_value('skills_learning')
        if isinstance(raw, (list, tuple)):
            return [str(s) for s in raw if s]
        if raw:
            return [raw]
        return []

    @property
    def skills_schema_field(self):
        """The schema field dict for this profile's skills-type field
        ('skills' or 'skills_learning'), or None if the current member type
        has no skills field at all (e.g. Business Owner)."""
        for field in self.member_type_schema:
            if field['type'] == 'skills_multi':
                return field
        return None

    def set_skills(self, selected, other_text=''):
        """Updates only the skills entry inside member_type_data, leaving
        every other member_type_data field untouched — used by the compact
        Skills edit modal so it doesn't have to resubmit (and risk wiping)
        the rest of the onboarding data. Returns False if this profile's
        member type has no skills field to update. Caller is responsible
        for calling save()."""
        field = self.skills_schema_field
        if not field:
            return False
        cleaned = _clean_skills_list(field.get('choices', []), selected, other_text)
        data = dict(self.member_type_data or {})
        if cleaned:
            data[field['key']] = cleaned
        else:
            data.pop(field['key'], None)
        self.member_type_data = data
        return True

    # ── "What I'm Looking For" ────────────────────────────────────────────
    @property
    def looking_for_field_choices(self):
        """The (key, label) choices this profile can currently pick from
        for 'What I'm Looking For', based on its member type."""
        return LOOKING_FOR_SCHEMA.get(self.member_type, LOOKING_FOR_GENERIC_CHOICES)

    @property
    def looking_for_display(self):
        """Human-readable labels for this profile's selected
        'What I'm Looking For' choices."""
        labels = dict(self.looking_for_field_choices) or LOOKING_FOR_LABELS
        return [LOOKING_FOR_LABELS.get(key, labels.get(key, key)) for key in (self.looking_for or [])]

    # ── "What I Do" — a short, natural-language description of what this
    #    profile does, composed per member type from the actual fields the
    #    user filled in / selected (never a generic placeholder). Each
    #    branch degrades gracefully: it uses the richest combination of
    #    fields available and falls back to a shorter sentence, then to a
    #    generic description field, then to the bio, if some fields are
    #    missing. ──────────────────────────────────────────────────────────
    _WHAT_I_DO_KEYS = (
        'business_description', 'services_offered', 'products_services',
        'hiring_for', 'description', 'experience',
    )
    # Every member_type_data key referenced by any branch below, plus the
    # generic fallback keys — excluded from the Details list so nothing the
    # What I Do sentence already says gets repeated there.
    _DISPLAY_FIELD_EXCLUDE = {
        'skills', 'skills_learning',
        'business_name', 'business_category',
        'subjects', 'teaching_level',
        'profession', 'desired_job',
        'trade', 'service_type', 'coverage_area',
        'institution', 'field_of_study',
        'company_name', 'hiring_for',
        'description',
        'business_description', 'services_offered', 'products_services', 'experience',
    }

    @property
    def what_i_do_headline(self):
        """Headline to show above the What I Do description. Left blank for
        any onboarded member type, since what_i_do_summary already composes
        a full sentence that includes it — only used as a fallback for
        profiles with no member_type set yet."""
        if self.member_type in MEMBER_TYPE_SCHEMA:
            return ''
        return self.profession

    @property
    def what_i_do_summary(self):
        mt = self.member_type
        data = self.member_type_data or {}
        skills = self.skills_list
        skills_text = ', '.join(skills[:3])

        if mt == 'business_owner':
            name = data.get('business_name', '')
            category = data.get('business_category', '')
            if name and category:
                return f"I own {name}, a {category} business."[:220]
            if name:
                return f"I own {name}."[:220]

        elif mt == 'teacher_tutor':
            subjects = data.get('subjects', '')
            level = data.get('teaching_level', '')
            if subjects and level:
                return f"I teach {subjects} at the {level} level."[:220]
            if subjects:
                return f"I teach {subjects}."[:220]

        elif mt == 'skilled_professional':
            profession = data.get('profession', '')
            if profession and skills:
                return f"I work as a {profession}, specializing in {skills_text}."[:220]
            if profession:
                return f"I work as a {profession}."[:220]

        elif mt == 'job_seeker':
            desired = data.get('desired_job', '')
            if desired and skills:
                return f"I'm looking for work as a {desired}, with skills in {skills_text}."[:220]
            if desired:
                return f"I'm looking for work as a {desired}."[:220]

        elif mt == 'freelancer':
            services = self._format_mtd_value(data.get('services_offered', ''))
            if skills and services:
                return f"I'm a freelancer offering {skills_text}. {services}"[:220]
            if skills:
                return f"I'm a freelancer offering {skills_text} services."[:220]
            if services:
                return services[:220]

        elif mt == 'artisan_technician':
            trade = data.get('trade', '')
            if trade and skills:
                return f"I work as a {trade}, skilled in {skills_text}."[:220]
            if trade:
                return f"I work as a {trade}."[:220]

        elif mt == 'service_provider':
            service_type = data.get('service_type', '')
            coverage = data.get('coverage_area', '')
            if service_type and coverage:
                return f"I provide {service_type} services within {coverage}."[:220]
            if service_type:
                return f"I provide {service_type} services."[:220]

        elif mt == 'student_apprentice':
            institution = data.get('institution', '')
            field_of_study = data.get('field_of_study', '')
            if field_of_study and institution:
                sentence = f"I'm studying {field_of_study} at {institution}."
            elif institution:
                sentence = f"I'm a student at {institution}."
            elif field_of_study:
                sentence = f"I'm studying {field_of_study}."
            else:
                sentence = ''
            if skills:
                sentence = (sentence + f" Currently learning {skills_text}.").strip()
            if sentence:
                return sentence[:220]

        elif mt == 'employer_recruiter':
            company = data.get('company_name', '')
            hiring_for = self._format_mtd_value(data.get('hiring_for', ''))
            if company and hiring_for:
                return f"I'm hiring on behalf of {company}. Currently hiring for {hiring_for}"[:220]
            if company:
                return f"I'm hiring on behalf of {company}."[:220]

        elif mt == 'other_professional':
            description = self._format_mtd_value(data.get('description', ''))
            if description and skills:
                return f"{description} Skilled in {skills_text}."[:220]
            if description:
                return description[:220]

        # Generic fallback — a member type with a missing required field, or
        # no member_type at all: use whichever description-shaped field is
        # filled in, then the bio.
        for key in self._WHAT_I_DO_KEYS:
            value = data.get(key)
            if value:
                return self._format_mtd_value(value)[:220]
        return (self.bio or '')[:220]

    @property
    def languages_display(self):
        """Languages formatted as ['English · Fluent', 'French · Basic'] for
        simple, no-logic template rendering (chips, headline, etc.)."""
        out = []
        for entry in (self.languages or []):
            name = entry.get('name', '')
            if not name:
                continue
            proficiency = entry.get('proficiency', '')
            out.append(f'{name} · {proficiency}' if proficiency else name)
        return out

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

    # ── Profile completion — single source of truth ─────────────────────
    # Used by the profile page (owner-only nudge) and mirrored 1:1 by the
    # JS in profile.html for the edit-sheet live preview. Keep the two in
    # sync if this list ever changes. Prioritizes meaningful professional
    # information over vanity items (no "create a business page" here).
    def profile_completion(self):
        """Returns (percent: int, missing: list[str]) — each check is worth
        an equal share of the total."""
        checks = [
            (self.has_custom_picture, 'Add a profile photo'),
            (bool(self.full_name or (self.user.first_name if self.user_id else '')), 'Add your name'),
            (bool(self.member_type_headline_value or self.profession), 'Add a headline'),
            (bool(self.location), 'Add your location'),
            (bool(self.bio or self.what_i_do_summary), 'Describe what you do'),
            (bool(self.looking_for), "Add what you're looking for"),
        ]
        # Only count "Add your skills" for member types whose schema actually
        # has a skills field (e.g. not Business Owner) — otherwise those
        # profiles could never reach 100%, and the popup would nudge them
        # toward a field they have no way to fill in.
        if self.skills_schema_field:
            checks.append((bool(self.skills_list), 'Add your skills'))
        if self.show_experience or self.show_education:
            has_exp_or_edu = self.experiences.exists() or self.education_history.exists()
            checks.append((has_exp_or_edu, 'Add your experience or education'))

        done = sum(1 for ok, _ in checks if ok)
        pct = round(done * 100 / len(checks)) if checks else 0
        missing = [label for ok, label in checks if not ok][:3]
        return pct, missing

    @property
    def is_professional(self):
        """True once the user has picked a member type / profession —
        i.e. their profile has something to show in the Professional tab."""
        return bool(self.member_type or self.profession)

    @property
    def show_products(self):
        return bool(self.sells_products)

    @property
    def show_experience(self):
        return 'experience' in (self.enabled_sections or [])

    @property
    def show_education(self):
        return 'education' in (self.enabled_sections or [])

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
    def experience_count(self):
        return self.experiences.count()

    @property
    def education_count(self):
        return self.education_history.count()

    @property
    def service_count(self):
        return self.services.count()

    @property
    def portfolio_count(self):
        return self.portfolio_items.filter(kind=ProfilePortfolioItem.KIND_PORTFOLIO).count()

    @property
    def project_count(self):
        return self.portfolio_items.filter(kind=ProfilePortfolioItem.KIND_PROJECT).count()

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

    # ── Intent signal — "Looking for Job" / "Hiring" / "Looking for
    #    Clients/Work" — derived from member_type, used both as a feed
    #    badge and as a ranking boost (employer <-> professional matching,
    #    job-seeker <-> job matching). ───────────────────────────────────
    INTENT_LOOKING_FOR_JOB     = 'looking_for_job'
    INTENT_HIRING              = 'hiring'
    INTENT_LOOKING_FOR_CLIENTS = 'looking_for_clients'
    INTENT_LABELS = {
        INTENT_LOOKING_FOR_JOB:     'Looking for Job',
        INTENT_HIRING:              'Hiring',
        INTENT_LOOKING_FOR_CLIENTS: 'Looking for Clients/Work',
    }
    INTENT_BY_MEMBER_TYPE = {
        'job_seeker':           INTENT_LOOKING_FOR_JOB,
        'student_apprentice':   INTENT_LOOKING_FOR_JOB,
        'employer_recruiter':   INTENT_HIRING,
        'business_owner':       INTENT_HIRING,
        'freelancer':           INTENT_LOOKING_FOR_CLIENTS,
        'skilled_professional': INTENT_LOOKING_FOR_CLIENTS,
        'artisan_technician':   INTENT_LOOKING_FOR_CLIENTS,
        'service_provider':     INTENT_LOOKING_FOR_CLIENTS,
        'teacher_tutor':        INTENT_LOOKING_FOR_CLIENTS,
    }

    @property
    def intent(self):
        """'looking_for_job' / 'hiring' / 'looking_for_clients', or '' when
        this member type carries no clear intent."""
        return self.INTENT_BY_MEMBER_TYPE.get(self.member_type, '')

    @property
    def intent_label(self):
        return self.INTENT_LABELS.get(self.intent, '')

    # ── Granular feed-ranking signals ───────────────────────────────────
    # feed_keywords/feed_location_tokens above are a flat bag used for
    # generic content (posts, achievements, portfolio). Type-specific
    # ranking (jobs, people/services) needs each signal on its own so it
    # can be weighted individually — pulled straight out of
    # member_type_data, whichever onboarding schema the user filled in.
    @property
    def skills_tokens(self):
        tokens = set()
        for skill in self.skills_list:
            tokens |= self._tokenize(skill)
        return tokens

    @property
    def desired_job_tokens(self):
        raw = (self.get_member_type_value('desired_job')
               or self.get_member_type_value('trade')
               or self.get_member_type_value('service_type')
               or self.get_member_type_value('subjects'))
        return self._tokenize(raw)

    @property
    def work_mode_pref(self):
        return (self.get_member_type_value('work_mode') or '').strip().lower()

    @property
    def salary_tokens(self):
        raw = (self.get_member_type_value('expected_salary')
               or self.get_member_type_value('rate')
               or self.get_member_type_value('pricing'))
        return self._tokenize(raw)

    @property
    def experience_tokens(self):
        raw = self.get_member_type_value('years_experience') or self.get_member_type_value('experience')
        return self._tokenize(raw)

    @property
    def hiring_for_tokens(self):
        """What an employer/recruiter or business owner is hiring for —
        matched against job-seeker/professional skills for employer ->
        professional suggestions."""
        raw = self.get_member_type_value('hiring_for') or self.get_member_type_value('products_services')
        return self._tokenize(raw)

    # ── Explicit "What I'm Looking For" signal ──────────────────────────
    # `looking_for` (see LOOKING_FOR_SCHEMA) is a short list of keys the
    # user explicitly picked — a stronger, self-declared intent than the
    # member_type-derived `intent` above. Bucketed into the same three
    # broad directions (job / hiring / clients) plus a catch-all
    # collaboration bucket, and a token bag for matching the keys' label
    # text against job/post/candidate content the same way skills_tokens
    # does. Feed scorers weight this above the coarser `intent` signal.
    LOOKING_FOR_JOB_KEYS = {
        'job', 'jobs', 'internship', 'entry_level_jobs', 'teaching_jobs',
        'freelance_work', 'mentorship',
    }
    LOOKING_FOR_HIRING_KEYS = {'hiring', 'candidates'}
    LOOKING_FOR_CLIENT_KEYS = {'clients', 'customers', 'students', 'students_customers'}
    LOOKING_FOR_COLLAB_KEYS = {
        'collaboration', 'partnerships', 'investors', 'business_opportunities',
        'opportunities',
    }

    @property
    def looking_for_tokens(self):
        tokens = set()
        for key in (self.looking_for or []):
            tokens |= self._tokenize(LOOKING_FOR_LABELS.get(key, key))
        return tokens

    @property
    def looking_for_wants_job(self):
        return bool(set(self.looking_for or []) & self.LOOKING_FOR_JOB_KEYS)

    @property
    def looking_for_wants_hiring(self):
        return bool(set(self.looking_for or []) & self.LOOKING_FOR_HIRING_KEYS)

    @property
    def looking_for_wants_clients(self):
        return bool(set(self.looking_for or []) & self.LOOKING_FOR_CLIENT_KEYS)

    @property
    def looking_for_wants_collab(self):
        return bool(set(self.looking_for or []) & self.LOOKING_FOR_COLLAB_KEYS)


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
      - 'new_comment'  → sent to the page owner when someone comments on a post.
      - 'new_vibe'     → sent to the page owner when someone reacts to a post.
    Kept separate from FollowNotification (which is strictly for personal
    profile follows) since a BusinessPage can have many followers and many
    products, and a single user can trigger many of these over time.
    """
    NEW_FOLLOWER = 'new_follower'
    NEW_PRODUCT  = 'new_product'
    NEW_COMMENT  = 'new_comment'
    NEW_VIBE     = 'new_vibe'
    NOTIF_TYPE_CHOICES = [
        (NEW_FOLLOWER, 'New page follower'),
        (NEW_PRODUCT,  'New product'),
        (NEW_COMMENT,  'New comment on a post'),
        (NEW_VIBE,     'New reaction on a post'),
    ]

    notif_type    = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    business_page = models.ForeignKey(
        'BusinessPage', on_delete=models.CASCADE, related_name='notifications'
    )
    # actor: the user who triggered the notification —
    #   the follower for 'new_follower', the page owner for 'new_product',
    #   the commenter/reactor for 'new_comment'/'new_vibe'.
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
        help_text='Set for new_comment / new_vibe notifications only.'
    )
    vibe_type = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Set for new_vibe notifications only (e.g. "fire", "love").'
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
        if self.notif_type == self.NEW_COMMENT:
            return f"{self.actor.username} commented on {self.business_page.name}'s post"
        if self.notif_type == self.NEW_VIBE:
            return f"{self.actor.username} vibed {self.vibe_type} on {self.business_page.name}'s post"
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

    class Meta:
        indexes = [
            # Conversation thread + "recent DM partners" queries filter by
            # one side of the pair and sort by created_at — this table grows
            # unbounded, so a compound index on both directions matters.
            models.Index(fields=['sender', 'receiver', '-created_at'], name='message_sender_recv_idx'),
            models.Index(fields=['receiver', 'sender', '-created_at'], name='message_recv_sender_idx'),
            # Unread-count badge queries.
            models.Index(fields=['receiver', 'is_read'], name='message_recv_unread_idx'),
        ]

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

    class Meta:
        # Every channel-history read filters by channel and orders by
        # created_at (most recent first for the initial page, ascending
        # for scrollback) — this table has no bound on growth for a
        # long-lived channel, so this composite index is what keeps the
        # `channel()` view's "most recent 50" query an index scan instead
        # of a sequential scan + sort as history grows into the millions.
        indexes = [
            models.Index(fields=['channel', '-created_at'], name='chanmsg_channel_created_idx'),
        ]

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

    class Meta:
        indexes = [
            # Category browse pages filter by category and sort by recency —
            # this was a full-table scan sorted at read time; now index-only.
            models.Index(fields=['product_category', '-posted_on'], name='market_cat_posted_idx'),
            # Home/marketplace feed candidate pool ordering.
            models.Index(fields=['-posted_on'], name='market_posted_idx'),
            models.Index(fields=['product_owner', '-posted_on'], name='market_owner_posted_idx'),
            # Trigram indexes so `icontains` search on these fields uses an
            # index instead of a sequential scan once the table has millions
            # of rows. Requires the Postgres pg_trgm extension — see the
            # migration note in SCALABILITY_AUDIT.md.
            GinIndex(fields=['product_name'], name='market_name_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['product_description'], name='market_desc_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['product_location'], name='market_loc_trgm', opclasses=['gin_trgm_ops']),
        ]

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
        indexes = [
            models.Index(fields=['is_cancelled', 'date'], name='event_active_date_idx'),
            GinIndex(fields=['title'], name='event_title_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['description'], name='event_desc_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['location'], name='event_loc_trgm', opclasses=['gin_trgm_ops']),
        ]

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

# ── Requestable applicant documents ─────────────────────────────────────────
# Shared by JobVacancy (what the poster asks for) and JobApplicationDocument
# (what the applicant actually attaches). Keeping this as an explicit,
# selective list — rather than a free-for-all "attach anything" uploader —
# means a poster picks exactly which results/certificates they need, and an
# applicant sees a clearly labelled slot for each one.
JOB_DOCUMENT_TYPE_CHOICES = [
    ('waec',                   'WAEC Result'),
    ('neco',                   'NECO Result'),
    ('nabteb',                 'NABTEB Result'),
    ('degree_certificate',     'Degree Certificate'),
    ('hnd_nd_certificate',     'HND / ND Certificate'),
    ('nysc_certificate',       'NYSC Certificate'),
    ('birth_certificate',      'Birth Certificate'),
    ('international_passport', 'International Passport'),
    ('other',                  'Other Certificate / Document'),
]
JOB_DOCUMENT_TYPE_VALUES = [c[0] for c in JOB_DOCUMENT_TYPE_CHOICES]
JOB_DOCUMENT_TYPE_LABELS = dict(JOB_DOCUMENT_TYPE_CHOICES)


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
    required_documents = models.CharField(
        max_length=255, blank=True, default='',
        help_text=(
            'Comma-separated codes for the specific results/certificates this '
            'poster wants applicants to attach (e.g. "waec,neco,degree_certificate"). '
            'Valid codes come from JOB_DOCUMENT_TYPE_CHOICES.'
        ),
    )
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
        indexes = [
            # Open-jobs listing sorted by recency — the common browse query.
            models.Index(fields=['is_open', '-created_at'], name='job_open_created_idx'),
            GinIndex(fields=['title'], name='job_title_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['description'], name='job_desc_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['location'], name='job_loc_trgm', opclasses=['gin_trgm_ops']),
        ]

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

        # Keep only recognised, de-duplicated document codes — this field
        # drives which upload slots show up on the application modal, so it
        # must never contain arbitrary/unsanitised text.
        if self.required_documents:
            codes = [c.strip() for c in self.required_documents.split(',') if c.strip()]
            seen = []
            for code in codes:
                if code in JOB_DOCUMENT_TYPE_VALUES and code not in seen:
                    seen.append(code)
            self.required_documents = ','.join(seen)

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

    # ── Requested-documents helpers ─────────────────────────────────────────
    @property
    def required_documents_list(self):
        """Ordered list of valid document codes this poster is requesting."""
        if not self.required_documents:
            return []
        codes = [c.strip() for c in self.required_documents.split(',') if c.strip()]
        return [c for c in codes if c in JOB_DOCUMENT_TYPE_VALUES]

    @property
    def required_documents_display(self):
        """[(code, label), ...] for the requested document codes — used to
        render one selective upload slot per requested document."""
        return [(code, JOB_DOCUMENT_TYPE_LABELS.get(code, code)) for code in self.required_documents_list]


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
# JobApplication — a job seeker's application to a JobVacancy
# =============================================================================

class JobApplication(models.Model):
    """
    One application by `applicant` to `job`. A user may only have a single
    application per job (enforced by unique_together below) — withdrawing
    keeps the row (status becomes WITHDRAWN) instead of deleting it, so the
    "applied once" rule holds even after a withdrawal.
    """

    APPLIED       = 'applied'
    UNDER_REVIEW  = 'under_review'
    SHORTLISTED   = 'shortlisted'
    INTERVIEW     = 'interview'
    SELECTED      = 'selected'
    REJECTED      = 'rejected'
    WITHDRAWN     = 'withdrawn'

    STATUS_CHOICES = [
        (APPLIED,      'Applied'),
        (UNDER_REVIEW, 'Under Review'),
        (SHORTLISTED,  'Shortlisted'),
        (INTERVIEW,    'Interview'),
        (SELECTED,     'Selected'),
        (REJECTED,     'Rejected'),
        (WITHDRAWN,    'Withdrawn'),
    ]

    # Statuses an employer is allowed to move an application *into* via the
    # status-change endpoint. WITHDRAWN is applicant-only (via withdraw());
    # employers can't "un-withdraw" or set it directly.
    EMPLOYER_SETTABLE_STATUSES = {
        UNDER_REVIEW, SHORTLISTED, INTERVIEW, SELECTED, REJECTED,
    }

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job        = models.ForeignKey(JobVacancy, on_delete=models.CASCADE, related_name='applications')
    applicant  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_applications')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=APPLIED, db_index=True)

    cover_letter        = models.TextField()
    portfolio_link       = models.URLField(max_length=500, blank=True, default='')
    additional_message   = models.TextField(blank=True, default='')

    if settings.USE_CLOUDINARY:
        resume = CloudinaryField(
            'raw', resource_type='raw', folder='job_applications/resumes',
            blank=True, null=True,
        )
    else:
        resume = models.FileField(upload_to='job_applications/resumes/', blank=True, null=True)
    resume_name = models.CharField(max_length=255, blank=True, default='')

    applied_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'JobApplication_Table'
        ordering = ['-applied_at']
        unique_together = ('job', 'applicant')
        indexes = [
            models.Index(fields=['job', 'status']),
            models.Index(fields=['applicant', 'status']),
        ]

    def __str__(self):
        return f'{self.applicant.username} → {self.job.title} [{self.get_status_display()}]'

    def clean(self):
        super().clean()
        self.cover_letter      = sanitize_text(self.cover_letter, 'product_description')
        self.additional_message = sanitize_text(self.additional_message, 'product_description')
        self.resume_name       = sanitize_text(self.resume_name)

        if self.portfolio_link:
            try:
                self.portfolio_link = validate_url(self.portfolio_link)
            except ValidationError:
                self.portfolio_link = ''

        valid_statuses = [c[0] for c in self.STATUS_CHOICES]
        if self.status not in valid_statuses:
            self.status = self.APPLIED

        # Same _committed guard used on Profile.member_type_cv — only
        # re-validate the file when a *new* upload is attached this
        # request, not on every unrelated save (status changes etc).
        if self.resume and hasattr(self.resume, 'name') and hasattr(self.resume, '_committed'):
            if not self.resume._committed:
                validate_cv_extension(self.resume)
                validate_file_size(self.resume, max_size_mb=5)

    def save(self, *args, **kwargs):
        self.full_clean(exclude=['resume'])
        if self.resume and hasattr(self.resume, '_committed') and not self.resume._committed:
            validate_cv_extension(self.resume)
            validate_file_size(self.resume, max_size_mb=5)
        super().save(*args, **kwargs)

    def withdraw(self):
        self.status = self.WITHDRAWN
        self.status_updated_at = timezone.now()
        self.save(update_fields=['status', 'status_updated_at', 'updated_at'])

    @property
    def is_active(self):
        return self.status not in (self.WITHDRAWN, self.REJECTED)

    @property
    def status_emoji(self):
        return {
            self.APPLIED:      '📨',
            self.UNDER_REVIEW: '🔍',
            self.SHORTLISTED:  '⭐',
            self.INTERVIEW:    '🗣️',
            self.SELECTED:     '✅',
            self.REJECTED:     '❌',
            self.WITHDRAWN:    '↩️',
        }.get(self.status, '📨')

    @property
    def status_color(self):
        return {
            self.APPLIED:      '#0095f6',
            self.UNDER_REVIEW: '#b45309',
            self.SHORTLISTED:  '#7c3aed',
            self.INTERVIEW:    '#0f766e',
            self.SELECTED:     '#16a34a',
            self.REJECTED:     '#e03131',
            self.WITHDRAWN:    '#64748b',
        }.get(self.status, '#0095f6')

    @property
    def resume_url(self):
        return self.resume.url if self.resume else ''


# =============================================================================
# JobApplicationDocument — one requested certificate/result attached by the
# applicant (WAEC, NECO, degree certificate, etc). Kept as its own row per
# document — rather than a single generic attachment — so the poster's
# selective list of requested documents maps to individually labelled,
# individually viewable files on the employer's side.
# =============================================================================

class JobApplicationDocument(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, related_name='documents')

    doc_type  = models.CharField(max_length=30, choices=JOB_DOCUMENT_TYPE_CHOICES)
    # Only used when doc_type == 'other' — the applicant's own label for
    # whatever extra certificate they've attached (e.g. "Driving Licence").
    doc_label = models.CharField(max_length=100, blank=True, default='')

    if settings.USE_CLOUDINARY:
        file = CloudinaryField(
            'raw', resource_type='raw', folder='job_applications/documents',
            blank=True, null=True,
        )
    else:
        file = models.FileField(upload_to='job_applications/documents/', blank=True, null=True)
    original_name = models.CharField(max_length=255, blank=True, default='')

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'JobApplicationDocument_Table'
        ordering = ['doc_type', 'uploaded_at']

    def __str__(self):
        return f'{self.application.applicant.username} — {self.display_label}'

    def clean(self):
        super().clean()
        self.doc_label     = sanitize_text(self.doc_label)
        self.original_name = sanitize_text(self.original_name)

        if self.doc_type not in JOB_DOCUMENT_TYPE_VALUES:
            raise ValidationError('Invalid document type.')

        if self.file and hasattr(self.file, 'name') and hasattr(self.file, '_committed'):
            if not self.file._committed:
                validate_certificate_extension(self.file)
                validate_file_size(self.file, max_size_mb=5)

    def save(self, *args, **kwargs):
        self.full_clean(exclude=['file'])
        if self.file and hasattr(self.file, '_committed') and not self.file._committed:
            validate_certificate_extension(self.file)
            validate_file_size(self.file, max_size_mb=5)
        super().save(*args, **kwargs)

    @property
    def display_label(self):
        if self.doc_type == 'other' and self.doc_label:
            return self.doc_label
        return JOB_DOCUMENT_TYPE_LABELS.get(self.doc_type, self.doc_type)

    @property
    def file_url(self):
        return self.file.url if self.file else ''


# =============================================================================
# JobApplicationNotification — notifications for the apply/status pipeline
# =============================================================================

class JobApplicationNotification(models.Model):
    """
    Notifications tied to a JobApplication:
      - 'applied'         → sent to the job owner when someone applies.
      - 'status_changed'  → sent to the applicant whenever the employer
                              changes the application status (includes
                              shortlisted / interview / selected / rejected).
      - 'withdrawn'       → sent to the job owner when an applicant withdraws.
    """
    APPLIED         = 'applied'
    STATUS_CHANGED  = 'status_changed'
    WITHDRAWN       = 'withdrawn'
    NOTIF_TYPE_CHOICES = [
        (APPLIED,        'New application'),
        (STATUS_CHANGED, 'Application status changed'),
        (WITHDRAWN,      'Application withdrawn'),
    ]

    notif_type  = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, related_name='notifications')
    actor       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_job_application_notifications')
    to_user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_application_notifications')
    old_status  = models.CharField(max_length=20, blank=True, default='')
    new_status  = models.CharField(max_length=20, blank=True, default='')
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'JobApplicationNotification_Table'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['to_user', 'is_read']),
            models.Index(fields=['application', 'notif_type']),
        ]

    def __str__(self):
        if self.notif_type == self.APPLIED:
            return f'{self.actor.username} applied for {self.application.job.title}'
        if self.notif_type == self.WITHDRAWN:
            return f'{self.actor.username} withdrew from {self.application.job.title}'
        return f'{self.application.job.title} status → {self.get_new_status_display() if self.new_status else self.new_status}'


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
        ('services',     'Professional Services'),
        ('agriculture',  'Agriculture & Farming'),
        ('logistics',    'Logistics & Delivery'),
        ('education',    'Education & Training'),
        ('others',       'Others'),
    ]

    # Payment methods commonly accepted by Nigerian SMEs — stored as a plain
    # list on `payment_methods`, e.g. ["cash", "transfer", "pos"].
    PAYMENT_METHOD_CHOICES = [
        ('cash',     'Cash'),
        ('transfer', 'Bank Transfer'),
        ('pos',      'POS'),
        ('card',     'Card'),
    ]
    VALID_PAYMENT_METHODS = {p[0] for p in PAYMENT_METHOD_CHOICES}

    page_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_pages')
    name        = models.CharField(max_length=150)
    slug        = models.SlugField(max_length=160, unique=True)
    category    = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='others')
    # Products are opt-in: only businesses that actually sell physical or
    # digital products should see the Products tab & be able to post Market
    # listings from this page.
    sells_products   = models.BooleanField(default=True)
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
    telegram    = models.CharField(max_length=100, blank=True, default='',
                                   help_text='Username or @handle')
    followers   = models.ManyToManyField(User, blank=True, related_name='followed_business_pages')
    is_verified = models.BooleanField(default=False)
    is_active   = models.BooleanField(default=True)

    # ── Business hours (simplified) ──────────────────────────────────────────
    # A single open/close time applies every day, unless the page is open
    # around the clock. Empty open_time/close_time means hours haven't been
    # set for this page yet.
    open_time  = models.CharField(max_length=10, blank=True, default='09:00')
    close_time = models.CharField(max_length=10, blank=True, default='18:00')
    is_24hrs   = models.BooleanField(default=False)

    # ── Nigerian-specific business details ───────────────────────────────────
    registration_number = models.CharField(max_length=20, blank=True, default='',
                                   help_text='RC Number or BN')
    delivery_available = models.BooleanField(default=False)
    pickup_available   = models.BooleanField(default=True)
    payment_methods    = models.JSONField(default=list, blank=True,
                                   help_text='Cash, Transfer, POS, etc.')

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
        indexes = [
            models.Index(fields=['is_active', 'category', '-created_at'], name='bizpage_active_cat_idx'),
            GinIndex(fields=['name'], name='bizpage_name_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['description'], name='bizpage_desc_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['location'], name='bizpage_loc_trgm', opclasses=['gin_trgm_ops']),
        ]

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
        if self.telegram:
            self.telegram = re.sub(r'[^a-zA-Z0-9._]', '', self.telegram.lstrip('@').strip())[:100]
        self.registration_number = re.sub(r'[^a-zA-Z0-9/\-]', '', (self.registration_number or '').strip())[:20]
        self.open_time, self.close_time = self._sanitize_hours(self.open_time, self.close_time)
        self.payment_methods = self._sanitize_payment_methods(self.payment_methods)

    @classmethod
    def _sanitize_payment_methods(cls, raw):
        """Keep only known, deduplicated payment-method keys."""
        if not isinstance(raw, (list, tuple, set)):
            return []
        seen = []
        for key in raw:
            key = str(key).strip()
            if key in cls.VALID_PAYMENT_METHODS and key not in seen:
                seen.append(key)
        return seen

    @classmethod
    def _sanitize_hours(cls, open_v, close_v):
        """Keep open/close as valid HH:MM strings, falling back to defaults."""
        time_re = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
        open_v = str(open_v or '').strip()
        close_v = str(close_v or '').strip()
        if not time_re.match(open_v):
            open_v = '09:00'
        if not time_re.match(close_v):
            close_v = '18:00'
        return open_v, close_v

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

    # ── Business hours helpers (simplified) ──────────────────────────────────
    @property
    def is_open_now(self):
        """True = open, False = closed. 24hrs pages are always open."""
        if self.is_24hrs:
            return True
        try:
            open_t  = datetime.strptime(self.open_time,  '%H:%M').time()
            close_t = datetime.strptime(self.close_time, '%H:%M').time()
        except (ValueError, TypeError):
            return None
        now_t = timezone.localtime().time()
        if open_t <= close_t:
            return open_t <= now_t <= close_t
        # Overnight hours, e.g. 18:00 → 02:00
        return now_t >= open_t or now_t <= close_t

    @property
    def operating_hours_display(self):
        """Simple display string, e.g. 'Open 24 Hours' or '9:00 AM - 6:00 PM'."""
        if self.is_24hrs:
            return 'Open 24 Hours'

        def _fmt(t):
            try:
                return datetime.strptime(t, '%H:%M').strftime('%-I:%M %p')
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(t, '%H:%M').strftime('%I:%M %p').lstrip('0')
                except (ValueError, TypeError):
                    return t
        return f'{_fmt(self.open_time)} - {_fmt(self.close_time)}'

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

    # ── Direct business reviews (BusinessReview) — customers rating the
    # business itself, independent of any single product purchase ─────────
    @property
    def business_review_average_rating(self):
        result = self.reviews.aggregate(avg=models.Avg('rating'))['avg']
        return round(result, 1) if result else 0

    @property
    def business_review_count(self):
        return self.reviews.count()

    # ── Combined rating shown in the page header — blends direct business
    # reviews with per-product reviews so a page with either (or both) still
    # shows one clear trust signal. ─────────────────────────────────────────
    @property
    def overall_review_count(self):
        return self.business_review_count + self.review_count

    @property
    def overall_average_rating(self):
        biz_avg  = self.business_review_average_rating
        biz_n    = self.business_review_count
        prod_avg = self.average_rating
        prod_n   = self.review_count
        total = biz_n + prod_n
        if not total:
            return 0
        weighted = (biz_avg * biz_n) + (prod_avg * prod_n)
        return round(weighted / total, 1)

    @property
    def post_count(self):
        return self.posts.count()

    # ── Trust & verification signals shown in the header/About section ────
    @property
    def has_verified_contact(self):
        return bool(self.phone or self.email)

    # ── Business page sections ───────────────────────────────────────────────
    # Services and Jobs are always available — no per-page toggle needed.
    @property
    def show_products(self):
        return bool(self.sells_products)

    @property
    def show_services(self):
        return True

    @property
    def show_jobs_section(self):
        return True

    @property
    def service_count(self):
        return self.services.count()

    @property
    def payment_methods_display(self):
        labels = dict(self.PAYMENT_METHOD_CHOICES)
        return [labels.get(m, m) for m in (self.payment_methods or [])]


# ─────────────────────────────────────────────────────────────────────────────
# Optional professional-page sections — Services, Portfolio/Projects,
# Achievements. Jobs already exist via JobVacancy.business_page and Products
# via Market.business_page, so no new models are needed for those two.
# ─────────────────────────────────────────────────────────────────────────────

class BusinessService(models.Model):
    """A service offered by a BusinessPage — e.g. 'Logo design', 'AC repair',
    'Home tutoring'. Shown in the optional Services section. Business-page
    owned only — see ProfileService for the equivalent on a user's own
    Profile; the two are entirely independent."""
    service_id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='services')
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
        return f'{self.title} — {self.business_page.name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.description = sanitize_text(self.description, 'about')
        self.price_text  = sanitize_text(self.price_text)
        if not self.title:
            raise ValidationError({'title': 'Service title is required.'})

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
        return self.business_page

    @property
    def owner_user(self):
        return self.business_page.owner

    @property
    def owner_name(self):
        return self.business_page.name


class ProfileService(models.Model):
    """A service offered directly from a user's own Profile — e.g. 'Logo
    design', 'AC repair', 'Home tutoring'. Shown in the optional Services
    section. Profile-owned only, entirely independent of BusinessPage/
    BusinessService."""
    service_id  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile     = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='services')
    title       = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    price_text  = models.CharField(max_length=150, blank=True, default='',
                                    help_text='e.g. ₦15,000, Starting from ₦5,000/hr, or Negotiable')

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_service_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_service_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProfileService_Table'
        ordering = ['order', '-created_at']

    def __str__(self):
        return f'{self.title} — {self.owner_name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.description = sanitize_text(self.description, 'about')
        self.price_text  = sanitize_text(self.price_text)
        if not self.title:
            raise ValidationError({'title': 'Service title is required.'})

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
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user

    @property
    def owner_name(self):
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
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='portfolio_items')
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
        return self.business_page

    @property
    def owner_user(self):
        return self.business_page.owner

    @property
    def gallery_urls(self):
        """Cover image (if any) followed by every extra gallery image —
        used to render a multi-image portfolio/project showcase."""
        urls = []
        if self.get_image_url:
            urls.append(self.get_image_url)
        urls.extend(img.get_image_url for img in self.extra_images.all() if img.get_image_url)
        return urls

    @property
    def image_count(self):
        return len(self.gallery_urls)


class BusinessPortfolioImage(models.Model):
    """An additional photo within a Portfolio piece or Project — supports
    showcasing completed work with multiple images alongside the item's
    single cover `image`."""
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item     = models.ForeignKey(BusinessPortfolioItem, on_delete=models.CASCADE, related_name='extra_images')
    order    = models.PositiveSmallIntegerField(default=0)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='business_portfolio_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='business_portfolio_images/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'BusinessPortfolioImage_Table'
        ordering = ['order', 'created_at']

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
            return self.image.url if self.image else ''
        except Exception:
            return ''


class ProfilePortfolioItem(models.Model):
    """A single Portfolio piece or Project shown directly on a user's own
    Profile. Same shape as BusinessPortfolioItem but Profile-owned only,
    entirely independent of BusinessPage."""
    KIND_PORTFOLIO = 'portfolio'
    KIND_PROJECT   = 'project'
    KIND_CHOICES = [
        (KIND_PORTFOLIO, 'Portfolio piece'),
        (KIND_PROJECT,   'Project'),
    ]

    item_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile     = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='portfolio_items')
    kind        = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_PORTFOLIO, db_index=True)
    title       = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    link_url    = models.URLField(max_length=500, blank=True, default='')
    is_ongoing  = models.BooleanField(default=False, help_text='Only meaningful for projects.')

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_portfolio_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_portfolio_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProfilePortfolioItem_Table'
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
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user

    @property
    def vibe_count(self):
        return self.vibes.count()

    @property
    def comment_count(self):
        return self.comments.count()

    @property
    def top_vibe_emoji(self):
        row = self.vibes.values('vibe_type').annotate(cnt=models.Count('id')).order_by('-cnt').first()
        return ProfilePostVibe.VIBE_EMOJIS.get(row['vibe_type'], '') if row else ''


class ProfileExperience(models.Model):
    """A single work-history entry (role at a company) shown on a user's own
    Profile, LinkedIn-style — with an optional company logo image."""
    EMPLOYMENT_FULL_TIME = 'full_time'
    EMPLOYMENT_PART_TIME = 'part_time'
    EMPLOYMENT_INTERNSHIP = 'internship'
    EMPLOYMENT_FREELANCE = 'freelance'
    EMPLOYMENT_CONTRACT = 'contract'
    EMPLOYMENT_VOLUNTEER = 'volunteer'
    EMPLOYMENT_TYPE_CHOICES = [
        (EMPLOYMENT_FULL_TIME,  'Full-time'),
        (EMPLOYMENT_PART_TIME,  'Part-time'),
        (EMPLOYMENT_INTERNSHIP, 'Internship'),
        (EMPLOYMENT_FREELANCE,  'Freelance'),
        (EMPLOYMENT_CONTRACT,   'Contract'),
        (EMPLOYMENT_VOLUNTEER,  'Volunteer'),
    ]

    experience_id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile         = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='experiences')
    title           = models.CharField(max_length=150, help_text='Role / position, e.g. Software Engineer Intern')
    company_name    = models.CharField(max_length=150)
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, blank=True, default='')
    location        = models.CharField(max_length=150, blank=True, default='')
    description     = models.TextField(blank=True, default='')
    start_date      = models.DateField(blank=True, null=True)
    end_date        = models.DateField(blank=True, null=True)
    is_current      = models.BooleanField(default=False)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_experience_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_experience_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProfileExperience_Table'
        ordering = ['order', '-is_current', '-start_date', '-created_at']

    def __str__(self):
        return f'{self.title} @ {self.company_name}'

    def clean(self):
        super().clean()
        self.title        = sanitize_text(self.title)
        self.company_name = sanitize_text(self.company_name)
        self.location      = sanitize_text(self.location)
        self.description   = sanitize_text(self.description, 'about')
        if self.employment_type not in dict(self.EMPLOYMENT_TYPE_CHOICES) and self.employment_type:
            self.employment_type = ''
        if not self.title:
            raise ValidationError({'title': 'Title is required.'})
        if not self.company_name:
            raise ValidationError({'company_name': 'Company name is required.'})
        if self.is_current:
            self.end_date = None

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
    def duration_label(self):
        """e.g. 'Jul 2026 - Present' — mirrors LinkedIn's date-range line."""
        if not self.start_date:
            return ''
        start = self.start_date.strftime('%b %Y')
        end = 'Present' if self.is_current else (self.end_date.strftime('%b %Y') if self.end_date else '')
        return f'{start} - {end}' if end else start

    @property
    def owner(self):
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user


class ProfileEducation(models.Model):
    """A single education entry (school / degree) shown on a user's own
    Profile, LinkedIn-style — with an optional institution logo image."""
    education_id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile          = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='education_history')
    school_name      = models.CharField(max_length=150)
    degree           = models.CharField(max_length=150, blank=True, default='')
    field_of_study   = models.CharField(max_length=150, blank=True, default='')
    grade            = models.CharField(max_length=50, blank=True, default='')
    description      = models.TextField(blank=True, default='')
    start_date       = models.DateField(blank=True, null=True)
    end_date         = models.DateField(blank=True, null=True)
    is_current       = models.BooleanField(default=False)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_education_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_education_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProfileEducation_Table'
        ordering = ['order', '-is_current', '-start_date', '-created_at']

    def __str__(self):
        return f'{self.school_name} — {self.degree}' if self.degree else self.school_name

    def clean(self):
        super().clean()
        self.school_name    = sanitize_text(self.school_name)
        self.degree         = sanitize_text(self.degree)
        self.field_of_study = sanitize_text(self.field_of_study)
        self.grade           = sanitize_text(self.grade)
        self.description     = sanitize_text(self.description, 'about')
        if not self.school_name:
            raise ValidationError({'school_name': 'School / institution name is required.'})
        if self.is_current:
            self.end_date = None

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
    def duration_label(self):
        if not self.start_date and not self.end_date:
            return ''
        start = self.start_date.strftime('%b %Y') if self.start_date else ''
        end = 'Present' if self.is_current else (self.end_date.strftime('%b %Y') if self.end_date else '')
        if start and end:
            return f'{start} - {end}'
        return start or end

    @property
    def owner(self):
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user


class BusinessAchievement(models.Model):
    """A certification, award, or milestone shown on a professional page."""
    achievement_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page  = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='achievements')
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
        return f'{self.title} — {self.business_page.name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.issuer      = sanitize_text(self.issuer)
        self.description = sanitize_text(self.description, 'about')
        if not self.title:
            raise ValidationError({'title': 'Achievement title is required.'})

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
        return self.business_page

    @property
    def owner_user(self):
        return self.business_page.owner

    @property
    def owner_name(self):
        return self.business_page.name


class BusinessReview(models.Model):
    """A star rating + written review left by a customer directly on a
    BusinessPage (as opposed to ProductReview, which is scoped to a single
    Market listing). One review per (business_page, user) — the reviewer can
    edit their own, and the page owner can post a single public reply."""
    RATING_CHOICES = [
        (1, '1 – Poor'),
        (2, '2 – Fair'),
        (3, '3 – Good'),
        (4, '4 – Very Good'),
        (5, '5 – Excellent'),
    ]

    review_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='reviews')
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_page_reviews')
    rating        = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment       = models.TextField(max_length=2000, blank=True, default='')
    is_edited     = models.BooleanField(default=False)

    owner_reply    = models.TextField(max_length=2000, blank=True, default='')
    owner_reply_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'BusinessReview_Table'
        ordering = ['-created_at']
        unique_together = ('business_page', 'user')
        indexes = [
            models.Index(fields=['business_page', '-created_at'], name='bizreview_page_time_idx'),
        ]

    def __str__(self):
        return f'{self.user.username} rated {self.business_page.name} {self.rating}★'

    def clean(self):
        super().clean()
        self.comment = sanitize_text(self.comment, 'comment')
        self.owner_reply = sanitize_text(self.owner_reply, 'comment')
        if self.rating not in dict(self.RATING_CHOICES):
            raise ValidationError({'rating': 'Rating must be between 1 and 5.'})
        if self.business_page_id and self.business_page.owner_id == self.user_id:
            raise ValidationError('You cannot review your own business page.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def star_range(self):
        return range(1, 6)

    @property
    def has_owner_reply(self):
        return bool(self.owner_reply)


class ProfileAchievement(models.Model):
    """A certification, award, or milestone shown directly on a user's own
    Profile. Profile-owned only, entirely independent of BusinessPage."""
    achievement_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile        = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='achievements')
    title          = models.CharField(max_length=150)
    issuer         = models.CharField(max_length=150, blank=True, default='')
    description    = models.TextField(blank=True, default='')
    date_achieved  = models.DateField(blank=True, null=True)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_achievement_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_achievement_images/', blank=True, null=True)

    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ProfileAchievement_Table'
        ordering = ['order', '-date_achieved', '-created_at']

    def __str__(self):
        return f'{self.title} — {self.owner_name}'

    def clean(self):
        super().clean()
        self.title       = sanitize_text(self.title)
        self.issuer      = sanitize_text(self.issuer)
        self.description = sanitize_text(self.description, 'about')
        if not self.title:
            raise ValidationError({'title': 'Achievement title is required.'})

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
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user

    @property
    def owner_name(self):
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

    Business-page owned only — see ProfilePost for the equivalent posted
    straight from a user's own Profile; the two are entirely independent.
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
    business_page = models.ForeignKey(BusinessPage, on_delete=models.CASCADE, related_name='posts')
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
        return f'{self.get_post_type_display()} post by {self.business_page.name}'

    def clean(self):
        super().clean()
        if self.post_type not in dict(self.POST_TYPE_CHOICES):
            raise ValidationError({'post_type': 'Invalid post type.'})
        if self.post_category not in dict(self.POST_CATEGORY_CHOICES):
            self.post_category = self.CATEGORY_UPDATE
        self.caption = sanitize_text(self.caption, 'post_caption')

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
        return self.business_page

    @property
    def owner_user(self):
        return self.business_page.owner

    @property
    def owner_name(self):
        return self.business_page.name

    @property
    def owner_picture_url(self):
        return self.business_page.get_logo_url

    @property
    def owner_url_kwargs(self):
        return {'type': 'page', 'slug': self.business_page.slug}


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


# ─────────────────────────────────────────────────────────────────────────────
# ProfilePost — image / video / text / poll updates posted directly from a
# user's own Profile. Mirrors BusinessPost field-for-field, but Profile-owned
# only and entirely independent of BusinessPage/BusinessPost — separate
# table, separate sub-models (images, poll, vibes, comments) below.
# ─────────────────────────────────────────────────────────────────────────────

class ProfilePost(models.Model):
    """
    A single update posted directly to a user's own Profile feed. One of
    four kinds:
      - image : one or more photos (see ProfilePostImage), + optional caption
      - video : a single short video (15–90s guideline, enforced client-side),
                + optional caption
      - text  : caption only, no media
      - poll  : caption used as an optional intro line; the actual question and
                options live on the related ProfilePostPoll / ProfilePostPollOption
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
    profile       = models.ForeignKey('Profile', on_delete=models.CASCADE, related_name='professional_posts')
    post_type     = models.CharField(max_length=10, choices=POST_TYPE_CHOICES, default=TYPE_TEXT, db_index=True)
    post_category = models.CharField(max_length=15, choices=POST_CATEGORY_CHOICES, default=CATEGORY_UPDATE, db_index=True)
    caption       = models.TextField(blank=True, default='')

    if settings.USE_CLOUDINARY:
        video = CloudinaryField('video', folder='profile_post_videos', resource_type='video', blank=True, null=True)
    else:
        video = models.FileField(upload_to='profile_post_videos/', blank=True, null=True)

    video_duration_seconds = models.PositiveIntegerField(blank=True, null=True)

    is_pinned  = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ProfilePost_Table'
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
        return ProfilePostVibe.VIBE_EMOJIS.get(row['vibe_type'], '')

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
        return self.profile

    @property
    def owner_user(self):
        return self.profile.user

    @property
    def owner_name(self):
        return self.profile.full_name or self.profile.user.username

    @property
    def owner_picture_url(self):
        return self.profile.get_picture_url

    @property
    def owner_url_kwargs(self):
        return {'type': 'profile', 'username': self.profile.user.username}


class ProfilePostImage(models.Model):
    """One photo within an 'image' type ProfilePost — supports multi-image posts."""
    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post     = models.ForeignKey(ProfilePost, on_delete=models.CASCADE, related_name='images')
    order    = models.PositiveSmallIntegerField(default=0)

    if settings.USE_CLOUDINARY:
        image = CloudinaryField('image', folder='profile_post_images', blank=True, null=True)
    else:
        image = models.ImageField(upload_to='profile_post_images/', blank=True, null=True)

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


class ProfilePostPoll(models.Model):
    """The poll attached to a 'poll' type ProfilePost — one per post."""
    poll_id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post           = models.OneToOneField(ProfilePost, on_delete=models.CASCADE, related_name='poll')
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
        return ProfilePostPollVote.objects.filter(option__poll=self).values('user_id').distinct().count()

    def voted_option_ids(self, user):
        if not user or not user.is_authenticated:
            return set()
        return set(
            ProfilePostPollVote.objects.filter(option__poll=self, user=user)
            .values_list('option_id', flat=True)
        )


class ProfilePostPollOption(models.Model):
    option_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll      = models.ForeignKey(ProfilePostPoll, on_delete=models.CASCADE, related_name='options')
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


class ProfilePostPollVote(models.Model):
    vote_id  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    option   = models.ForeignKey(ProfilePostPollOption, on_delete=models.CASCADE, related_name='votes')
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_poll_votes')
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['option', 'user'], name='unique_vote_per_option_per_user_profile'),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# ProfilePostVibe / ProfilePostComment — reactions & comments on Profile
# posts, mirroring BusinessPostVibe/BusinessPostComment so the existing
# generic _card_vibe_* / _card_comments_* view helpers can be reused.
# ─────────────────────────────────────────────────────────────────────────────

class ProfilePostVibe(models.Model):
    """Vibe reactions on ProfilePost updates. One per user per post."""

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

    post       = models.ForeignKey(ProfilePost, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User,        on_delete=models.CASCADE, related_name='profile_post_vibes')
    vibe_type  = models.CharField(max_length=10, choices=VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')
        ordering = ['created_at']
        db_table = 'ProfilePostVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on post {self.post_id}"


class ProfilePostComment(models.Model):
    """Comments on ProfilePost updates."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post       = models.ForeignKey(ProfilePost, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User,        on_delete=models.CASCADE, related_name='profile_post_comments')
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
        db_table = 'ProfilePostComment_Table'

    def __str__(self):
        return f"{self.author.username} on post {self.post_id}: {self.text[:50]}"


# ─────────────────────────────────────────────────────────────────────────────
# ProfilePostNotification — reaction/comment notifications for personal
# ProfilePost updates, mirroring BusinessNotification's new_comment/new_vibe
# handling but scoped to a user's own profile feed instead of a BusinessPage.
# ─────────────────────────────────────────────────────────────────────────────

class ProfilePostNotification(models.Model):
    """
    Notifications tied to a ProfilePost (a personal profile update):
      - 'new_vibe'    → sent to the post owner when someone reacts to their post.
      - 'new_comment' → sent to the post owner when someone comments on their post.
    A single actor can only have one active 'new_vibe' row per post (their
    reaction is refreshed in place if they change/re-apply it); comments
    always create a fresh row since each comment is a distinct event.
    """
    NEW_VIBE    = 'new_vibe'
    NEW_COMMENT = 'new_comment'
    NOTIF_TYPE_CHOICES = [
        (NEW_VIBE,    'New reaction'),
        (NEW_COMMENT, 'New comment'),
    ]

    notif_type = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    post = models.ForeignKey(
        ProfilePost, on_delete=models.CASCADE, related_name='notifications'
    )
    # actor: the user who reacted or commented.
    actor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_profile_post_notifications'
    )
    # to_user: the post owner — the recipient of the notification.
    to_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='profile_post_notifications'
    )
    vibe_type = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Set for new_vibe notifications only (e.g. "fire", "love").'
    )
    comment = models.ForeignKey(
        ProfilePostComment, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications',
        help_text='Set for new_comment notifications only.'
    )
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ProfilePostNotification_Table'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['to_user', 'is_read']),
            models.Index(fields=['post', 'notif_type']),
        ]

    def __str__(self):
        if self.notif_type == self.NEW_VIBE:
            return f"{self.actor.username} vibed {self.vibe_type} on post {self.post_id}"
        return f"{self.actor.username} commented on post {self.post_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Reactions & comments for the other Profile sub-sections — Portfolio/Projects,
# Achievements, Experience, Education, Services. Same vibe/comment shape as
# ProfilePostVibe/ProfilePostComment (reusing its VIBE_CHOICES/VIBE_EMOJIS) so
# the existing _card_vibe_* / _card_comments_* view helpers work unchanged.
# ─────────────────────────────────────────────────────────────────────────────

class ProfilePortfolioItemVibe(models.Model):
    """Vibe reactions on a ProfilePortfolioItem (portfolio piece or project)."""
    item       = models.ForeignKey(ProfilePortfolioItem, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_portfolio_vibes')
    vibe_type  = models.CharField(max_length=10, choices=ProfilePostVibe.VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('item', 'user')
        ordering = ['created_at']
        db_table = 'ProfilePortfolioItemVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on portfolio item {self.item_id}"


class ProfilePortfolioItemComment(models.Model):
    """Comments on a ProfilePortfolioItem (portfolio piece or project)."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item       = models.ForeignKey(ProfilePortfolioItem, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_portfolio_comments')
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
        db_table = 'ProfilePortfolioItemComment_Table'

    def __str__(self):
        return f"{self.author.username} on portfolio item {self.item_id}: {self.text[:50]}"


class ProfileAchievementVibe(models.Model):
    """Vibe reactions on a ProfileAchievement."""
    achievement = models.ForeignKey(ProfileAchievement, on_delete=models.CASCADE, related_name='vibes')
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_achievement_vibes')
    vibe_type   = models.CharField(max_length=10, choices=ProfilePostVibe.VIBE_CHOICES)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('achievement', 'user')
        ordering = ['created_at']
        db_table = 'ProfileAchievementVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on achievement {self.achievement_id}"


class ProfileAchievementComment(models.Model):
    """Comments on a ProfileAchievement."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    achievement = models.ForeignKey(ProfileAchievement, on_delete=models.CASCADE, related_name='comments')
    author      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_achievement_comments')
    text        = models.TextField()
    created_at  = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        self.text = sanitize_text(self.text, 'comment')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        db_table = 'ProfileAchievementComment_Table'

    def __str__(self):
        return f"{self.author.username} on achievement {self.achievement_id}: {self.text[:50]}"


class ProfileExperienceVibe(models.Model):
    """Vibe reactions on a ProfileExperience entry."""
    experience = models.ForeignKey(ProfileExperience, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_experience_vibes')
    vibe_type  = models.CharField(max_length=10, choices=ProfilePostVibe.VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('experience', 'user')
        ordering = ['created_at']
        db_table = 'ProfileExperienceVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on experience {self.experience_id}"


class ProfileExperienceComment(models.Model):
    """Comments on a ProfileExperience entry."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    experience = models.ForeignKey(ProfileExperience, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_experience_comments')
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
        db_table = 'ProfileExperienceComment_Table'

    def __str__(self):
        return f"{self.author.username} on experience {self.experience_id}: {self.text[:50]}"


class ProfileEducationVibe(models.Model):
    """Vibe reactions on a ProfileEducation entry."""
    education  = models.ForeignKey(ProfileEducation, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_education_vibes')
    vibe_type  = models.CharField(max_length=10, choices=ProfilePostVibe.VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('education', 'user')
        ordering = ['created_at']
        db_table = 'ProfileEducationVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on education {self.education_id}"


class ProfileEducationComment(models.Model):
    """Comments on a ProfileEducation entry."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    education  = models.ForeignKey(ProfileEducation, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_education_comments')
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
        db_table = 'ProfileEducationComment_Table'

    def __str__(self):
        return f"{self.author.username} on education {self.education_id}: {self.text[:50]}"


class ProfileServiceVibe(models.Model):
    """Vibe reactions on a ProfileService."""
    service    = models.ForeignKey(ProfileService, on_delete=models.CASCADE, related_name='vibes')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_service_vibes')
    vibe_type  = models.CharField(max_length=10, choices=ProfilePostVibe.VIBE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('service', 'user')
        ordering = ['created_at']
        db_table = 'ProfileServiceVibe_Table'

    def __str__(self):
        return f"{self.user.username} vibed {self.vibe_type} on service {self.service_id}"


class ProfileServiceComment(models.Model):
    """Comments on a ProfileService."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service    = models.ForeignKey(ProfileService, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_service_comments')
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
        db_table = 'ProfileServiceComment_Table'

    def __str__(self):
        return f"{self.author.username} on service {self.service_id}: {self.text[:50]}"


# ─────────────────────────────────────────────────────────────────────────────
# ProfileItemNotification — reaction/comment notifications for the profile's
# other sub-sections: Portfolio/Project, Achievement, Experience, Education,
# and Service. Mirrors ProfilePostNotification's new_vibe/new_comment
# handling, but a single model covers all five sections instead of one
# model per section — exactly one of the five target FKs below is set per
# row, matching which section the notification belongs to.
# ─────────────────────────────────────────────────────────────────────────────

class ProfileItemNotification(models.Model):
    """
    Notifications tied to one of a profile's "extra" sections:
      - 'new_vibe'    → sent to the item owner when someone reacts to it.
      - 'new_comment' → sent to the item owner when someone comments on it.
    A single actor can only have one active 'new_vibe' row per item (their
    reaction is refreshed in place if they change/re-apply it); comments
    always create a fresh row since each comment is a distinct event.
    """
    NEW_VIBE    = 'new_vibe'
    NEW_COMMENT = 'new_comment'
    NOTIF_TYPE_CHOICES = [
        (NEW_VIBE,    'New reaction'),
        (NEW_COMMENT, 'New comment'),
    ]

    PORTFOLIO   = 'portfolio'
    ACHIEVEMENT = 'achievement'
    EXPERIENCE  = 'experience'
    EDUCATION   = 'education'
    SERVICE     = 'service'
    SECTION_CHOICES = [
        (PORTFOLIO,   'Portfolio / Project'),
        (ACHIEVEMENT, 'Achievement'),
        (EXPERIENCE,  'Experience'),
        (EDUCATION,   'Education'),
        (SERVICE,     'Service'),
    ]

    # Card id prefix + subtab name used to build a deep link back to the
    # source item on the profile page (kept here so views/templates never
    # have to hard-code this mapping in more than one place).
    _ANCHOR_PREFIX = {
        PORTFOLIO:   'kpp-portfolio-',
        ACHIEVEMENT: 'kpp-achievement-',
        EXPERIENCE:  'kpp-experience-',
        EDUCATION:   'kpp-education-',
        SERVICE:     'kpp-service-',
    }
    _SECTION_LABEL = {
        PORTFOLIO:   'portfolio piece',
        ACHIEVEMENT: 'achievement',
        EXPERIENCE:  'experience',
        EDUCATION:   'education entry',
        SERVICE:     'service',
    }

    notif_type = models.CharField(max_length=20, choices=NOTIF_TYPE_CHOICES, db_index=True)
    section    = models.CharField(max_length=20, choices=SECTION_CHOICES, db_index=True)

    # Exactly one of these is set, matching `section`.
    portfolio_item = models.ForeignKey(
        ProfilePortfolioItem, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications'
    )
    achievement = models.ForeignKey(
        ProfileAchievement, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications'
    )
    experience = models.ForeignKey(
        ProfileExperience, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications'
    )
    education = models.ForeignKey(
        ProfileEducation, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications'
    )
    service = models.ForeignKey(
        ProfileService, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications'
    )

    # actor: the user who reacted or commented.
    actor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_profile_item_notifications'
    )
    # to_user: the item's owner — the recipient of the notification.
    to_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='profile_item_notifications'
    )
    vibe_type = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Set for new_vibe notifications only (e.g. "fire", "love").'
    )
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ProfileItemNotification_Table'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['to_user', 'is_read']),
            models.Index(fields=['section', 'notif_type']),
        ]

    def __str__(self):
        verb = 'vibed' if self.notif_type == self.NEW_VIBE else 'commented on'
        return f"{self.actor.username} {verb} {self.get_section_display()} {self.target_id}"

    @property
    def target(self):
        """Whichever of the five FKs is set for this row."""
        return (
            self.portfolio_item or self.achievement or self.experience
            or self.education or self.service
        )

    @property
    def target_id(self):
        t = self.target
        return t.pk if t else None

    @property
    def target_label(self):
        """Human-readable title for the source item, regardless of section
        (ProfileEducation uses `school_name` instead of `title`)."""
        t = self.target
        if not t:
            return ''
        return getattr(t, 'title', None) or getattr(t, 'school_name', '')

    @property
    def target_image_url(self):
        t = self.target
        return t.get_image_url if t else ''

    @property
    def section_label(self):
        return self._SECTION_LABEL.get(self.section, self.section)

    @property
    def anchor_id(self):
        """DOM id of the source card on the profile page, e.g.
        'kpp-portfolio-<uuid>' — matches the ids rendered in profile.html
        and the PROFILE_ITEM_URL_MAP.card() ids used there."""
        t = self.target
        if not t:
            return ''
        return f'{self._ANCHOR_PREFIX.get(self.section, "")}{t.pk}'

    @property
    def subtab(self):
        """Which Professional-tab subtab the item lives in. Portfolio items
        live in either the 'portfolio' or 'projects' subtab depending on
        their `kind`; every other section maps 1:1 to its own subtab."""
        if self.section == self.PORTFOLIO:
            t = self.target
            return 'projects' if (t and t.kind == ProfilePortfolioItem.KIND_PROJECT) else 'portfolio'
        if self.section == self.ACHIEVEMENT:
            return 'achievements'
        if self.section == self.SERVICE:
            return 'services'
        return self.section  # 'experience' / 'education'
