import os
import re
import uuid as uuid_module
import socket

from html import escape as html_escape, unescape as html_unescape
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from .models import FollowNotification, BusinessNotification, ProfilePostNotification, ProfileItemNotification
from django.template.loader import render_to_string
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, UserReport, BlockedUser, ChannelUserLastSeen, Message, ChannelMessage, Channel, Market, MarketImage, SearchHistory, SocialEvent, JobVacancy, JobVibe, JobComment, EventVibe, EventComment, BusinessPage, Wishlist, ProductReview, EventFollow, EventNotification, BusinessPost, BusinessPostImage, BusinessPostPoll, BusinessPostPollOption, BusinessPostPollVote, BusinessPostVibe, BusinessPostComment, BusinessService, BusinessPortfolioItem, BusinessPortfolioImage, BusinessAchievement, BusinessReview, ProfilePost, ProfilePostImage, ProfilePostPoll, ProfilePostPollOption, ProfilePostPollVote, ProfilePostVibe, ProfilePostComment, ProfileService, ProfilePortfolioItem, ProfileAchievement, ProfileExperience, ProfileEducation, ProfilePortfolioItemVibe, ProfilePortfolioItemComment, ProfileAchievementVibe, ProfileAchievementComment, ProfileExperienceVibe, ProfileExperienceComment, ProfileEducationVibe, ProfileEducationComment, ProfileServiceVibe, ProfileServiceComment
from social.models import validate_url
from social.models import MEMBER_TYPE_SCHEMA, MEMBER_TYPE_CHOICES, sanitize_member_type_data, validate_file_size, DAY_CHOICES, HOUR_CHOICES


def _member_type_edit_schema(profile):
    """
    Builds a version of MEMBER_TYPE_SCHEMA with each field's current saved
    value attached, so the edit-profile modal template can render inputs
    without needing dynamic dict lookups by variable key.
    """
    data = profile.member_type_data or {}
    out = []
    for key, cfg in MEMBER_TYPE_SCHEMA.items():
        fields = []
        for field in cfg['fields']:
            f = dict(field)
            saved_value = data.get(field['key'], '')
            f['value'] = saved_value
            if field['type'] == 'select_other':
                choices = field.get('choices', [])
                if saved_value in choices:
                    f['select_value'] = saved_value
                    f['other_value'] = ''
                elif saved_value:
                    f['select_value'] = 'Other'
                    f['other_value'] = saved_value
                else:
                    f['select_value'] = ''
                    f['other_value'] = ''
            elif field['type'] == 'days_hours':
                # Parse the stored "Mon, Wed · 9:00 AM – 5:00 PM"-style string
                # back into its parts so the form can pre-select them.
                f['day_choices'] = DAY_CHOICES
                f['hour_choices'] = HOUR_CHOICES
                selected_days, open_value, close_value = [], '', ''
                if saved_value:
                    segments = saved_value.split(' · ')
                    for segment in segments:
                        if '–' in segment:
                            open_part, _, close_part = segment.partition('–')
                            open_value = open_part.strip()
                            close_value = close_part.strip()
                        else:
                            segment_days = [d.strip() for d in segment.split(',') if d.strip()]
                            if all(d in DAY_CHOICES for d in segment_days) and segment_days:
                                selected_days = segment_days
                f['selected_days'] = selected_days
                f['open_value'] = open_value
                f['close_value'] = close_value
            fields.append(f)
        out.append({'key': key, 'label': cfg['label'], 'emoji': cfg['emoji'], 'blurb': cfg['blurb'], 'fields': fields})
    return out
from django.core.exceptions import ValidationError as _ModelValidationError


def _clean_apply_link(raw):
    """Validate an optional 'apply link' POST field. Returns (url, error_message)."""
    raw = (raw or '').strip()
    if not raw:
        return '', None
    try:
        return validate_url(raw), None
    except _ModelValidationError:
        return '', 'Please enter a valid application link (starting with http:// or https://).'
from django.db.models import Q
from django.db.models import Count, Max, Min
from django.db.models import Case, When, Value, IntegerField, TextField
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time, json, logging, re, requests, ipaddress
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote as url_quote
from django.http import JsonResponse, Http404
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime as django_parse_datetime
import json as _json
from datetime import datetime, timedelta
import random
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.http import require_POST, require_GET
from django.core.cache import cache
import cloudinary

# ─────────────────────────────────────────────────────────────────────────────
# Registration helpers — compiled once, reused by view + AJAX endpoints
# ─────────────────────────────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{5,30}$')
_EMAIL_RE    = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

_COMMON_PASSWORDS = {
    'password', 'password1', '12345678', '123456789', 'qwerty123',
    'iloveyou', 'admin123', 'letmein1', 'welcome1', 'monkey123',
    'dragon12', 'master12', 'abc12345', 'passw0rd', 'superman',
    'baseball', 'football', 'shadow12', 'master12', 'qwerty12',
    '1q2w3e4r', '123qwe', 'zxcvbnm', 'trustno1', 'starwars',
}

def _score_password(pw: str):
    score = 0
    if len(pw) >= 8:   score += 1
    if len(pw) >= 12:  score += 1
    if re.search(r'[A-Z]', pw): score += 1
    if re.search(r'[0-9]', pw): score += 1
    if re.search(r'[^A-Za-z0-9]', pw): score += 1
    labels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong']
    return min(score, 4), labels[min(score, 4)]

def _validate_registration(username, email, password, password2):
    """Central validation — single source of truth for view + AJAX."""
    errors = []
    if not username:
        errors.append('Username is required.')
    elif len(username) < 5:
        errors.append('Username must be at least 5 characters.')
    elif len(username) > 30:
        errors.append('Username must be 30 characters or fewer.')
    elif not _USERNAME_RE.match(username):
        errors.append('Username may only contain letters, numbers and underscores.')
    elif User.objects.filter(username__iexact=username).exists():
        errors.append('That username is already taken.')

    if not email:
        errors.append('Email address is required.')
    elif not _EMAIL_RE.match(email):
        errors.append('Please enter a valid email address.')
    elif User.objects.filter(email__iexact=email).exists():
        errors.append('An account with that email already exists.')

    if not password:
        errors.append('Password is required.')
    elif len(password) < 8:
        errors.append('Password must be at least 8 characters.')
    elif password.lower() in _COMMON_PASSWORDS:
        errors.append('That password is too common — please choose a stronger one.')
    elif username and password.lower() == username.lower():
        errors.append('Password cannot be the same as your username.')

    if password and password != password2:
        errors.append('Passwords do not match.')

    return errors

# ─────────────────────────────────────────────────────────────────────────────
# Create your views here.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Safe-redirect helper — prevents open-redirect attacks via ?next= parameter
# ─────────────────────────────────────────────────────────────────────────────
_ALLOWED_ORIGINS = (
    'http://127.0.0.1',
    'https://kishihub.com',
    'https://kishihub.onrender.com',
    'www.kishihub.com'
)

def _safe_next(request, fallback='/home'):
    """
    Validate the ?next= parameter.
    Only allows relative paths that start with /  and rejects
    protocol-relative (//evil.com) and absolute external URLs.
    """
    next_url = request.GET.get('next', '').strip()
    if (
        next_url
        and next_url.startswith('/')
        and not next_url.startswith('//')   # block //evil.com
        and '\x00' not in next_url          # block null bytes
    ):
        return next_url
    return fallback

# ─────────────────────────────────────────────────────────────────────────────
# Verification gate for job/event posting
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_PROFILE_FIELDS = [
    ('full_name',        'Full name'),
    ('phone',            'Phone number'),
]

def _profile_post_status(user):
    """
    Returns (can_post: bool, missing: list[str]).
    can_post is True when all required profile fields are filled.
    Verification (is_verify) is intentionally not checked here — it will
    be enforced separately once that feature is fully implemented.
    """
    try:
        profile = user.profile
    except Exception:
        return False, [label for _, label in _REQUIRED_PROFILE_FIELDS]

    missing = [
        label
        for field, label in _REQUIRED_PROFILE_FIELDS
        if not getattr(profile, field, '').strip()
    ]
    can_post = not missing
    return can_post, missing


def _flatten_validation_error(e):
    """Flatten a Django ValidationError (dict or list form) into a list of plain strings."""
    try:
        if hasattr(e, 'message_dict'):
            out = []
            for msgs in e.message_dict.values():
                out.extend(msgs)
            return out
        if hasattr(e, 'messages'):
            return list(e.messages)
    except Exception:
        pass
    return [str(e)]


def _format_count(n):
    """12345 -> '12.3K', 1250000 -> '1.3M', 842 -> '842'."""
    n = n or 0
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}".rstrip('0').rstrip('.') + 'M+'
    if n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}".rstrip('0').rstrip('.') + 'K+'
    return str(n)


def index(request):
    # ── Already logged in ─────────────────────────────────────────────────────
    if request.user.is_authenticated:
        return redirect(_safe_next(request, '/home'))

    # ── POST — login attempt ──────────────────────────────────────────────────
    if request.method == 'POST':

        user_check = (request.POST.get('user_check') or '').strip()
        password   = (request.POST.get('password')   or '').strip()

        if not user_check or not password:
            messages.error(request, 'Please fill in all fields.')
            return redirect('/')

        # Allow login by email OR username
        try:
            user_obj = User.objects.get(email__iexact=user_check)
            username = user_obj.username
        except User.DoesNotExist:
            username = user_check

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            request.session.set_expiry(None)
            return redirect(_safe_next(request, '/home'))
        else:
            messages.error(request, 'Invalid username or password. Please try again.')
            return redirect('/')

    return render(request, 'index.html', {
        # Tells index.html to auto-open the Register modal instead of the
        # Login modal (set by register() when it bounces validation errors
        # back to '/', or when someone hits /register/ directly).
        'open_register_modal': request.session.pop('mfy_open_register', False),
    })

@csrf_protect
def register(request):
    """
    Registration is now handled entirely as a modal on the index ('/') page —
    there is no standalone register page anymore. This view only processes
    the POST from that modal (and the legacy AJAX check-* endpoints below
    still work the same way). Any GET here (e.g. an old bookmark/link to
    /register/) just bounces to '/' with the modal flagged to auto-open.
    """
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username  = html_escape(request.POST.get('username', '').strip())
        email     = html_escape(request.POST.get('email', '').strip().lower())
        password  = request.POST.get('pass1', '')
        password2 = request.POST.get('pass2', '')

        errors = _validate_registration(username, email, password, password2)
        if errors:
            for err in errors:
                messages.error(request, err, extra_tags='register')
            request.session['mfy_open_register'] = True
            return redirect('/')

        secret_question = html_escape(request.POST.get('secret_question', '').strip())
        secret_answer   = request.POST.get('secret_answer', '').strip()

        from .models import SecretQuestion
        valid_keys = [k for k, _ in SecretQuestion.QUESTION_CHOICES]
        if not secret_question or secret_question not in valid_keys:
            messages.error(request, 'Please choose a valid security question.', extra_tags='register')
            request.session['mfy_open_register'] = True
            return redirect('/')
        if not secret_answer or len(secret_answer) < 2:
            messages.error(request, 'Security answer must be at least 2 characters.', extra_tags='register')
            request.session['mfy_open_register'] = True
            return redirect('/')

        gender        = html_escape(request.POST.get('gender', '').strip())

        # Validate gender
        valid_genders = ['male', 'female', 'non_binary', 'prefer_not_to_say']
        if gender and gender not in valid_genders:
            gender = ''

        user = User.objects.create_user(username=username, email=email, password=password)
        profile = Profile.objects.create(
            user=user,
            gender=gender,
        )

        # Handle optional profile picture upload
        pic = request.FILES.get('profile_picture')
        if pic:
            profile.picture = pic
            profile.save(update_fields=['picture'])

        sq = SecretQuestion(user=user, question=secret_question)
        sq.set_answer(secret_answer)
        sq.save()

        messages.success(request, f'Welcome {username}! You can now log in.')
        return redirect('/')

    # GET /register/ — no more standalone page, send them home with the
    # register modal open.
    request.session['mfy_open_register'] = True
    return redirect('/')


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding — "What do you use Marketfy for?"
# ─────────────────────────────────────────────────────────────────────────────

def _collect_indexed_entries(post, files, prefix):
    """Collect indexed form-array entries like 'experience-0-title',
    'experience-0-image', 'experience-1-title' ... (from onboarding's
    repeatable Experience/Education rows) into an ordered list of dicts:
    [{'title': ..., 'image': <UploadedFile>, ...}, {...}]. Text fields
    come from `post`, file fields from `files`; a field present in both
    (shouldn't normally happen) prefers the file. Unknown prefixes just
    return an empty list.
    """
    pattern = re.compile(r'^' + re.escape(prefix) + r'-(\d+)-(.+)$')
    entries = {}
    for key in post.keys():
        m = pattern.match(key)
        if not m:
            continue
        idx, field = m.group(1), m.group(2)
        entries.setdefault(idx, {})[field] = post.get(key)
    for key in files.keys():
        m = pattern.match(key)
        if not m:
            continue
        idx, field = m.group(1), m.group(2)
        entries.setdefault(idx, {})[field] = files.get(key)
    return [entries[k] for k in sorted(entries.keys(), key=int)]


def _create_onboarding_experience_entries(profile, request):
    """Creates or updates ProfileExperience rows from onboarding Step 3's
    repeatable 'experience-<n>-...' fields. Rows carrying an 'id' field that
    matches a row already owned by this profile are updated in place (this
    is how re-running onboarding via ?edit=1 shows previous entries
    pre-filled and lets them be edited rather than duplicated); rows
    without a matching id are created as new. Any existing row that isn't
    resubmitted (e.g. removed via the trash button in the UI) is deleted.
    Rows missing a title or company are silently skipped — this step is
    optional, so partial rows shouldn't block finishing onboarding.
    Returns the number of rows newly created."""
    created = 0
    kept_ids = set()
    for entry in _collect_indexed_entries(request.POST, request.FILES, 'experience'):
        title = (entry.get('title') or '').strip()
        company_name = (entry.get('company_name') or '').strip()
        if not title or not company_name:
            continue

        employment_type = (entry.get('employment_type') or '').strip()
        if employment_type not in dict(ProfileExperience.EMPLOYMENT_TYPE_CHOICES):
            employment_type = ''
        is_current = str(entry.get('is_current') or '') in ('1', 'true', 'on')

        start_date = None
        start_raw = (entry.get('start_date') or '').strip()
        if start_raw:
            try:
                start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
            except ValueError:
                start_date = None

        end_date = None
        if not is_current:
            end_raw = (entry.get('end_date') or '').strip()
            if end_raw:
                try:
                    end_date = datetime.strptime(end_raw, '%Y-%m-%d').date()
                except ValueError:
                    end_date = None

        image = entry.get('image') or None
        if image is not None:
            allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
            if getattr(image, 'content_type', None) not in allowed_types or image.size > 10 * 1024 * 1024:
                image = None

        entry_id = (entry.get('id') or '').strip()
        existing = None
        if entry_id:
            existing = ProfileExperience.objects.filter(profile=profile, experience_id=entry_id).first()

        try:
            if existing:
                existing.title = title[:150]
                existing.company_name = company_name[:150]
                existing.employment_type = employment_type
                existing.location = (entry.get('location') or '').strip()[:150]
                existing.description = (entry.get('description') or '').strip()
                existing.start_date = start_date
                existing.end_date = end_date
                existing.is_current = is_current
                if image is not None:
                    existing.image = image
                existing.save()
                kept_ids.add(existing.pk)
            else:
                new_row = ProfileExperience.objects.create(
                    profile=profile, title=title[:150], company_name=company_name[:150],
                    employment_type=employment_type, location=(entry.get('location') or '').strip()[:150],
                    description=(entry.get('description') or '').strip(),
                    start_date=start_date, end_date=end_date, is_current=is_current,
                    image=image,
                )
                created += 1
                kept_ids.add(new_row.pk)
        except _ModelValidationError:
            continue

    profile.experiences.exclude(pk__in=kept_ids).delete()
    return created


def _create_onboarding_education_entries(profile, request):
    """Creates or updates ProfileEducation rows from onboarding Step 3's
    repeatable 'education-<n>-...' fields. Rows carrying an 'id' field that
    matches a row already owned by this profile are updated in place (this
    is how re-running onboarding via ?edit=1 shows previous entries
    pre-filled and lets them be edited rather than duplicated); rows
    without a matching id are created as new. Any existing row that isn't
    resubmitted (e.g. removed via the trash button in the UI) is deleted.
    Rows missing a school name are silently skipped. Returns the number of
    rows newly created."""
    created = 0
    kept_ids = set()
    for entry in _collect_indexed_entries(request.POST, request.FILES, 'education'):
        school_name = (entry.get('school_name') or '').strip()
        if not school_name:
            continue

        is_current = str(entry.get('is_current') or '') in ('1', 'true', 'on')

        start_date = None
        start_raw = (entry.get('start_date') or '').strip()
        if start_raw:
            try:
                start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
            except ValueError:
                start_date = None

        end_date = None
        if not is_current:
            end_raw = (entry.get('end_date') or '').strip()
            if end_raw:
                try:
                    end_date = datetime.strptime(end_raw, '%Y-%m-%d').date()
                except ValueError:
                    end_date = None

        image = entry.get('image') or None
        if image is not None:
            allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
            if getattr(image, 'content_type', None) not in allowed_types or image.size > 10 * 1024 * 1024:
                image = None

        entry_id = (entry.get('id') or '').strip()
        existing = None
        if entry_id:
            existing = ProfileEducation.objects.filter(profile=profile, education_id=entry_id).first()

        try:
            if existing:
                existing.school_name = school_name[:150]
                existing.degree = (entry.get('degree') or '').strip()[:150]
                existing.field_of_study = (entry.get('field_of_study') or '').strip()[:150]
                existing.grade = (entry.get('grade') or '').strip()[:50]
                existing.description = (entry.get('description') or '').strip()
                existing.start_date = start_date
                existing.end_date = end_date
                existing.is_current = is_current
                if image is not None:
                    existing.image = image
                existing.save()
                kept_ids.add(existing.pk)
            else:
                new_row = ProfileEducation.objects.create(
                    profile=profile, school_name=school_name[:150],
                    degree=(entry.get('degree') or '').strip()[:150],
                    field_of_study=(entry.get('field_of_study') or '').strip()[:150],
                    grade=(entry.get('grade') or '').strip()[:50],
                    description=(entry.get('description') or '').strip(),
                    start_date=start_date, end_date=end_date, is_current=is_current,
                    image=image,
                )
                created += 1
                kept_ids.add(new_row.pk)
        except _ModelValidationError:
            continue

    profile.education_history.exclude(pk__in=kept_ids).delete()
    return created


@login_required(login_url='/')
def onboarding(request):
    profile = request.user.profile

    # Already done — nothing to do here (unless they explicitly want to change it).
    if profile.onboarding_completed and request.method == 'GET' and request.GET.get('edit') != '1':
        return redirect('home')

    # Previously-saved Experience/Education rows — passed to every render of
    # this view so Step 3 shows them pre-filled instead of blank when the
    # owner is re-running onboarding (e.g. ?edit=1) to update their profile.
    existing_experience = list(profile.experiences.all()) if profile.pk else []
    existing_education = list(profile.education_history.all()) if profile.pk else []

    if request.method == 'POST':
        if request.POST.get('skip') == '1':
            profile.onboarding_completed = True
            profile.save(update_fields=['onboarding_completed'])
            return redirect('home')

        member_type = request.POST.get('member_type', '').strip()
        valid_types = {k for k, _ in MEMBER_TYPE_CHOICES}

        if member_type not in valid_types:
            messages.error(request, 'Please choose what best describes you.')
            return render(request, 'onboarding.html', {
                'member_type_schema': _member_type_edit_schema(profile),
                'selected_type': member_type,
                'employment_type_choices': ProfileExperience.EMPLOYMENT_TYPE_CHOICES,
                'existing_experience': existing_experience,
                'existing_education': existing_education,
            })

        raw_data = {}
        for field in MEMBER_TYPE_SCHEMA[member_type]['fields']:
            key = field['key']
            posted_name = f'mt_{member_type}__{key}'
            if field['type'] == 'days_hours':
                raw_data[key + '__days'] = request.POST.getlist(posted_name + '__days')
                raw_data[key + '__open'] = request.POST.get(posted_name + '__open', '')
                raw_data[key + '__close'] = request.POST.get(posted_name + '__close', '')
                continue
            raw_data[key] = request.POST.get(posted_name, '')
            if field['type'] == 'select_other':
                raw_data[key + '__other'] = request.POST.get(posted_name + '__other', '')
        cleaned = sanitize_member_type_data(member_type, raw_data)

        required_missing = [
            f['label'] for f in MEMBER_TYPE_SCHEMA[member_type]['fields']
            if f.get('required') and not cleaned.get(f['key']) and f['type'] != 'file'
        ]
        if required_missing:
            messages.error(request, f"Please fill in: {', '.join(required_missing)}")
            return render(request, 'onboarding.html', {
                'member_type_schema': _member_type_edit_schema(profile),
                'selected_type': member_type,
                'submitted': raw_data,
                'employment_type_choices': ProfileExperience.EMPLOYMENT_TYPE_CHOICES,
                'existing_experience': existing_experience,
                'existing_education': existing_education,
            })

        profile.member_type = member_type
        profile.member_type_data = cleaned

        # Seed sensible default professional sections (Experience, Education,
        # Services, Portfolio, Achievements, Jobs, etc.) for this member
        # type — mirrors the same seeding the profile-edit form does, so a
        # brand-new profile isn't left with every section switched off.
        # Only seeds once: if the owner already customized their sections
        # (e.g. re-running onboarding via ?edit=1), their choices are kept.
        if not profile.enabled_sections:
            profile.enabled_sections = Profile.default_sections_for(member_type)
            profile.sells_products = member_type in Profile.MEMBER_TYPES_SELLING_BY_DEFAULT

        cv_field_name = next(
            (f'mt_{member_type}__{f["key"]}' for f in MEMBER_TYPE_SCHEMA[member_type]['fields'] if f['type'] == 'file'),
            None
        )
        cv_file = request.FILES.get(cv_field_name) if cv_field_name else None
        if cv_file:
            try:
                ext = os.path.splitext(cv_file.name)[1].lower()
                if ext not in {'.pdf', '.doc', '.docx'}:
                    raise _ModelValidationError('CV must be a PDF, DOC, or DOCX file.')
                validate_file_size(cv_file, max_size_mb=5)
                profile.member_type_cv = cv_file
                profile.member_type_cv_name = cv_file.name
            except _ModelValidationError as e:
                messages.error(request, str(e))
                return render(request, 'onboarding.html', {
                    'member_type_schema': _member_type_edit_schema(profile),
                    'selected_type': member_type,
                    'submitted': raw_data,
                    'employment_type_choices': ProfileExperience.EMPLOYMENT_TYPE_CHOICES,
                    'existing_experience': existing_experience,
                    'existing_education': existing_education,
                })

        # ── Step 3 (optional): repeatable Experience / Education rows ──────
        # profile already has a pk (it's an existing OneToOne row), so these
        # FK creates are safe even though profile.save() hasn't run yet.
        exp_created = _create_onboarding_experience_entries(profile, request)
        edu_created = _create_onboarding_education_entries(profile, request)
        # Make sure whatever the owner actually filled in during Step 3 is
        # visible, even if it isn't a default section for their member type
        # (e.g. a Business Owner who still added their education history).
        sections = list(profile.enabled_sections or [])
        if exp_created and 'experience' not in sections:
            sections.append('experience')
        if edu_created and 'education' not in sections:
            sections.append('education')
        profile.enabled_sections = sections

        profile.onboarding_completed = True
        profile.save()

        messages.success(request, "You're all set!")
        return redirect('profile', username=request.user.username)

    return render(request, 'onboarding.html', {
        'member_type_schema': _member_type_edit_schema(profile),
        'selected_type': profile.member_type,
        'employment_type_choices': ProfileExperience.EMPLOYMENT_TYPE_CHOICES,
        'existing_experience': existing_experience,
        'existing_education': existing_education,
    })



# ─────────────────────────────────────────────────────────────────────────────
# Forgot Password — secret-question flow (AJAX JSON endpoint)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_protect
@require_POST
def forgot_password_lookup(request):
    """
    Step 1 — receives {username_or_email} and returns the user's
    secret question label so the modal can display it.
    """
    from django.core.cache import cache
    ip  = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    key = f'fpw_lookup_{ip}'
    if cache.get(key, 0) >= 10:
        return JsonResponse({'error': 'Too many attempts. Please try again later.'}, status=429)
    cache.set(key, cache.get(key, 0) + 1, timeout=900)

    from .models import SecretQuestion
    user_check = (request.POST.get('user_check') or '').strip()
    if not user_check:
        return JsonResponse({'error': 'Please enter your username or email.'}, status=400)

    try:
        user_obj = User.objects.get(email__iexact=user_check)
    except User.DoesNotExist:
        try:
            user_obj = User.objects.get(username__iexact=user_check)
        except User.DoesNotExist:
            # Vague on purpose — don't confirm existence
            return JsonResponse({'error': 'No account found with that username or email.'}, status=404)

    try:
        sq = user_obj.secret_question
    except SecretQuestion.DoesNotExist:
        return JsonResponse({'error': 'This account has no security question set up.'}, status=400)

    return JsonResponse({
        'ok': True,
        'question': SecretQuestion.question_label(sq.question),
        'username': user_obj.username,
    })


@csrf_protect
@require_POST
def forgot_password_reset(request):
    """
    Step 2 — receives {username, secret_answer, new_password, confirm_password}.
    Verifies the answer then resets the password.
    """
    from django.core.cache import cache
    from django.contrib.auth import update_session_auth_hash
    from .models import SecretQuestion

    ip  = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    key = f'fpw_reset_{ip}'
    if cache.get(key, 0) >= 5:
        return JsonResponse({'error': 'Too many reset attempts. Please wait before trying again.'}, status=429)
    cache.set(key, cache.get(key, 0) + 1, timeout=900)

    username       = (request.POST.get('username') or '').strip()
    secret_answer  = (request.POST.get('secret_answer') or '').strip()
    new_password   = request.POST.get('new_password', '')
    confirm_pw     = request.POST.get('confirm_password', '')

    if not all([username, secret_answer, new_password, confirm_pw]):
        return JsonResponse({'error': 'All fields are required.'}, status=400)

    try:
        user_obj = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Something went wrong. Please start over.'}, status=400)

    try:
        sq = user_obj.secret_question
    except SecretQuestion.DoesNotExist:
        return JsonResponse({'error': 'No security question found for this account.'}, status=400)

    if not sq.check_answer(secret_answer):
        return JsonResponse({'error': 'Incorrect answer. Please try again.'}, status=400)

    # Validate new password
    if len(new_password) < 8:
        return JsonResponse({'error': 'Password must be at least 8 characters.'}, status=400)

    _COMMON_PW = {
        'password', 'password1', '12345678', '123456789', 'qwerty123',
        'iloveyou', 'admin123', 'letmein1', 'welcome1', 'monkey123',
    }
    if new_password.lower() in _COMMON_PW:
        return JsonResponse({'error': 'That password is too common — choose a stronger one.'}, status=400)
    if new_password != confirm_pw:
        return JsonResponse({'error': 'Passwords do not match.'}, status=400)

    user_obj.set_password(new_password)
    user_obj.save()

    cache.delete(key)

    return JsonResponse({'ok': True, 'message': 'Password reset successfully! You can now log in.'})


# ── AJAX real-time validation endpoints ──────────────────────────────────────

@require_GET
def validate_username(request):
    """GET /register/check-username/?username=…"""
    from django.core.cache import cache
    ip = (request.META.get('HTTP_X_FORWARDED_FOR','').split(',')[0].strip()
          or request.META.get('REMOTE_ADDR','unknown'))
    rk = f'reg_check_{ip}'
    hits = cache.get(rk, 0)
    if hits >= 60:  # 60 checks per minute per IP
        return JsonResponse({'available': False, 'error': 'Too many requests. Please slow down.'}, status=429)
    cache.set(rk, hits + 1, timeout=60)
    raw = request.GET.get('username', '').strip()
    if len(raw) < 5:
        return JsonResponse({'available': False, 'error': 'Too short (min 5 characters)'})
    if len(raw) > 30:
        return JsonResponse({'available': False, 'error': 'Too long (max 30 characters)'})
    if not _USERNAME_RE.match(raw):
        return JsonResponse({'available': False, 'error': 'Letters, numbers and underscores only'})
    if User.objects.filter(username__iexact=raw).exists():
        return JsonResponse({'available': False, 'error': 'Username is already taken'})
    return JsonResponse({'available': True, 'error': None})


@require_GET
def validate_email(request):
    """GET /register/check-email/?email=…"""
    from django.core.cache import cache
    ip = (request.META.get('HTTP_X_FORWARDED_FOR','').split(',')[0].strip()
          or request.META.get('REMOTE_ADDR','unknown'))
    rk = f'reg_check_{ip}'
    hits = cache.get(rk, 0)
    if hits >= 60:
        return JsonResponse({'available': False, 'error': 'Too many requests. Please slow down.'}, status=429)
    cache.set(rk, hits + 1, timeout=60)
    raw = request.GET.get('email', '').strip().lower()
    if not raw:
        return JsonResponse({'available': False, 'error': 'Email is required'})
    if not _EMAIL_RE.match(raw):
        return JsonResponse({'available': False, 'error': 'Invalid email format'})
    if User.objects.filter(email__iexact=raw).exists():
        return JsonResponse({'available': False, 'error': 'Email is already registered'})
    return JsonResponse({'available': True, 'error': None})


@require_GET
def validate_password_strength(request):
    """GET /register/check-password/?password=…&username=…"""
    pw       = request.GET.get('password', '')
    username = request.GET.get('username', '').strip().lower()
    if len(pw) < 8:
        return JsonResponse({'score': 0, 'label': 'Too Short', 'error': 'Minimum 8 characters'})
    if pw.lower() in _COMMON_PASSWORDS:
        return JsonResponse({'score': 0, 'label': 'Breached', 'error': 'Too common — choose a stronger password'})
    if username and pw.lower() == username:
        return JsonResponse({'score': 0, 'label': 'Insecure', 'error': 'Password cannot match username'})
    score, label = _score_password(pw)
    return JsonResponse({'score': score, 'label': label, 'error': None})





def _safe_redirect_back(request, fallback='home'):
   
    referer = request.META.get('HTTP_REFERER', '')
    allowed_origins = (
        'http://127.0.0.1',
        'https://kishihub.com',
        'https://kishihub.onrender.com',
        'www.kishihub.com',
    )
    if referer and any(referer.startswith(origin) for origin in allowed_origins):
        return redirect(referer)
    return redirect(fallback)




FEED_PAGE_SIZE = 10          # items returned per page


# ─────────────────────────────────────────────────────────────────────────────
# Personalized feed ranking — keyword/location/recency scoring shared by every
# candidate pool (posts, jobs, products, services, events, business pages,
# people). Signals come from the viewer's Profile (profession, member_type,
# member_type_data skills/experience, interests, location) plus who/what they
# already follow, so two users see different, individually-ranked feeds.
# ─────────────────────────────────────────────────────────────────────────────

def _profile_feed_signal(user, profile):
    """
    (keywords, location_tokens) describing what this viewer cares about —
    their own profile plus a light boost from the pages/people they follow.
    """
    keywords = set(profile.feed_keywords)
    location_tokens = set(profile.feed_location_tokens)

    for cat, ptype in BusinessPage.objects.filter(followers=user).values_list('category', 'page_type'):
        if cat:
            keywords.add(str(cat).lower())
        if ptype:
            keywords.add(str(ptype).lower())

    for prof in profile.followings.exclude(user=user).values_list('profession', flat=True)[:100]:
        keywords |= Profile._tokenize(prof)

    return keywords, location_tokens


def _content_score(keywords, location_tokens, text_blob, item_location=None,
                    created_at=None, keyword_weight=2.0, social_boost=0.0):
    """
    Generic relevance score for one feed candidate:
      + keyword overlap with the viewer's profile/interest signal
      + a bonus when the item's location matches the viewer's location
      + recency (newer content ranks higher)
      + an optional social_boost (e.g. from a followed page/user)
      + a small jitter so near-ties don't always resolve the same way
    """
    text_tokens = Profile._tokenize(text_blob)
    overlap = len(keywords & text_tokens) if keywords else 0

    loc_score = 0.0
    if location_tokens and item_location and (Profile._tokenize(item_location) & location_tokens):
        loc_score = 2.5

    recency = 0.0
    if created_at:
        age_days = (timezone.now() - created_at).total_seconds() / 86400
        if age_days <= 1:
            recency = 3.0
        elif age_days <= 3:
            recency = 2.2
        elif age_days <= 7:
            recency = 1.5
        elif age_days <= 30:
            recency = 0.6

    return (overlap * keyword_weight) + loc_score + recency + social_boost + random.random() * 0.4


def _ranked(pool, keywords, location_tokens, blob_fn, location_fn=None, created_fn=None,
            social_fn=None, limit=None):
    """Score every item in `pool` and return it sorted best-first (optionally truncated)."""
    scored = []
    for obj in pool:
        blob = blob_fn(obj)
        loc = location_fn(obj) if location_fn else None
        created = created_fn(obj) if created_fn else None
        social = social_fn(obj) if social_fn else 0.0
        scored.append((_content_score(keywords, location_tokens, blob, loc, created, social_boost=social), obj))
    scored.sort(key=lambda t: t[0], reverse=True)
    ranked_objs = [obj for _, obj in scored]
    return ranked_objs[:limit] if limit else ranked_objs






# ─────────────────────────────────────────────────────────────────────────────
# Personalized feed page builder — pulls candidate pools from every content
# type (posts, jobs, products, services/business pages, events, people),
# scores each candidate against the viewer's profile signal (_content_score),
# and interleaves the best-ranked items from each pool into one unified feed.
# Different users get different pools/order because the ranking is driven by
# their own profession, skills, interests, location, and follow graph.
# ─────────────────────────────────────────────────────────────────────────────

def _get_feed_page(user, following_ids, cursor_dt=None, page_size=None,
                   seen_suggestion_ids=None,
                   seen_market_ids=None, seen_job_ids=None, seen_event_ids=None,
                   seen_business_ids=None, seen_people_ids=None, seen_post_ids=None,
                   market_category=None,
                   market_offset=0,
                   **_kwargs):
    """
    Build one page of the personalized feed: business/post updates, market
    ads, job cards, event cards, business-page suggestions, and people
    suggestions — each ranked by relevance to this viewer, then interleaved.

    market_category: optional category key (Market.CATEGORY_CHOICES) to
    restrict market ads to a single category. 'all' or None means no filter.

    market_offset: how many matching products have already been shown for the
    active market_category filter. Used to deterministically page through the
    full category result set (ignored when no category filter is active).

    Returns (feed_items list, next_cursor).
    next_cursor is None for the normal mixed feed (item-count-driven by the
    injected cards, not post timestamps). When a market_category filter is
    active, next_cursor is the next market_offset to request, or None once
    every matching product has been shown.
    """
    import datetime as _dt_feed

    if page_size is None:
        page_size = FEED_PAGE_SIZE

    profile = getattr(user, 'profile', None) or Profile.objects.get(user=user)
    keywords, location_tokens = _profile_feed_signal(user, profile)

    following_ids_set = set(following_ids)
    next_cursor = None

    _is_market_filtered = bool(
        market_category and market_category != 'all' and market_category in Market.VALID_CATEGORIES
    )

    # ── Business page suggestions — ranked by category/skill/location match ──
    _seen_biz_ids = set(str(i) for i in (seen_business_ids or []) if i)
    followed_business_ids = set(
        BusinessPage.objects.filter(followers=user).values_list('page_id', flat=True)
    )
    business_pool_qs = (
        BusinessPage.objects
        .filter(is_active=True)
        .exclude(owner=user)
        .exclude(page_id__in=followed_business_ids)
    )
    if _seen_biz_ids:
        business_pool_qs = business_pool_qs.exclude(page_id__in=_seen_biz_ids)
    business_pool_count = business_pool_qs.count()
    suggestion_businesses = []
    if business_pool_count > 0 and not _is_market_filtered:
        sb_offset = random.randint(0, max(0, business_pool_count - 24))
        _biz_candidates = list(
            business_pool_qs.select_related('owner')
            .order_by('page_id')[sb_offset: sb_offset + 24]
        )
        suggestion_businesses = _ranked(
            _biz_candidates, keywords, location_tokens,
            blob_fn=lambda bp: ' '.join(filter(None, [
                bp.name, bp.tagline, bp.description,
                bp.get_category_display(), bp.get_page_type_display(),
            ])),
            location_fn=lambda bp: bp.location,
            created_fn=lambda bp: bp.created_at,
            limit=3,
        )

    # ── Business posts (updates) — from followed pages, plus a few relevant
    #    pages the viewer doesn't yet follow, so the feed still has post
    #    content to rank even for new users. ────────────────────────────────
    _seen_post_ids = set(str(i) for i in (seen_post_ids or []) if i)
    _post_qs = (
        BusinessPost.objects
        .select_related('business_page', 'business_page__owner')
        .prefetch_related('images', 'poll__options__votes', 'vibes', 'comments')
    )
    if _seen_post_ids:
        _post_qs = _post_qs.exclude(post_id__in=_seen_post_ids)
    _recent_cutoff = timezone.now() - timedelta(days=60)
    _post_candidates = list(
        _post_qs.filter(
            Q(business_page__in=followed_business_ids) | Q(created_at__gte=_recent_cutoff)
        )
        .order_by('-created_at')[:60]
    )
    _post_pool = [] if _is_market_filtered else _ranked(
        _post_candidates, keywords, location_tokens,
        blob_fn=lambda p: ' '.join(filter(None, [
            p.caption, p.get_post_category_display(), p.business_page.name,
            p.business_page.get_category_display(),
        ])),
        location_fn=lambda p: p.business_page.location,
        created_fn=lambda p: p.created_at,
        social_fn=lambda p: 4.0 if p.business_page_id in followed_business_ids else 0.0,
        limit=6,
    )
    # Attach each poll's total vote count + the viewer's own selected option
    # ids, plus the viewer's own reaction — same annotation the business
    # page's own Posts tab does — so the ported kbiz-post-card partial can
    # render identically without extra per-post queries.
    for _post in _post_pool:
        # Annotate so the ported kbiz-post-card partial can render the
        # Follow/Following state correctly on page load (not just after
        # the AJAX toggle updates the button client-side).
        _post.business_page.is_following = _post.business_page_id in followed_business_ids
        if _post.post_type == BusinessPost.TYPE_POLL and hasattr(_post, 'poll'):
            _poll = _post.poll
            _total = sum(o.vote_count for o in _poll.options.all())
            _poll.viewer_total_votes = _total
            _poll.viewer_voted_ids = _poll.voted_option_ids(user)
            for _opt in _poll.options.all():
                _opt.viewer_pct = _opt.vote_pct(_total)
        _post.viewer_vibe = None
        _post.viewer_vibe_emoji = ''
        _mine = next((v for v in _post.vibes.all() if v.user_id == user.pk), None)
        if _mine:
            _post.viewer_vibe = _mine.vibe_type
            _post.viewer_vibe_emoji = BusinessPostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')

    # ── Profile posts (personal updates) — from followed users, plus a few
    #    relevant posts from users not yet followed, mirroring the business
    #    post pool above so ProfilePost updates surface in the feed too,
    #    rendered with the exact same .kbiz-post-card layout. ────────────────
    _pp_qs = (
        ProfilePost.objects
        .select_related('profile', 'profile__user')
        .prefetch_related('images', 'poll__options__votes', 'vibes', 'comments')
        .exclude(profile__user=user)
    )
    if _seen_post_ids:
        _pp_qs = _pp_qs.exclude(post_id__in=_seen_post_ids)
    _pp_candidates = list(
        _pp_qs.filter(
            Q(profile__user_id__in=following_ids_set) | Q(created_at__gte=_recent_cutoff)
        )
        .order_by('-created_at')[:60]
    )
    _pp_pool = [] if _is_market_filtered else _ranked(
        _pp_candidates, keywords, location_tokens,
        blob_fn=lambda p: ' '.join(filter(None, [
            p.caption, p.category_label, p.profile.full_name,
            p.profile.profession, p.profile.member_type_label,
        ])),
        location_fn=lambda p: p.profile.location,
        created_fn=lambda p: p.created_at,
        social_fn=lambda p: 4.0 if p.profile.user_id in following_ids_set else 0.0,
        limit=6,
    )
    # Same per-post annotation as the business post pool above, so the
    # ported kbiz-post-card partial can render profile posts identically.
    for _pp in _pp_pool:
        _pp.profile.is_following = _pp.profile.user_id in following_ids_set
        if _pp.post_type == ProfilePost.TYPE_POLL and hasattr(_pp, 'poll'):
            _poll = _pp.poll
            _total = sum(o.vote_count for o in _poll.options.all())
            _poll.viewer_total_votes = _total
            _poll.viewer_voted_ids = _poll.voted_option_ids(user)
            for _opt in _poll.options.all():
                _opt.viewer_pct = _opt.vote_pct(_total)
        _pp.viewer_vibe = None
        _pp.viewer_vibe_emoji = ''
        _mine = next((v for v in _pp.vibes.all() if v.user_id == user.pk), None)
        if _mine:
            _pp.viewer_vibe = _mine.vibe_type
            _pp.viewer_vibe_emoji = ProfilePostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')

    # ── Business achievements — ranked the same way, so award/certification
    #    highlights surface in the feed for viewers with matching skills. ────
    _seen_ach_ids = set(str(i) for i in (_kwargs.get('seen_achievement_ids') or []) if i)
    _ach_pool = []
    if not _is_market_filtered:
        _ach_qs = BusinessAchievement.objects.select_related('business_page')
        if _seen_ach_ids:
            _ach_qs = _ach_qs.exclude(achievement_id__in=_seen_ach_ids)
        _ach_candidates = list(_ach_qs.order_by('-created_at')[:40])
        _ach_pool = _ranked(
            _ach_candidates, keywords, location_tokens,
            blob_fn=lambda a: ' '.join(filter(None, [
                a.title, a.issuer, a.description, a.business_page.name,
                a.business_page.get_category_display(),
            ])),
            location_fn=lambda a: a.business_page.location,
            created_fn=lambda a: a.created_at,
            social_fn=lambda a: 3.0 if a.business_page_id in followed_business_ids else 0.0,
            limit=2,
        )
    _ach_injected = 0
    _MAX_ACH_PER_PAGE = 1

    # ── Personal profile achievements — certs/awards/milestones posted
    #    directly on a user's own Profile (not a BusinessPage). Ranked the
    #    same way as business achievements so they surface in the feed too;
    #    only pulled from profiles that have the Achievements section on. ───
    _seen_pach_ids = set(str(i) for i in (_kwargs.get('seen_profile_achievement_ids') or []) if i)
    _pach_pool = []
    if not _is_market_filtered:
        _pach_qs = (
            ProfileAchievement.objects
            .select_related('profile', 'profile__user')
            .prefetch_related('vibes')
            .exclude(profile__user=user)
        )
        if _seen_pach_ids:
            _pach_qs = _pach_qs.exclude(achievement_id__in=_seen_pach_ids)
        _pach_candidates = [
            a for a in _pach_qs.order_by('-created_at')[:60]
            if a.profile.show_achievements
        ][:40]
        _pach_pool = _ranked(
            _pach_candidates, keywords, location_tokens,
            blob_fn=lambda a: ' '.join(filter(None, [
                a.title, a.issuer, a.description, a.owner_name,
                a.profile.profession,
            ])),
            location_fn=lambda a: a.profile.location,
            created_fn=lambda a: a.created_at,
            social_fn=lambda a: 4.0 if a.profile.user_id in following_ids_set else 0.0,
            limit=2,
        )
    # Same per-item annotation as the profile post pool above, so the
    # ported kbiz-post-card partial can render achievement cards identically
    # (follow button state + the viewer's own reaction, if any).
    for _pa in _pach_pool:
        _pa.profile.is_following = _pa.profile.user_id in following_ids_set
        _pa.viewer_vibe = None
        _pa.viewer_vibe_emoji = ''
        _mine = next((v for v in _pa.vibes.all() if v.user_id == user.pk), None)
        if _mine:
            _pa.viewer_vibe = _mine.vibe_type
            _pa.viewer_vibe_emoji = ProfilePostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')
    _pach_injected = 0
    _MAX_PACH_PER_PAGE = 1

    # ── Personal portfolio pieces & projects — same model, split by `kind`,
    #    posted directly on a user's own Profile. Only pulled from profiles
    #    that have the matching Portfolio/Projects section switched on. ─────
    _seen_port_ids = set(str(i) for i in (_kwargs.get('seen_portfolio_ids') or []) if i)
    _port_pool = []
    if not _is_market_filtered:
        _port_qs = (
            ProfilePortfolioItem.objects
            .select_related('profile', 'profile__user')
            .prefetch_related('vibes')
            .exclude(profile__user=user)
        )
        if _seen_port_ids:
            _port_qs = _port_qs.exclude(item_id__in=_seen_port_ids)
        _port_candidates = []
        for _pi in _port_qs.order_by('-created_at')[:60]:
            if _pi.kind == ProfilePortfolioItem.KIND_PROJECT and _pi.profile.show_projects:
                _port_candidates.append(_pi)
            elif _pi.kind == ProfilePortfolioItem.KIND_PORTFOLIO and _pi.profile.show_portfolio:
                _port_candidates.append(_pi)
        _port_candidates = _port_candidates[:40]
        _port_pool = _ranked(
            _port_candidates, keywords, location_tokens,
            blob_fn=lambda p: ' '.join(filter(None, [
                p.title, p.description, p.profile.full_name, p.profile.profession,
            ])),
            location_fn=lambda p: p.profile.location,
            created_fn=lambda p: p.created_at,
            social_fn=lambda p: 4.0 if p.profile.user_id in following_ids_set else 0.0,
            limit=2,
        )
    # Same per-item annotation as the profile post pool above, so the
    # ported kbiz-post-card partial can render portfolio/project cards
    # identically (follow button state + the viewer's own reaction, if any).
    for _pi2 in _port_pool:
        _pi2.profile.is_following = _pi2.profile.user_id in following_ids_set
        _pi2.viewer_vibe = None
        _pi2.viewer_vibe_emoji = ''
        _mine = next((v for v in _pi2.vibes.all() if v.user_id == user.pk), None)
        if _mine:
            _pi2.viewer_vibe = _mine.vibe_type
            _pi2.viewer_vibe_emoji = ProfilePostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')
    _port_injected = 0
    _MAX_PORT_PER_PAGE = 1

    # ── Market product pool ───────────────────────────────────────────────────
    _seen_market_ids = set(str(i) for i in (seen_market_ids or []))
    # Exclude products the user has already saved to their wishlist so they
    # don't keep re-appearing in the feed.
    _wishlisted_ids = set(
        Wishlist.objects.filter(user=user).values_list('product_id', flat=True)
    )
    _market_pool = []
    _market_qs = Market.objects.all()
    if _seen_market_ids:
        _market_qs = _market_qs.exclude(product_id__in=_seen_market_ids)
    if _wishlisted_ids:
        _market_qs = _market_qs.exclude(product_id__in=_wishlisted_ids)
    if _is_market_filtered:
        _market_qs = _market_qs.filter(product_category=market_category)
    _market_count = _market_qs.count()

    if _is_market_filtered:
        # Deterministic, offset-based paging so scrolling a filtered category
        # walks through every matching product exactly once instead of
        # re-randomizing a single page each time.
        _safe_offset = max(0, market_offset)
        _market_pool = list(
            _market_qs
            .select_related('product_owner', 'product_owner__profile')
            .prefetch_related('images')
            .order_by('-product_id')
            [_safe_offset: _safe_offset + page_size]
        )
        _next_market_offset = _safe_offset + page_size
        if _next_market_offset < _market_count:
            next_cursor = _next_market_offset
    else:
        _market_fetch_n = 24
        if _market_count > 0:
            _rand_offset = random.randint(0, max(0, _market_count - _market_fetch_n))
            _market_candidates = list(
                _market_qs
                .select_related('product_owner', 'product_owner__profile')
                .prefetch_related('images')
                [_rand_offset: _rand_offset + _market_fetch_n]
            )
            _market_pool = _ranked(
                _market_candidates, keywords, location_tokens,
                blob_fn=lambda m: ' '.join(filter(None, [
                    m.product_name, m.product_description, m.category_label,
                ])),
                location_fn=lambda m: m.product_location,
                created_fn=lambda m: m.posted_on,
                limit=8,
            )
    _market_injected = 0
    _MAX_MARKET_PER_PAGE = 6

    # ── Job vacancy pool — ranked by profession/skills/location match ────────
    _today = _dt_feed.date.today()
    _seen_job_ids = set(str(i) for i in (seen_job_ids or []))
    _job_pool = []
    if not _is_market_filtered:
        _job_qs = JobVacancy.objects.filter(is_open=True).select_related('posted_by', 'business_page')
        if _seen_job_ids:
            _job_qs = _job_qs.exclude(id__in=_seen_job_ids)
        _job_count = _job_qs.count()
        if _job_count > 0:
            _job_offset = random.randint(0, max(0, _job_count - 20))
            _job_candidates = list(_job_qs.order_by('-created_at')[_job_offset: _job_offset + 20])
            _job_pool = _ranked(
                _job_candidates, keywords, location_tokens,
                blob_fn=lambda j: ' '.join(filter(None, [
                    j.title, j.description, j.requirements, j.company,
                    j.get_category_display(), j.get_work_mode_display(),
                ])),
                location_fn=lambda j: j.location,
                created_fn=lambda j: j.created_at,
                limit=3,
            )
    _job_injected = 0
    _MAX_JOB_PER_PAGE = 2

    # ── Social event pool — ranked by type/skills/location match ─────────────
    _seen_event_ids = set(str(i) for i in (seen_event_ids or []))
    _event_pool = []
    if not _is_market_filtered:
        _event_base_qs = SocialEvent.objects.filter(date__gte=_today, is_cancelled=False)
        if _seen_event_ids:
            _event_base_qs = _event_base_qs.exclude(id__in=_seen_event_ids)
        _event_count = _event_base_qs.count()
        if _event_count > 0:
            _event_offset = random.randint(0, max(0, _event_count - 12))
            _event_candidates = list(
                _event_base_qs
                .select_related('created_by', 'created_by__profile')
                .order_by('date')
                [_event_offset: _event_offset + 12]
            )
            _event_pool = _ranked(
                _event_candidates, keywords, location_tokens,
                blob_fn=lambda e: ' '.join(filter(None, [
                    e.title, e.description, e.get_event_type_display(),
                ])),
                location_fn=lambda e: e.location,
                created_fn=lambda e: e.created_at,
                limit=2,
            )
    _event_injected = 0
    _MAX_EVENT_PER_PAGE = 1

    # ── People suggestions — ranked by profession/skills/interests/location ──
    _seen_people_ids = set()
    for i in (seen_people_ids or []):
        try:
            _seen_people_ids.add(int(i))
        except (TypeError, ValueError):
            continue
    people_pool = []
    if not _is_market_filtered:
        _people_qs = (
            User.objects.exclude(id__in=following_ids_set | {user.id})
            .select_related('profile')
        )
        if _seen_people_ids:
            _people_qs = _people_qs.exclude(id__in=_seen_people_ids)
        _people_count = _people_qs.count()
        if _people_count > 0:
            _people_offset = random.randint(0, max(0, _people_count - 24))
            _people_candidates = list(_people_qs.order_by('id')[_people_offset: _people_offset + 24])
            _people_candidates = [u for u in _people_candidates if hasattr(u, 'profile')]
            people_pool = _ranked(
                _people_candidates, keywords, location_tokens,
                blob_fn=lambda u: ' '.join(filter(None, [
                    u.profile.profession, u.profile.member_type_label, u.profile.bio,
                    ' '.join(u.profile.interests or []),
                ])),
                location_fn=lambda u: u.profile.location,
                limit=3,
            )
    _people_injected = 0
    _MAX_PEOPLE_PER_PAGE = 1

    # ── Build feed_items ──────────────────────────────────────────────────────
    # Inject cards at fixed intervals across page_size virtual slots so the
    # partial always has content to render even with no posts. Each pool is
    # already best-first ranked, so earlier slots surface the most relevant
    # item of that type first.
    _max_business_this_page = 1 if not _is_market_filtered else 0
    _business_injected = 0

    if _is_market_filtered:
        # Category filter is active — fill the page with market cards only,
        # ignoring everything else so the grid is pure product results.
        _MAX_MARKET_PER_PAGE = page_size
        _job_pool, _event_pool, _post_pool, _pp_pool, people_pool, _ach_pool = [], [], [], [], [], []
        _pach_pool, _port_pool = [], []

    feed_items = []
    # Achievement / profile-achievement / portfolio cards all pull from the
    # same visual family — guard against two of them landing back-to-back by
    # requiring at least one other feed item between any two of this trio.
    _SPECIAL_CARD_TYPES = {'achievement', 'profile_achievement', 'portfolio'}
    for i in range(1, page_size + 1):
        # Business page suggestion at slot 6 (every 8 slots)
        if (i % 8 == 6
                and suggestion_businesses
                and _business_injected < _max_business_this_page):
            _biz_group = suggestion_businesses[:3]
            del suggestion_businesses[:3]
            feed_items.append({'type': 'business_suggestion', 'data': _biz_group})
            _business_injected += 1

        # Business post (update) and Profile post (personal update) —
        # alternating slots so both surface in the feed, highest-relevance
        # ranked items lead within each pool.
        if i % 6 == 1 and _post_pool:
            feed_items.append({'type': 'business_post', 'data': _post_pool.pop(0)})
        if i % 6 == 4 and _pp_pool:
            feed_items.append({'type': 'profile_post', 'data': _pp_pool.pop(0)})

        _last_type = feed_items[-1]['type'] if feed_items else None

        # Achievement highlight at slot 11 (every 10 slots, offset from suggestions)
        if (i % 10 == 1
                and _ach_pool
                and _ach_injected < _MAX_ACH_PER_PAGE
                and _last_type not in _SPECIAL_CARD_TYPES):
            feed_items.append({'type': 'achievement', 'data': _ach_pool.pop(0)})
            _ach_injected += 1
            _last_type = 'achievement'

        # Personal profile achievement at slot 4 (every 10 slots)
        if (i % 10 == 4
                and _pach_pool
                and _pach_injected < _MAX_PACH_PER_PAGE
                and _last_type not in _SPECIAL_CARD_TYPES):
            feed_items.append({'type': 'profile_achievement', 'data': _pach_pool.pop(0)})
            _pach_injected += 1
            _last_type = 'profile_achievement'

        # Personal portfolio piece / project at slot 8 (every 10 slots)
        if (i % 10 == 8
                and _port_pool
                and _port_injected < _MAX_PORT_PER_PAGE
                and _last_type not in _SPECIAL_CARD_TYPES):
            feed_items.append({'type': 'portfolio', 'data': _port_pool.pop(0)})
            _port_injected += 1
            _last_type = 'portfolio'

        # Market ad — fills most slots (1,2,3,4,5,6 of every 10) normally,
        # or every slot when a category filter is active.
        _market_slot_match = True if _is_market_filtered else (i % 10 in (2, 3, 5, 6, 8, 9))
        if (_market_slot_match
                and _market_pool
                and _market_injected < _MAX_MARKET_PER_PAGE):
            feed_items.append({'type': 'market', 'data': _market_pool.pop(0)})
            _market_injected += 1

        # Job card at slot 5, 12 …
        if (i % 7 == 5
                and _job_pool
                and _job_injected < _MAX_JOB_PER_PAGE):
            feed_items.append({'type': 'job', 'data': _job_pool.pop(0)})
            _job_injected += 1

        # Event card at slot 7, 16 …
        if (i % 9 == 7
                and _event_pool
                and _event_injected < _MAX_EVENT_PER_PAGE):
            feed_items.append({'type': 'event', 'data': _event_pool.pop(0)})
            _event_injected += 1

        # People-to-follow suggestion at slot 9, 18 …
        if (i % 9 == 3
                and people_pool
                and _people_injected < _MAX_PEOPLE_PER_PAGE):
            _people_group = people_pool[:3]
            del people_pool[:3]
            feed_items.append({'type': 'people_suggestion', 'data': _people_group})
            _people_injected += 1

    # ── Randomize final ordering ────────────────────────────────────────────
    # The slot-based build above only controls *how many* of each card type
    # appear and paces them across virtual slots — it still produced a fairly
    # fixed shape (e.g. a business/profile post always leading). Shuffle the
    # assembled list so every card type (posts, achievements, portfolio,
    # projects, jobs, events, suggestions…) can land anywhere, then repair
    # any achievement/profile_achievement/portfolio pair that ended up
    # adjacent so that constraint still holds after the shuffle.
    random.shuffle(feed_items)
    for _idx in range(1, len(feed_items)):
        if (feed_items[_idx]['type'] in _SPECIAL_CARD_TYPES
                and feed_items[_idx - 1]['type'] in _SPECIAL_CARD_TYPES):
            for _j in range(_idx + 1, len(feed_items)):
                if feed_items[_j]['type'] not in _SPECIAL_CARD_TYPES:
                    feed_items[_idx], feed_items[_j] = feed_items[_j], feed_items[_idx]
                    break

    return feed_items, next_cursor


# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def home(request):
    profile = Profile.objects.get(user=request.user)

    if not profile.onboarding_completed:
        return redirect('onboarding')

    following_ids = list(profile.followings.values_list('user', flat=True))

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).count()

    # Optional market category filter (?market_category=phones, etc.)
    market_category = request.GET.get('market_category', 'all')

    # First page of the feed (market ads, jobs, events, user suggestions)
    feed, next_cursor = _get_feed_page(
        request.user, following_ids, market_category=market_category
    )

    # Only pass counts — lists are loaded lazily via HTMX
    sidebar_following_count = profile.followings.count()
    sidebar_follower_count  = profile.followers.count()

    # ── Right-sidebar "Grow your business" card — only for users without one.
    # If the user already owns a business page, show that page's stats
    # instead of the "create a page" pitch. listing_count/follower_count are
    # read-only @properties already defined on BusinessPage.
    user_business_pages = (
        BusinessPage.objects.filter(owner=request.user, is_active=True)
        .order_by('-created_at')
    )
    user_business_page_count = user_business_pages.count()
    primary_business_page = user_business_pages.first()

    # ── Right-sidebar "Suggested for you" — business pages, ranked by
    #    relevance to this viewer's profession/skills/interests/location ────
    _sidebar_keywords, _sidebar_location_tokens = _profile_feed_signal(request.user, profile)

    followed_business_ids = set(
        BusinessPage.objects.filter(followers=request.user).values_list('page_id', flat=True)
    )
    _sidebar_page_candidates = list(
        BusinessPage.objects
        .filter(is_active=True)
        .exclude(owner=request.user)
        .exclude(page_id__in=followed_business_ids)
        .select_related('owner')
        .order_by('?')[:24]
    )
    suggested_pages = _ranked(
        _sidebar_page_candidates, _sidebar_keywords, _sidebar_location_tokens,
        blob_fn=lambda bp: ' '.join(filter(None, [
            bp.name, bp.tagline, bp.description,
            bp.get_category_display(), bp.get_page_type_display(),
        ])),
        location_fn=lambda bp: bp.location,
        created_fn=lambda bp: bp.created_at,
        limit=3,
    )

    # ── Right-sidebar "People you may know" — ranked the same way ────────────
    _sidebar_people_candidates = list(
        User.objects.exclude(id__in=following_ids)
               .exclude(id=request.user.id)
               .select_related('profile')
               .order_by('?')[:24]
    )
    _sidebar_people_candidates = [u for u in _sidebar_people_candidates if hasattr(u, 'profile')]
    users = _ranked(
        _sidebar_people_candidates, _sidebar_keywords, _sidebar_location_tokens,
        blob_fn=lambda u: ' '.join(filter(None, [
            u.profile.profession, u.profile.member_type_label, u.profile.bio,
            ' '.join(u.profile.interests or []),
        ])),
        location_fn=lambda u: u.profile.location,
        limit=3,
    )

    # Attach "X and Y other mutual connections" info to each suggestion for
    # the "People you may know" sidebar widget (mirrors the profile page's
    # mutual_followings/mutual_count pattern).
    _my_following = profile.followings.all()
    for _u in users:
        _mutuals_qs = _my_following.filter(followings=_u.profile)
        _u.pymk_mutual_profile = _mutuals_qs.first()
        _u.pymk_mutual_count = _mutuals_qs.count()

    # ── Recent DM conversation partners (home-page bubble row) ───────────────
    from django.db.models import Max
    _dm_qs = (
        Message.objects
        .filter(Q(sender=request.user) | Q(receiver=request.user))
        .values('sender', 'receiver')
        .annotate(latest=Max('created_at'))
        .order_by('-latest')
    )
    _seen, _dm_ids = set(), []
    for row in _dm_qs:
        other_id = row['receiver'] if row['sender'] == request.user.id else row['sender']
        if other_id not in _seen:
            _seen.add(other_id)
            _dm_ids.append(other_id)
        if len(_dm_ids) >= 10:
            break
    _id_order = {uid: i for i, uid in enumerate(_dm_ids)}
    recent_dm_users = sorted(
        User.objects.filter(id__in=_dm_ids).select_related('profile'),
        key=lambda u: _id_order.get(u.id, 999)
    )

    return render(request, 'home.html', {
        'posts_with_ads':             feed,
        'next_cursor':                next_cursor,
        'unread_follow_count':        unread_follow_count,
        'users':                      users,
        'suggested_pages':            suggested_pages,
        'following_ids':              following_ids,
        'sidebar_following_count':    sidebar_following_count,
        'sidebar_follower_count':     sidebar_follower_count,
        'user_business_page_count':   user_business_page_count,
        'primary_business_page':      primary_business_page,
        'viewer_primary_business_page': primary_business_page,
        'recent_dm_users':            recent_dm_users,
        'vibe_choices': [
            {'type': t, 'emoji': BusinessPostVibe.VIBE_EMOJIS[t], 'label': label.split(' ', 1)[-1]}
            for t, label in BusinessPostVibe.VIBE_CHOICES
        ],
        'all_categories':             [
            {'key': k, 'label': l, 'icon': Market.CATEGORY_ICONS.get(k, '📦')}
            for k, l in Market.CATEGORY_CHOICES
        ],
        'selected_market_category':   market_category,
    })

# ─────────────────────────────────────────────────────────────────────────────
# HTMX sidebar connections endpoint
# GET /sidebar/connections/?type=following|followers&page=<int>
# Returns a partial list of sidebar user rows (20 per page).
# ─────────────────────────────────────────────────────────────────────────────

_SIDEBAR_PAGE_SIZE = 20

@login_required(login_url='/')
@require_GET
def sidebar_connections(request):
    """
    Paginated HTMX endpoint for the right-sidebar Following / Followers lists.
    Handles 10 000+ connections gracefully via cursor-based offset pagination.
    """
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    conn_type = request.GET.get('type', 'following')   # 'following' | 'followers'
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    profile = get_object_or_404(Profile, user=request.user)

    # profile.followers / profile.followings are a M2M of Profile objects.
    # Each Profile already IS the profile — select_related('user') joins the
    # auth_user row. 'user__profile' would be a circular self-join back to
    # the same profile table and is incorrect here.
    if conn_type == 'followers':
        qs = (
            profile.followers
            .select_related('user')
            .order_by('user__username')
        )
    else:
        qs = (
            profile.followings
            .select_related('user')
            .order_by('user__username')
        )

    # Exclude the logged-in user themselves
    qs = qs.exclude(user=request.user)

    total    = qs.count()
    offset   = (page - 1) * _SIDEBAR_PAGE_SIZE
    profiles = list(qs[offset: offset + _SIDEBAR_PAGE_SIZE])
    has_more = (offset + _SIDEBAR_PAGE_SIZE) < total

    html = render_to_string(
        'snippet/sidebar_connections_partial.html',
        {
            'profiles':  profiles,
            'has_more':  has_more,
            'next_page': page + 1,
            'conn_type': conn_type,
            'request':   request,
        },
        request=request,
    )
    return HttpResponse(html)


# ─────────────────────────────────────────────────────────────────────────────
# HTMX profile sidebar connections endpoint
# GET /profile-sidebar/<username>/connections/?type=following|followers&page=<n>
# Scoped to the VIEWED profile's own following/followers, not request.user.
# Works for authenticated viewers; public profiles visible to anyone.
# ─────────────────────────────────────────────────────────────────────────────

@require_GET
def profile_sidebar_connections(request, username):
    """
    Paginated HTMX endpoint for the profile page right-sidebar
    Following / Followers lists.  Always scoped to the profile being *viewed*
    (``username``), not the logged-in user, so visitors see the profile owner's
    network — not their own.
    """
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    profile_user   = get_object_or_404(User, username=username)
    viewed_profile = get_object_or_404(Profile, user=profile_user)

    conn_type = request.GET.get('type', 'following')   # 'following' | 'followers'
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    if conn_type == 'followers':
        qs = (
            viewed_profile.followers
            .select_related('user')
            .order_by('user__username')
        )
    else:
        qs = (
            viewed_profile.followings
            .select_related('user')
            .order_by('user__username')
        )

    total    = qs.count()
    offset   = (page - 1) * _SIDEBAR_PAGE_SIZE
    profiles = list(qs[offset: offset + _SIDEBAR_PAGE_SIZE])
    has_more = (offset + _SIDEBAR_PAGE_SIZE) < total

    html = render_to_string(
        'snippet/sidebar_connections_partial.html',
        {
            'profiles':         profiles,
            'has_more':         has_more,
            'next_page':        page + 1,
            'conn_type':        conn_type,
            'request':          request,
            'profile_username': username,   # tells partial to use profile-scoped URL
        },
        request=request,
    )
    return HttpResponse(html)


# ─────────────────────────────────────────────────────────────────────────────
# HTMX infinite-scroll endpoint
# GET /feed/more/?cursor=<float_unix_timestamp>
# Returns the next page partial (posts + new sentinel) or 204 if exhausted.
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_GET
def feed_load_more(request):
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    profile       = Profile.objects.get(user=request.user)
    following_ids = list(profile.followings.values_list('user', flat=True))

    # Dedup tracking — clients send comma-separated IDs of already-seen cards
    seen_users_raw   = request.GET.get('seen_users', '')
    seen_markets_raw = request.GET.get('seen_markets', '')
    seen_jobs_raw    = request.GET.get('seen_jobs', '')
    seen_events_raw  = request.GET.get('seen_events', '')
    seen_business_raw = request.GET.get('seen_businesses', '')
    seen_people_raw  = request.GET.get('seen_people', '')
    seen_posts_raw   = request.GET.get('seen_posts', '')
    market_category  = request.GET.get('market_category', 'all')

    # cursor doubles as the market_offset once a category filter is active
    # (see _get_feed_page). Non-numeric / missing cursor just means page 1.
    try:
        market_offset = int(request.GET.get('cursor') or 0)
    except (TypeError, ValueError):
        market_offset = 0

    seen_suggestion_ids = set(seen_users_raw.split(','))   if seen_users_raw   else set()
    seen_market_ids     = set(seen_markets_raw.split(',')) if seen_markets_raw else set()
    seen_job_ids        = set(seen_jobs_raw.split(','))    if seen_jobs_raw    else set()
    seen_event_ids      = set(seen_events_raw.split(','))  if seen_events_raw  else set()
    seen_business_ids   = set(seen_business_raw.split(',')) if seen_business_raw else set()
    seen_people_ids     = set(seen_people_raw.split(','))  if seen_people_raw  else set()
    seen_post_ids       = set(seen_posts_raw.split(','))   if seen_posts_raw   else set()

    feed, next_cursor = _get_feed_page(
        request.user, following_ids,
        seen_suggestion_ids=seen_suggestion_ids,
        seen_market_ids=seen_market_ids,
        seen_job_ids=seen_job_ids,
        seen_event_ids=seen_event_ids,
        seen_business_ids=seen_business_ids,
        seen_people_ids=seen_people_ids,
        seen_post_ids=seen_post_ids,
        market_category=market_category,
        market_offset=market_offset,
    )

    _is_fresh = request.GET.get('fresh') == '1'

    if not feed:
        if _is_fresh:
            # Category switch with zero matching products — show a friendly
            # empty state instead of silently leaving the grid blank.
            return render(request, 'snippet/feed_posts_partial.html', {
                'posts_with_ads': [],
                'next_cursor':    None,
                'following_ids':  following_ids,
                'empty_category': True,
                'selected_market_category': market_category,
            })
        return HttpResponse(status=204)

    return render(request, 'snippet/feed_posts_partial.html', {
        'posts_with_ads': feed,
        'next_cursor':    next_cursor,
        'following_ids':  following_ids,
        'selected_market_category': market_category,
        'vibe_choices': [
            {'type': t, 'emoji': BusinessPostVibe.VIBE_EMOJIS[t], 'label': label.split(' ', 1)[-1]}
            for t, label in BusinessPostVibe.VIBE_CHOICES
        ],
    })


def _safe_pic_url(user_obj):
    """
    Return picture URL safely. Works in both debug (ImageField) and
    production (CloudinaryField). Always returns a full https URL.
    """
    try:
        if hasattr(user_obj, 'profile') and user_obj.profile.picture:
            pic = user_obj.profile.picture
            if hasattr(pic, 'public_id') and pic.public_id:
                return cloudinary.CloudinaryImage(pic.public_id).build_url(secure=True)
            if hasattr(pic, 'url') and pic.url:
                url = pic.url
                if url.startswith('http://'):
                    url = 'https://' + url[7:]
                return url
    except Exception:
        pass
    return ''





# ─────────────────────────────────────────────────────────────────────────────
# Profile View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def profile(request, username):
    user    = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked        = False
    viewer_is_blocked = False

    if request.user.is_authenticated and request.user != user:
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()

    if viewer_is_blocked:
        return render(request, 'blocked.html', {'blocked_by': user})

    # ── Logged-in viewer's own right-sidebar widget data ─────────────────────
    # This mirrors the home page's right sidebar (profile card, suggested
    # users, following/followers counts) and is always about request.user,
    # regardless of which profile page is currently being viewed.
    viewer_profile          = request.user.profile
    viewer_following_ids    = list(viewer_profile.followings.values_list('user', flat=True))
    viewer_following_count  = viewer_profile.followings.count()
    viewer_follower_count   = viewer_profile.followers.count()
    sidebar_suggested_users = list(
        User.objects.exclude(id__in=viewer_following_ids)
               .exclude(id=request.user.id)
               .order_by('?')[:3]
    )

    # ── Viewer's own business page — for the "Grow your business" /
    # "Your business page" sidebar widget (always about request.user).
    # listing_count/follower_count are read-only @properties already
    # defined on BusinessPage.
    viewer_business_pages = (
        BusinessPage.objects.filter(owner=request.user, is_active=True)
        .order_by('-created_at')
    )
    viewer_business_page_count = viewer_business_pages.count()
    viewer_primary_business_page = viewer_business_pages.first()

    if is_blocked:
        context = {
            'user': user, 'profile': profile, 'posts': [],
            'current_profile': request.user.profile if request.user.is_authenticated else None,
            'total_view': 0, 'total_like_recieved': 0,
            'total_comments_received': 0, 'mutual_followings': None,
            'mutual_count': 0, 'is_blocked': True,
            'can_view_details': False,
            'is_own_profile': False,
            'business_pages': BusinessPage.objects.none(),
            'business_page_count': 0,
            'business_page_previews': [],
            'wishlist_ids': set(),
            'suggested_pages': [],
            'saved_products': [],
            'saved_products_count': 0,
            'user_reviews': [],
            'user_reviews_count': 0,
            'profile_followers': [],
            'profile_followers_count': 0,
            'profile_following': [],
            'profile_following_count': 0,
            'viewer_following_row_ids': set(),
            'viewer_following_count':  viewer_following_count,
            'viewer_follower_count':   viewer_follower_count,
            'sidebar_suggested_users': sidebar_suggested_users,
            'viewer_business_page_count':   viewer_business_page_count,
            'viewer_primary_business_page': viewer_primary_business_page,
            'profile_completion_pct': 0,
            'profile_completion_missing': [],
            'profile_skills': [],
            'user_reviews': [],
            'professional_experience': [], 'professional_education': [],
            'professional_services': [], 'professional_portfolio': [],
            'professional_projects': [], 'professional_achievements': [],
            'professional_posts': [], 'professional_products': [],
            'professional_jobs': [], 'suggested_professional_sections': [],
            'professional_section_choices': Profile.PROFESSIONAL_SECTION_CHOICES,
        }
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(request, 'profile.html', context)
        return render(request, 'profile.html', context)


    mutual_followings = None
    mutual_count      = 0
    if request.user.is_authenticated and request.user != user:
        my_following      = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count      = my_following.filter(followings=profile).count()

    # ── Privacy: determine if viewer can see personal details ───────────────
    can_view_details = profile.can_view_details(request.user)

    # Only pass counts — the full lists are loaded lazily via HTMX
    # (profile_sidebar_connections endpoint), matching the home feed pattern.
    sidebar_following_count = profile.followings.count()
    sidebar_follower_count  = profile.followers.count()

    is_own_profile = request.user.is_authenticated and request.user == user
    is_following   = False
    if request.user.is_authenticated and not is_own_profile:
        is_following = current_profile_qs_exists = request.user.profile.followings.filter(pk=profile.pk).exists()

    # ── Business pages owned by this user ────────────────────────────────────
    # Instead of rendering each page's full details on the profile, we show a
    # lightweight preview: that page's featured product/market card plus a
    # link through to the full business page.
    business_pages = (
        BusinessPage.objects.filter(owner=user, is_active=True)
        .order_by('-created_at')
        .prefetch_related('market_listings__images')
    )
    business_page_count = business_pages.count()

    business_page_previews = []
    for page in business_pages:
        featured_listing = page.market_listings.order_by('-posted_on').first()
        business_page_previews.append({
            'page': page,
            'listing': featured_listing,
        })

    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    # ── Right-sidebar "Suggestions for you" — business pages, not users ──────────
    suggested_pages = []
    if request.user.is_authenticated:
        followed_business_ids = set(
            BusinessPage.objects.filter(followers=request.user).values_list('page_id', flat=True)
        )
        suggested_pages = list(
            BusinessPage.objects
            .filter(is_active=True)
            .exclude(owner=request.user)
            .exclude(page_id__in=followed_business_ids)
            .select_related('owner')
            .order_by('-created_at')[:5]
        )

    # ── Saved items for the "Saved" tab (owner only — wishlist is private) ──────
    saved_products = []
    saved_products_count = 0
    if is_own_profile:
        saved_qs = (
            Wishlist.objects.filter(user=request.user)
            .select_related('product')
            .prefetch_related('product__images')
            .order_by('-created_at')
        )
        saved_products_count = saved_qs.count()
        saved_products = [item.product for item in saved_qs[:8] if item.product_id]

    # ── Reviews this user has written (for the "Reviews" tab) ───────────────────
    user_reviews_qs = (
        ProductReview.objects.filter(user=user)
        .select_related('product')
        .prefetch_related('product__images')
        .order_by('-created_at')
    )
    user_reviews_count = user_reviews_qs.count()
    user_reviews = list(user_reviews_qs[:10])

    # ── Followers / Following for the "Followers" and "Following" tabs ──────────
    # Small first page rendered directly (fast, no extra request); the full
    # lists live at the existing 'followers' / 'following' pages for "View All".
    profile_followers_qs = (
        profile.followers.select_related('user').order_by('user__username')
    )
    profile_following_qs = (
        profile.followings.select_related('user').order_by('user__username')
    )
    profile_followers_count = profile_followers_qs.count()
    profile_following_count = profile_following_qs.count()
    profile_followers = list(profile_followers_qs[:12])
    profile_following = list(profile_following_qs[:12])

    # So each row can show "Following" vs "Follow" when the viewer is logged
    # in (does the viewer already follow this row's user?).
    viewer_following_row_ids = set()
    if request.user.is_authenticated:
        viewer_following_row_ids = set(
            request.user.profile.followings.values_list('user_id', flat=True)
        )

    # Call button on each row uses that row's own phone number, respecting
    # their own privacy setting (same can_view_details check used for the
    # main profile's own contact info) — never expose a number they've hidden.
    for row_profile in profile_followers + profile_following:
        row_profile.call_phone = (
            row_profile.phone if row_profile.phone and row_profile.can_view_details(request.user) else ''
        )

    # Wishlist ("likes") counts per listing — queried separately so we don't
    # depend on a specific reverse-relation name from the Wishlist model.
    listing_ids = [p.product_id for p in saved_products]
    wishlist_counts = {}
    if listing_ids:
        for row in (Wishlist.objects.filter(product_id__in=listing_ids)
                    .values('product_id').annotate(c=Count('id'))):
            wishlist_counts[row['product_id']] = row['c']
    for product in saved_products:
        product.like_count = wishlist_counts.get(product.product_id, 0)

    # ── LinkedIn-style "profile strength" meter (owner-only nudge) ───────────
    # Each of these fields contributes equally toward a completeness score,
    # mirroring LinkedIn's profile-strength bar. Missing items are surfaced
    # as quick "Add X" prompts that deep-link into the edit sheet.
    completion_checks = [
        (bool(profile.picture), 'Add a profile photo'),
        (bool(profile.cover_photo), 'Add a cover photo'),
        (bool(profile.bio), 'Write an About summary'),
        (bool(profile.profession), 'Add a headline'),
        (bool(profile.location), 'Add your location'),
        (bool(profile.website), 'Add a website'),
        (bool(profile.phone), 'Add a phone number'),
        (business_page_count > 0, 'Create a business page'),
    ]
    completion_done = sum(1 for done, _ in completion_checks if done)
    profile_completion_pct = round(completion_done * 100 / len(completion_checks))
    profile_completion_missing = [label for done, label in completion_checks if not done][:3]

    # ── LinkedIn-style "skills" chips ─────────────────────────────────────────
    # There's no dedicated skills model, so we surface the closest real signal:
    # the user's stated profession plus the categories of businesses they run.
    profile_skills = []
    if profile.profession:
        profile_skills.append(profile.profession)
    for preview in business_page_previews:
        cat = preview['page'].get_category_display()
        if cat and cat not in profile_skills:
            profile_skills.append(cat)
    profile_skills = profile_skills[:8]

    # ── Professional profile sections (Services, Portfolio, Projects,
    # Achievements, Jobs, Products, Posts) — these now live directly on the
    # Profile, independent of any BusinessPage. Shown/hidden per-section via
    # profile.show_services / show_portfolio / etc., which read
    # profile.enabled_sections (defaults suggested from profile.member_type).
    professional_experience   = list(profile.experiences.prefetch_related('vibes')) if profile.show_experience else []
    professional_education    = list(profile.education_history.prefetch_related('vibes')) if profile.show_education else []
    professional_services     = list(profile.services.filter(is_active=True).prefetch_related('vibes')) if profile.show_services else []
    professional_portfolio    = list(profile.portfolio_items.filter(kind=ProfilePortfolioItem.KIND_PORTFOLIO).prefetch_related('vibes')) if profile.show_portfolio else []
    professional_projects     = list(profile.portfolio_items.filter(kind=ProfilePortfolioItem.KIND_PROJECT).prefetch_related('vibes')) if profile.show_projects else []
    professional_achievements = list(profile.achievements.prefetch_related('vibes')) if profile.show_achievements else []

    # Annotate each of these sub-items with the viewer's own reaction — same
    # shape as the professional_posts annotation below — so their engagement
    # bars can render a filled-in reaction without an extra query per card.
    for _items in (professional_experience, professional_education, professional_services,
                   professional_portfolio, professional_projects, professional_achievements):
        for _it in _items:
            _it.viewer_vibe = None
            _it.viewer_vibe_emoji = ''
            if request.user.is_authenticated:
                _mine = next((v for v in _it.vibes.all() if v.user_id == request.user.pk), None)
                if _mine:
                    _it.viewer_vibe = _mine.vibe_type
                    _it.viewer_vibe_emoji = ProfilePostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')
    professional_posts_qs = (
        profile.professional_posts.prefetch_related('images', 'poll__options', 'vibes')
        if profile.is_professional else ProfilePost.objects.none()
    )
    professional_posts = list(professional_posts_qs[:20])
    # Annotate each post with the viewer's own reaction — same shape the
    # business page's Posts tab uses — so the ported kbiz-vibe-popover
    # markup can render identically without extra per-post queries.
    for _pp in professional_posts:
        _pp.viewer_vibe = None
        _pp.viewer_vibe_emoji = ''
        if request.user.is_authenticated:
            _mine = next((v for v in _pp.vibes.all() if v.user_id == request.user.pk), None)
            if _mine:
                _pp.viewer_vibe = _mine.vibe_type
                _pp.viewer_vibe_emoji = ProfilePostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')
    professional_products = (
        list(Market.objects.filter(product_owner=user, business_page__isnull=True).prefetch_related('images')[:20])
        if profile.show_products else []
    )
    professional_jobs = (
        list(JobVacancy.objects.filter(posted_by=user, business_page__isnull=True)[:20])
        if profile.show_jobs_section else []
    )
    # Suggested (not-yet-enabled) sections, for the owner's "Add a section" prompt.
    suggested_professional_sections = []
    if is_own_profile and profile.member_type:
        suggested_professional_sections = [
            s for s in Profile.default_sections_for(profile.member_type)
            if s not in (profile.enabled_sections or [])
        ]

    context = {
        'user': user, 'profile': profile,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': False,
        'can_view_details': can_view_details,
        'is_own_profile': is_own_profile,
        'profile_completion_pct': profile_completion_pct,
        'profile_completion_missing': profile_completion_missing,
        'profile_skills': profile_skills,
        'is_following': is_following,
        'sidebar_following_count': sidebar_following_count,
        'sidebar_follower_count':  sidebar_follower_count,
        'business_pages': business_pages,
        'business_page_count': business_page_count,
        'business_page_previews': business_page_previews,
        'wishlist_ids': wishlist_ids,
        'suggested_pages': suggested_pages,
        'saved_products': saved_products,
        'saved_products_count': saved_products_count,
        'user_reviews': user_reviews,
        'user_reviews_count': user_reviews_count,
        'profile_followers': profile_followers,
        'profile_followers_count': profile_followers_count,
        'profile_following': profile_following,
        'profile_following_count': profile_following_count,
        'viewer_following_row_ids': viewer_following_row_ids,
        'viewer_following_count':  viewer_following_count,
        'viewer_follower_count':   viewer_follower_count,
        'sidebar_suggested_users': sidebar_suggested_users,
        'viewer_business_page_count':   viewer_business_page_count,
        'viewer_primary_business_page': viewer_primary_business_page,
        'member_type_edit_schema': _member_type_edit_schema(profile) if request.user == user else [],
        'professional_experience':   professional_experience,
        'professional_education':    professional_education,
        'professional_services':     professional_services,
        'professional_portfolio':    professional_portfolio,
        'professional_projects':     professional_projects,
        'professional_achievements': professional_achievements,
        'professional_posts':        professional_posts,
        'professional_products':     professional_products,
        'professional_jobs':         professional_jobs,
        'suggested_professional_sections': suggested_professional_sections,
        'professional_section_choices': Profile.PROFESSIONAL_SECTION_CHOICES,
        'vibe_choices': [
            {'type': t, 'emoji': ProfilePostVibe.VIBE_EMOJIS[t], 'label': label.split(' ', 1)[-1]}
            for t, label in ProfilePostVibe.VIBE_CHOICES
        ],
        'market_categories': Market.CATEGORY_CHOICES,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'profile.html', context)
    return render(request, 'profile.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Update Profile View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def update_profile(request, username):
    # Security: only the owner can update their own profile
    user    = request.user
    profile = request.user.profile

    if request.method == 'POST':
        fname            = request.POST.get('fname', '').strip()
        lname            = request.POST.get('lname', '').strip()
        phone            = request.POST.get('phone', '').strip()
        address          = request.POST.get('address', '').strip()
        location         = request.POST.get('location', '').strip()
        image            = request.FILES.get('image')
        cover_image      = request.FILES.get('cover_image')
        bio              = request.POST.get('bio', '').strip()
        website          = request.POST.get('website', '').strip()
        privacy_level    = request.POST.get('privacy_level', '').strip()
        gender           = request.POST.get('gender', '').strip()
        dob_raw          = request.POST.get('date_of_birth', '').strip()
        # Checkboxes: present in POST = True, absent = False
        show_gender      = 'show_gender' in request.POST
        show_dob         = 'show_dob'    in request.POST
        # Kishi community fields
        profession       = request.POST.get('profession',       '').strip()

        # Member type (only touched if the edit form actually included it —
        # the main profile-edit form doesn't, onboarding/its own "edit" link do)
        member_type_submitted = 'member_type' in request.POST
        member_type = request.POST.get('member_type', '').strip()

        # ── Whitelist validation ─────────────────────────────────
        VALID_PRIVACY = {'public', 'followers_only', 'private'}
        if privacy_level not in VALID_PRIVACY:
            privacy_level = None

        VALID_GENDERS = {'male', 'female', 'non_binary', 'prefer_not_to_say', ''}
        if gender not in VALID_GENDERS:
            gender = None

        import datetime
        date_of_birth = None
        dob_changed   = False
        if dob_raw:
            try:
                date_of_birth = datetime.date.fromisoformat(dob_raw)
                dob_changed   = True
            except ValueError:
                pass  # ignore invalid date silently

        try:
            profile_dirty = False

            # Save name fields independently (don't require both)
            if fname is not None:
                user.first_name = fname
                profile_dirty = True  # triggers full_name sync via profile.save()
            if lname is not None:
                user.last_name = lname
                profile_dirty = True
            if fname is not None or lname is not None:
                user.save()

            profile.phone    = phone;            profile_dirty = True
            profile.address  = address;          profile_dirty = True
            profile.location = location;         profile_dirty = True
            profile.bio      = bio;              profile_dirty = True
            profile.website  = website;          profile_dirty = True
            if privacy_level:      profile.privacy_level  = privacy_level;    profile_dirty = True
            if gender is not None: profile.gender         = gender;           profile_dirty = True
            if dob_changed:        profile.date_of_birth  = date_of_birth;    profile_dirty = True

            # Always update visibility toggles (checkbox — present/absent)
            profile.show_gender = show_gender
            profile.show_dob    = show_dob
            profile_dirty = True

            # Kishi community fields — always write (empty string clears the field)
            profile.profession       = profession
            profile_dirty = True

            if member_type_submitted:
                valid_types = {k for k, _ in MEMBER_TYPE_CHOICES}
                if member_type in valid_types:
                    # Each dynamic field is rendered with a name namespaced to its
                    # member type (mt_<member_type>__<key>) so that fields from the
                    # other (CSS-hidden, but still present in the DOM and therefore
                    # still submitted) member-type fieldsets don't collide with the
                    # currently selected one, or with generic fields like
                    # "profession"/"location" that share the same key.
                    raw_data = {}
                    cv_field_name = None
                    for field in MEMBER_TYPE_SCHEMA[member_type]['fields']:
                        key = field['key']
                        posted_name = f'mt_{member_type}__{key}'
                        if field['type'] == 'file':
                            cv_field_name = posted_name
                            continue
                        if field['type'] == 'days_hours':
                            raw_data[key + '__days'] = request.POST.getlist(posted_name + '__days')
                            raw_data[key + '__open'] = request.POST.get(posted_name + '__open', '')
                            raw_data[key + '__close'] = request.POST.get(posted_name + '__close', '')
                            continue
                        raw_data[key] = request.POST.get(posted_name, '')
                        if field['type'] == 'select_other':
                            raw_data[key + '__other'] = request.POST.get(posted_name + '__other', '')
                    profile.member_type = member_type
                    profile.member_type_data = sanitize_member_type_data(member_type, raw_data)

                    cv_file = request.FILES.get(cv_field_name) if cv_field_name else None
                    if cv_file:
                        validate_file_extension_cv = os.path.splitext(cv_file.name)[1].lower()
                        if validate_file_extension_cv not in {'.pdf', '.doc', '.docx'}:
                            raise ValueError('CV must be a PDF, DOC, or DOCX file.')
                        validate_file_size(cv_file, max_size_mb=5)
                        profile.member_type_cv = cv_file
                        profile.member_type_cv_name = cv_file.name
                    elif request.POST.get('clear_cv') == '1' and profile.member_type_cv:
                        profile.member_type_cv.delete(save=False)
                        profile.member_type_cv = None
                        profile.member_type_cv_name = ''
                    profile_dirty = True
                elif member_type == '':
                    profile.member_type = ''
                    profile.member_type_data = {}
                    if profile.member_type_cv:
                        profile.member_type_cv.delete(save=False)
                    profile.member_type_cv = None
                    profile.member_type_cv_name = ''
                    profile_dirty = True

            # ── Professional sections (Services, Portfolio, Projects,
            # Achievements, Jobs) + "sells products" toggle. Only touched when
            # explicitly submitted (the "Manage professional sections" panel
            # on the profile page), so the main profile-edit form is unaffected.
            if 'sections_submitted' in request.POST:
                profile.enabled_sections = [
                    s for s in request.POST.getlist('sections')
                    if s in Profile.VALID_PROFESSIONAL_SECTIONS
                ]
                profile.sells_products = request.POST.get('sells_products') in ('1', 'true', 'on')
                profile_dirty = True
            elif member_type_submitted and member_type in {k for k, _ in MEMBER_TYPE_CHOICES} and not profile.enabled_sections:
                # First time a member type is chosen — seed sensible defaults
                # (the owner can still fine-tune them from "Manage sections").
                profile.enabled_sections = Profile.default_sections_for(member_type)
                profile.sells_products = member_type in Profile.MEMBER_TYPES_SELLING_BY_DEFAULT
                profile_dirty = True

            if profile_dirty:
                profile.save()

            if image:
                profile.picture = image
                profile.save()

            if cover_image:
                allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
                if cover_image.content_type not in allowed_types:
                    raise ValueError('Only JPEG, PNG, WebP or GIF images are allowed for the cover photo.')
                if cover_image.size > 10 * 1024 * 1024:
                    raise ValueError('Cover photo must be under 10MB.')
                if getattr(settings, 'USE_CLOUDINARY', False) and profile.cover_photo:
                    try:
                        import cloudinary.uploader as _cu
                        _cu.destroy(str(profile.cover_photo))
                    except Exception:
                        pass
                profile.cover_photo = cover_image
                profile.save()
            elif request.POST.get('clear_cover') == '1' and profile.cover_photo:
                if getattr(settings, 'USE_CLOUDINARY', False):
                    try:
                        import cloudinary.uploader as _cu
                        _cu.destroy(str(profile.cover_photo))
                    except Exception:
                        pass
                profile.cover_photo = None
                profile.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'data': {
                        'first_name':      user.first_name,
                        'last_name':       user.last_name,
                        'bio':             profile.bio,
                        'phone':           profile.phone,
                        'address':         profile.address,
                        'location':        profile.location,
                        'picture_url':     profile.picture.url,
                        'cover_url':       profile.get_cover_url,
                        'website':         profile.website,
                        'privacy_level':   profile.privacy_level,
                        'gender':          profile.gender,
                        'date_of_birth':   profile.date_of_birth.isoformat() if profile.date_of_birth else '',
                        'show_gender':     profile.show_gender,
                        'show_dob':        profile.show_dob,
                        'profession':      profile.profession,
                        'member_type':     profile.member_type,
                    },
                    'message': 'Profile updated successfully!'
                })
            else:
                messages.info(request, 'Profile Updated Successfully')
                return redirect('profile', username=request.user.username)

        except (ValueError, _ModelValidationError) as e:
            # Expected validation failures (bad CV type/size, etc.) — safe to show verbatim.
            error_message = str(e).strip("[]'\"") or 'Please check your input and try again.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_message})
            else:
                messages.error(request, error_message)
                return redirect('profile', username=request.user.username)
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Failed to update profile.'})
            else:
                messages.error(request, 'Failed to update profile. Please try again.')
                return redirect('profile', username=request.user.username)

    return render(request, 'update_profile.html', {'profile': profile})


# ─────────────────────────────────────────────────────────────────────────────
# Block / Unblock View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def block_user(request, username):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    target_user = get_object_or_404(User, username=username)

    if target_user == request.user:
        return JsonResponse({'success': False, 'error': "You can't block yourself."}, status=400)

    block_record, created = BlockedUser.objects.get_or_create(
        blocker=request.user, blocked=target_user
    )

    if not created:
        block_record.delete()
        return JsonResponse({'success': True, 'action': 'unblocked'})

    request.user.profile.followings.remove(target_user.profile)
    target_user.profile.followings.remove(request.user.profile)
    return JsonResponse({'success': True, 'action': 'blocked'})


# ─────────────────────────────────────────────────────────────────────────────
# Report User View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def report_user(request, username):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    target_user = get_object_or_404(User, username=username)

    if target_user == request.user:
        return JsonResponse({'success': False, 'error': "You can't report yourself."}, status=400)

    try:
        body   = json.loads(request.body)
        reason = body.get('reason', '').strip()
        note   = body.get('note', '').strip()
    except (json.JSONDecodeError, AttributeError):
        reason = request.POST.get('reason', '').strip()
        note   = request.POST.get('note', '').strip()

    if not reason:
        return JsonResponse({'success': False, 'error': 'Please select a reason.'}, status=400)

    already_reported = UserReport.objects.filter(
        reporter=request.user,
        reported=target_user,
        created_at__gte=timezone.now() - timedelta(hours=24)
    ).exists()

    if already_reported:
        return JsonResponse({
            'success': False,
            'error': 'You already reported this user recently. Our team is reviewing it.'
        })

    UserReport.objects.create(
        reporter=request.user, reported=target_user, reason=reason, note=note,
    )
    return JsonResponse({'success': True})






@login_required
def mark_follow_notifications_read(request):
    if request.method == 'POST':
        updated = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).update(is_read=True)
        return JsonResponse({'success': True, 'updated_count': updated})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})



@login_required(login_url='/')
def follow(request, username):
    other_user = get_object_or_404(User, username=username)
    current_profile = request.user.profile
    other_profile = other_user.profile
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if other_user == request.user:
        if is_ajax:
            return JsonResponse({'success': False, 'error': "You can't follow yourself."}, status=400)
        return _safe_redirect_back(request, fallback='home')

    if other_profile not in current_profile.followings.all():
        current_profile.followings.add(other_profile)
        action = 'followed'
        messages.info(request, 'Following')

        # Create (or refresh, if this pair unfollowed/refollowed before) the
        # follow notification for the person being followed.
        notif, created = FollowNotification.objects.get_or_create(
            from_user=request.user, to_user=other_user,
        )
        if not created:
            notif.is_read = False
            notif.created_at = timezone.now()
            notif.save(update_fields=['is_read', 'created_at'])
    else:
        current_profile.followings.remove(other_profile)
        action = 'unfollowed'
        messages.info(request, 'unFollowing')

        # Drop the stale notification — it no longer reflects a real
        # relationship, so it shouldn't linger in the recipient's activity.
        FollowNotification.objects.filter(from_user=request.user, to_user=other_user).delete()

    if is_ajax:
        return JsonResponse({
            'success': True,
            'action': action,
            'follower_count': other_profile.followers.count(),
        })
    return _safe_redirect_back(request, fallback='home')


# ─────────────────────────────────────────────────────────────────────────────
# Toggle Privacy Lock View — quick public/private toggle for own profile
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def toggle_privacy_lock(request, username):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    if request.user.username != username:
        return JsonResponse({'success': False, 'error': "You can't change another user's privacy."}, status=403)

    profile = request.user.profile
    profile.privacy_level = (
        Profile.PRIVACY_PUBLIC if profile.privacy_level == Profile.PRIVACY_PRIVATE
        else Profile.PRIVACY_PRIVATE
    )
    profile.save()

    return JsonResponse({
        'success': True,
        'privacy_level': profile.privacy_level,
        'is_private': profile.privacy_level == Profile.PRIVACY_PRIVATE,
    })


@login_required(login_url='/')
def follower_list(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    followers = profile.followers.all()
    context = {'user': user, 'profile': profile, 'followers': followers}
    return render(request, 'followers_list.html', context)


@login_required(login_url='/')
def following_list(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    followings = profile.followings.all()
    context = {'user': user, 'profile': profile, 'followings': followings}
    return render(request, 'following_list.html', context)


def _search_users_qs(query):
    """
    People / professionals search.

    Matches on username/name/bio as before, plus:
      - Profile.profession (free-text headline, e.g. "Plumber")
      - Profile.member_type_data — the JSON blob holding every onboarding
        field (skills, services offered, years of experience, subjects,
        trades, desired job, etc. — see MEMBER_TYPE_SCHEMA), cast to text
        so a query like "electrical wiring" or "web development" matches
        whatever field it lives in without hardcoding per-type keys.
      - Profile.member_type itself, matched against the *label* of each
        member type (e.g. searching "freelancer" or "job seeker" finds
        everyone onboarded under that type).

    Results are ranked via `_relevance` so an exact profession/skill match
    (e.g. profession == "Plumber", or a member_type_data value that exactly
    equals the query) is boosted above a loose substring match, which in
    turn is boosted above a plain username/bio hit.
    """
    q = (query or '').strip()

    # Member types whose display label contains the query, e.g. searching
    # "job seeker" should surface everyone with member_type='job_seeker'
    # even though the word "seeker" isn't stored anywhere on the row.
    matching_member_types = [
        key for key, cfg in MEMBER_TYPE_SCHEMA.items()
        if q and q.lower() in cfg['label'].lower()
    ] or ['__none__']  # sentinel so `__in=[]` doesn't silently match everything

    mtd_text = Cast('profile__member_type_data', output_field=TextField())
    # A JSON string value is serialized wrapped in double quotes, so
    # searching for `"query"` approximates an *exact* value match (e.g.
    # profession/skill == query) rather than a loose substring hit.
    exact_value_marker = f'"{q}"'

    qs = (
        User.objects
        .annotate(_mtd_text=mtd_text)
        .filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(profile__bio__icontains=q) |
            Q(profile__profession__icontains=q) |
            Q(_mtd_text__icontains=q) |
            Q(profile__member_type__in=matching_member_types)
        )
        .select_related('profile')
        .annotate(
            follower_count=Count('profile__followers', distinct=True),
            _relevance=Case(
                # Exact profession / skill / member-type-field match — top of results.
                When(profile__profession__iexact=q, then=Value(100)),
                When(_mtd_text__icontains=exact_value_marker, then=Value(90)),
                When(username__iexact=q, then=Value(85)),
                # Starts-with matches next.
                When(profile__profession__istartswith=q, then=Value(75)),
                When(username__istartswith=q, then=Value(65)),
                # Member-type label match (e.g. "freelancer", "job seeker").
                When(profile__member_type__in=matching_member_types, then=Value(60)),
                # Loose substring matches on profession / member_type_data.
                When(profile__profession__icontains=q, then=Value(55)),
                When(_mtd_text__icontains=q, then=Value(45)),
                default=Value(20),
                output_field=IntegerField(),
            ),
        )
        .distinct()
        .order_by('-_relevance', '-follower_count', 'username')
    )
    return qs


def _search_products_qs(query):
    return (
        Market.objects.filter(
            Q(product_name__icontains=query) |
            Q(product_description__icontains=query) |
            Q(product_category__icontains=query) |
            Q(product_location__icontains=query)
        )
        .select_related('product_owner', 'product_owner__profile', 'business_page')
        .prefetch_related('images')
        .distinct()
        .order_by('-posted_on')
    )


def _search_pages_qs(query):
    return (
        BusinessPage.objects.filter(
            Q(name__icontains=query) |
            Q(tagline__icontains=query) |
            Q(description__icontains=query) |
            Q(category__icontains=query) |
            Q(location__icontains=query),
            is_active=True,
        )
        .annotate(_follower_count=Count('followers', distinct=True))
        .distinct()
        .order_by('-_follower_count')
    )


def _search_jobs_qs(query):
    return (
        JobVacancy.objects.filter(
            Q(title__icontains=query) |
            Q(company__icontains=query) |
            Q(description__icontains=query) |
            Q(location__icontains=query),
            is_open=True,
        )
        .select_related('business_page', 'posted_by')
        .distinct()
        .order_by('-created_at')
    )


def _search_events_qs(query):
    return (
        SocialEvent.objects.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(location__icontains=query) |
            Q(event_type__icontains=query)
        )
        .select_related('created_by')
        .distinct()
        .order_by('date', 'time')
    )


def _trending_searches(limit=8, days=14, exclude_query=None):
    """
    Site-wide trending search terms — most frequently searched queries
    (case-insensitive) across all users within the trailing window.
    """
    from django.db.models.functions import Lower

    cutoff = timezone.now() - timedelta(days=days)
    qs = (
        SearchHistory.objects
        .filter(created_at__gte=cutoff)
        .annotate(q_norm=Lower('query'))
    )
    if exclude_query:
        qs = qs.exclude(q_norm=exclude_query.strip().lower())

    rows = (
        qs.values('q_norm')
        .annotate(hits=Count('id'))
        .order_by('-hits')[:limit]
    )
    # Re-title-case for display (e.g. "iphone 13" -> "iPhone 13" is not knowable,
    # so just use the most recent original-cased spelling for each normalized term).
    results = []
    for row in rows:
        original = (
            SearchHistory.objects
            .filter(created_at__gte=cutoff, query__iexact=row['q_norm'])
            .order_by('-created_at')
            .values_list('query', flat=True)
            .first()
        )
        results.append({'query': original or row['q_norm'], 'hits': row['hits']})
    return results


@login_required(login_url='/')
def search(request):
    _PAGE = 10   # items per HTMX page

    query = request.GET.get('q', '').strip()[:100]

    if query:
        SearchHistory.objects.create(user=request.user, query=query)

        # ── First page of each result type ─────────────────────────────────────
        users_qs    = _search_users_qs(query)
        products_qs = _search_products_qs(query)
        pages_qs    = _search_pages_qs(query)
        jobs_qs     = _search_jobs_qs(query)
        events_qs   = _search_events_qs(query)

        users_total    = users_qs.count()
        products_total = products_qs.count()
        pages_total    = pages_qs.count()
        jobs_total     = jobs_qs.count()
        events_total   = events_qs.count()

        users    = users_qs[:_PAGE]
        products = products_qs[:_PAGE]
        pages    = pages_qs[:_PAGE]
        jobs     = jobs_qs[:_PAGE]
        events   = events_qs[:_PAGE]

        recent_searches = (
            SearchHistory.objects.filter(user=request.user)
            .exclude(query=query).order_by('-created_at')[:8]
        )

        # ── Wishlist state for the product cards ───────────────────────────────
        wishlist_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        ) if request.user.is_authenticated else set()

        # ── Sidebar context ────────────────────────────────────────────────────
        _unread_follow_count = FollowNotification.objects.filter(to_user=request.user, is_read=False).count()

        return render(request, 'search.html', {
            'query':             query,
            'users':             users,
            'users_total':       users_total,
            'users_has_more':    users_total > _PAGE,
            'products':          products,
            'products_total':    products_total,
            'products_has_more': products_total > _PAGE,
            'pages':             pages,
            'pages_total':       pages_total,
            'pages_has_more':    pages_total > _PAGE,
            'jobs':              jobs,
            'jobs_total':        jobs_total,
            'jobs_has_more':     jobs_total > _PAGE,
            'events':            events,
            'events_total':      events_total,
            'events_has_more':   events_total > _PAGE,
            'recent_searches':   recent_searches,
            'page_size':         _PAGE,
            'wishlist_ids':      wishlist_ids,
            'unread_follow_count':        _unread_follow_count,
        })

    # ── Explore (no query) ─────────────────────────────────────────────────────
    _EXPLORE_PAGE = 12
    search_history = (
        SearchHistory.objects.filter(user=request.user).order_by('-created_at')[:20]
    )
    trending_searches = _trending_searches(limit=8, days=14)

    current_profile = request.user.profile
    following_profile_ids = current_profile.followings.values_list('id', flat=True)
    suggested_users = (
        Profile.objects
        .exclude(user=request.user)
        .exclude(id__in=following_profile_ids)
        .annotate(_follower_count=Count('followers'))
        .order_by('-_follower_count')[:12]
    )

    explore_products_qs = (
        Market.objects
        .select_related('product_owner', 'product_owner__profile', 'business_page')
        .prefetch_related('images')
        .order_by('-is_promoted', '-posted_on')
    )
    explore_products_total = explore_products_qs.count()
    explore_products = explore_products_qs[:_EXPLORE_PAGE]

    trending_pages = (
        BusinessPage.objects.filter(is_active=True)
        .annotate(_follower_count=Count('followers', distinct=True))
        .order_by('-_follower_count')[:10]
    )

    upcoming_events = (
        SocialEvent.objects.filter(date__gte=timezone.now().date())
        .select_related('created_by')
        .order_by('date', 'time')[:6]
    )

    # ── Sidebar context ────────────────────────────────────────────────────────
    _unread_follow_count = FollowNotification.objects.filter(to_user=request.user, is_read=False).count()

    return render(request, 'search.html', {
        'search_history':        search_history,
        'trending_searches':     trending_searches,
        'suggested_users':       suggested_users,
        'explore_products':      explore_products,
        'explore_has_more':      explore_products_total > _EXPLORE_PAGE,
        'trending_pages':        trending_pages,
        'upcoming_events':       upcoming_events,
        'unread_follow_count':   _unread_follow_count,
    })


# ── HTMX search pagination partials ───────────────────────────────────────────

@login_required(login_url='/')
@require_GET
def search_users_partial(request):
    """GET /search/users/?q=…&page=N  — HTMX paginated user rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    users_qs = _search_users_qs(query)
    total = users_qs.count()
    users = users_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/search_users_partial.html', {
        'users':    users,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def search_products_partial(request):
    """GET /search/products/?q=…&page=N  — HTMX paginated product rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    products_qs = _search_products_qs(query)
    total = products_qs.count()
    products = products_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    wishlist_ids = set(
        Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
    ) if request.user.is_authenticated else set()

    return render(request, 'snippet/search_products_partial.html', {
        'products':     products,
        'query':        query,
        'page':         page + 1,
        'has_more':     has_more,
        'wishlist_ids': wishlist_ids,
    })


@login_required(login_url='/')
@require_GET
def search_pages_partial(request):
    """GET /search/pages/?q=…&page=N  — HTMX paginated business page rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    pages_qs = _search_pages_qs(query)
    total = pages_qs.count()
    pages = pages_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/search_pages_partial.html', {
        'pages':    pages,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def search_jobs_partial(request):
    """GET /search/jobs/?q=…&page=N  — HTMX paginated job rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    jobs_qs = _search_jobs_qs(query)
    total = jobs_qs.count()
    jobs = jobs_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/search_jobs_partial.html', {
        'jobs':     jobs,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def search_events_partial(request):
    """GET /search/events/?q=…&page=N — HTMX paginated event rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    events_qs = _search_events_qs(query)
    total = events_qs.count()
    events = events_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/search_events_partial.html', {
        'events':   events,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def explore_products_partial(request):
    """GET /search/explore/products/?page=N — HTMX paginated explore grid (no query)."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 12
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    products_qs = (
        Market.objects
        .select_related('product_owner', 'product_owner__profile', 'business_page')
        .prefetch_related('images')
        .order_by('-is_promoted', '-posted_on')
    )
    total = products_qs.count()
    products = products_qs[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/explore_products_partial.html', {
        'products': products,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def search_suggestions_v0(request):
    """
    GET /search/suggestions/?q=… — lightweight live-typeahead results,
    called as the user types. Returns a small mixed bag of matches
    across users, products, pages, jobs and events, plus any of the
    user's own past searches that match.
    """
    query = request.GET.get('q', '').strip()[:100]

    if not query:
        return JsonResponse({'query': '', 'results': [], 'history': []})

    _N = 4  # max items per category in the dropdown

    users    = list(_search_users_qs(query)[:_N])
    products = list(_search_products_qs(query)[:_N])
    pages    = list(_search_pages_qs(query)[:_N])
    jobs     = list(_search_jobs_qs(query)[:_N])
    events   = list(_search_events_qs(query)[:_N])

    results = []

    for u in users:
        pic = ''
        is_pro = False
        sub = u.get_full_name() or 'User'
        try:
            prof = u.profile
            pic = prof.get_picture_url
            if prof.is_professional:
                # e.g. "Skilled Professional · Plumber" — surfaces the
                # profession/skill match right in the suggestion dropdown.
                headline = prof.kishihub_use_headline
                if headline:
                    sub = headline
                    is_pro = True
        except Exception:
            pass
        results.append({
            'type':  'professional' if is_pro else 'user',
            'label': u.username,
            'sub':   sub,
            'image': pic,
            'url':   reverse('profile', args=[u.username]),
        })

    for p in products:
        first_image = p.images.first()
        results.append({
            'type':  'product',
            'label': p.product_name,
            'sub':   f'₦{p.product_price:,.0f}' if p.product_price is not None else '',
            'image': first_image.product_image.url if first_image and first_image.product_image else '',
            'url':   reverse('product_detail', args=[p.product_id]),
        })

    for bp in pages:
        logo = ''
        try:
            logo = bp.get_logo_url
        except Exception:
            logo = ''
        results.append({
            'type':  'page',
            'label': bp.name,
            'sub':   bp.get_category_display() if hasattr(bp, 'get_category_display') else 'Business',
            'image': logo,
            'url':   reverse('business_page_detail', args=[bp.slug]),
        })

    for j in jobs:
        results.append({
            'type':  'job',
            'label': j.title,
            'sub':   j.company,
            'image': '',
            'url':   f"{reverse('job_vacancy')}#khj-card-{j.id}",
        })

    for e in events:
        results.append({
            'type':  'event',
            'label': e.title,
            'sub':   e.date.strftime('%b %d') if e.date else e.get_event_type_display(),
            'image': '',
            'url':   f"{reverse('event_calendar')}#event-card-{e.id}",
        })

    history = list(
        SearchHistory.objects.filter(user=request.user, query__icontains=query)
        .exclude(query__iexact=query)
        .order_by('-created_at')
        .values_list('query', flat=True)
        .distinct()[:5]
    )

    return JsonResponse({
        'query':   query,
        'results': results,
        'history': history,
    })




@login_required
def delete_history(request, history_id):
    SearchHistory.objects.filter(id=history_id, user=request.user).delete()
    return redirect('search')


@login_required
def clear_history(request):
    SearchHistory.objects.filter(user=request.user).delete()
    return redirect('search')




@login_required(login_url='/')
def message(request, username):
    receiver = get_object_or_404(User, username=username)
    sender = request.user

    try:
        if sender.profile.has_blocked(receiver.profile) or receiver.profile.has_blocked(sender.profile):
            from django.contrib import messages as _msgs
            _msgs.error(request, 'You cannot view this conversation.')
            return redirect('inbox')
    except Exception:
        pass

    unread_messages = Message.objects.filter(sender=receiver, receiver=sender, is_read=False)
    unread_messages.update(is_read=True)
    
    conversations = Message.objects.filter(
        Q(sender=sender, receiver=receiver) | Q(sender=receiver, receiver=sender)
    ).order_by('created_at')

    from social.models import MessageReaction
    from django.db.models import Count as _Count

    reaction_rows = (
        MessageReaction.objects
        .filter(message__in=conversations)
        .values('message_id', 'emoji')
        .annotate(count=_Count('id'))
    )
    reactions_by_msg = {}
    for row in reaction_rows:
        reactions_by_msg.setdefault(row['message_id'], {})[row['emoji']] = row['count']

    user_reaction_rows = MessageReaction.objects.filter(
        message__in=conversations, user=request.user
    ).values('message_id', 'emoji')
    user_reactions = {r['message_id']: r['emoji'] for r in user_reaction_rows}

    conversations_list = list(conversations)
    for msg in conversations_list:
        msg.reactions_summary = reactions_by_msg.get(msg.id, {})
        my_emoji = user_reactions.get(msg.id)
        msg.reaction_users = [request.user] if my_emoji else []
        msg.my_reaction = my_emoji
    
    grouped_messages = {}
    for msg in conversations_list:
        label = msg.chat_date_label
        grouped_messages.setdefault(label, []).append(msg)
    
    # ── Product enquiry context ───────────────────────────────────────────────
    # If ?product=<uuid> is in the URL, preload the listing so the template can
    # pre-fill the composer with a product card prompt.
    product_context = None
    product_uuid = request.GET.get('product')
    if product_uuid:
        try:
            import uuid as _uuid_mod
            _pid = _uuid_mod.UUID(str(product_uuid))
            _product = Market.objects.prefetch_related('images').get(product_id=_pid)
            if _product.product_owner != request.user:
                _first_img = _product.images.first()
                product_context = {
                    'product_id':   str(_product.product_id),
                    'name':         _product.product_name,
                    'price':        _product.product_price,
                    'condition':    _product.product_condition,
                    'category':     _product.product_category,
                    'location':     _product.product_location,
                    'image_url':    _first_img.product_image.url if _first_img else '',
                    'detail_url':   f"/product/{_product.product_id}/",
                }
        except Exception:
            product_context = None

    # ── Job enquiry context ────────────────────────────────────────────────────
    # If ?job=<uuid> is in the URL, preload the vacancy so the template can
    # pre-fill the composer with a job card prompt (mirrors product_context).
    job_context = None
    job_uuid = request.GET.get('job')
    if job_uuid:
        try:
            import uuid as _uuid_mod2
            _jid = _uuid_mod2.UUID(str(job_uuid))
            _job = JobVacancy.objects.select_related('business_page').get(id=_jid)
            if _job.posted_by != request.user:
                job_context = {
                    'job_id':       str(_job.id),
                    'title':        _job.title,
                    'company':      _job.company,
                    'category':     _job.category,
                    'category_label': _job.get_category_display(),
                    'location':     _job.location,
                    'salary_range': _job.salary_range,
                    'is_open':      _job.is_open,
                    'image_url':    _job.cover_image.url if _job.cover_image else '',
                    'detail_url':   f"/jobs/{_job.id}/",
                }
        except Exception:
            job_context = None

    context = {
        'grouped_messages': grouped_messages,
        'receiver': receiver,
        'product_context': product_context,
        'job_context': job_context,
    }
    return render(request, 'message.html', context)


@login_required(login_url='/')
def send_message(request, username):
    receiver = get_object_or_404(User, username=username)
    
    if request.method == 'POST':
        try:
            sender_profile   = request.user.profile
            receiver_profile = receiver.profile
            if sender_profile.has_blocked(receiver_profile) or receiver_profile.has_blocked(sender_profile):
                return JsonResponse({'status': 'error', 'message': 'Unable to send message.'}, status=403)
        except Exception:
            pass

        if request.content_type == 'application/json':
            if len(request.body) > 100_000:
                return JsonResponse({'status': 'error', 'message': 'Request too large.'}, status=413)
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Invalid JSON.'}, status=400)
            message_text = str(data.get('message', ''))
            reply_to_id = data.get('reply_to')
            product_id_raw = data.get('product_id')
            job_id_raw = data.get('job_id')
        else:
            message_text = request.POST.get('message', '')
            reply_to_id = request.POST.get('reply_to')
            product_id_raw = request.POST.get('product_id')
            job_id_raw = request.POST.get('job_id')
        
        file_upload = request.FILES.get('file_upload')

        if message_text and len(message_text) > 5000:
            return JsonResponse({'status': 'error', 'message': 'Message too long. Maximum 5000 characters.'}, status=400)

        if not message_text and not file_upload:
            return JsonResponse({'status': 'success', 'message': 'No content to send'})
        
        file_type = None
        file_name = None
        if file_upload:
            raw_name = file_upload.name or 'file'
            raw_name = os.path.basename(raw_name.replace('\\', '/'))
            raw_name = re.sub(r'[^\w\s\-\.]', '', raw_name).strip()[:100] or 'file'
            file_name = raw_name
            ext = os.path.splitext(file_name)[1].lower()
            ALLOWED_EXTENSIONS = {
                'image':    {'.jpg', '.jpeg', '.png', '.gif'},
                'video':    {'.mp4', '.mov', '.avi'},
                'audio':    {'.mp3', '.wav', '.webm', '.ogg', '.m4a'},
                'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'},
            }
            file_type = next((t for t, exts in ALLOWED_EXTENSIONS.items() if ext in exts), None)
            if not file_type:
                return JsonResponse({'status': 'error', 'message': 'Unsupported file type'}, status=400)
            if file_upload.size > 50 * 1024 * 1024:
                return JsonResponse({'status': 'error', 'message': 'File too large. Maximum size is 50MB.'}, status=400)
        
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id)
                if not (reply_to.sender == request.user or reply_to.receiver == request.user or
                        reply_to.sender == receiver or reply_to.receiver == receiver):
                    reply_to = None
            except Message.DoesNotExist:
                reply_to = None
        
        link_preview = None
        if message_text:
            url_match = re.search(r'https?://[^\s]+', message_text)
            if url_match:
                preview_url = url_match.group(0)
                if _is_safe_url_for_preview(preview_url):
                    try:
                        _headers = {
                            'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
                            'Accept': 'text/html,application/xhtml+xml',
                        }
                        _resp = requests.get(preview_url, headers=_headers, timeout=4, allow_redirects=True, stream=True)
                        _content = b''
                        for _chunk in _resp.iter_content(chunk_size=8192):
                            _content += _chunk
                            if len(_content) > 500_000:
                                break
                        _soup = BeautifulSoup(_content, 'html.parser')

                        def _og(prop):
                            tag = (
                                _soup.find('meta', property=f'og:{prop}')
                                or _soup.find('meta', attrs={'name': f'twitter:{prop}'})
                            )
                            return tag['content'].strip() if tag and tag.get('content') else ''

                        _image = _og('image')
                        if _image and not _image.startswith(('http://', 'https://')):
                            _image = ''

                        link_preview = {
                            'title':       html_escape((_og('title') or (_soup.title.string.strip() if _soup.title else ''))[:200]),
                            'description': html_escape(_og('description')[:400]),
                            'image':       _image[:500],
                            'domain':      html_escape(urlparse(_resp.url).netloc.replace('www.', '')[:100]),
                            'url':         preview_url,
                        }
                    except Exception:
                        link_preview = None

        # ── Resolve linked product (buyer → seller enquiry) ───────────────────
        linked_product_obj = None
        linked_product_snapshot = None
        if product_id_raw:
            try:
                import uuid as _uuid_mod
                _pid = _uuid_mod.UUID(str(product_id_raw))
                _prod = Market.objects.prefetch_related('images').get(product_id=_pid)
                # Only attach if the receiver is the actual seller
                if _prod.product_owner == receiver:
                    linked_product_obj = _prod
                    _first_img = _prod.images.first()
                    linked_product_snapshot = {
                        'product_id':  str(_prod.product_id),
                        'name':        _prod.product_name,
                        'price':       _prod.product_price,
                        'condition':   _prod.product_condition,
                        'category':    _prod.product_category,
                        'location':    _prod.product_location,
                        'image_url':   _first_img.product_image.url if _first_img else '',
                        'detail_url':  f"/product/{_prod.product_id}/",
                    }
            except Exception:
                linked_product_obj = None
                linked_product_snapshot = None

        # ── Resolve linked job (applicant → poster enquiry) ────────────────────
        linked_job_obj = None
        linked_job_snapshot = None
        if job_id_raw:
            try:
                import uuid as _uuid_mod3
                _jid = _uuid_mod3.UUID(str(job_id_raw))
                _job = JobVacancy.objects.select_related('business_page').get(id=_jid)
                # Only attach if the receiver is the actual poster
                if _job.posted_by == receiver:
                    linked_job_obj = _job
                    linked_job_snapshot = {
                        'job_id':         str(_job.id),
                        'title':          _job.title,
                        'company':        _job.company,
                        'category':       _job.category,
                        'category_label': _job.get_category_display(),
                        'location':       _job.location,
                        'salary_range':   _job.salary_range,
                        'is_open':        _job.is_open,
                        'image_url':      _job.cover_image.url if _job.cover_image else '',
                        'detail_url':     f"/jobs/{_job.id}/",
                    }
            except Exception:
                linked_job_obj = None
                linked_job_snapshot = None

        msg_obj = Message.objects.create(
            sender=request.user, receiver=receiver,
            conversation=message_text if message_text else '',
            file_type=file_type,
            file=file_upload if file_upload else None,
            reply_to=reply_to,
            link_preview=link_preview,
            linked_product=linked_product_obj,
            linked_product_snapshot=linked_product_snapshot,
            linked_job=linked_job_obj,
            linked_job_snapshot=linked_job_snapshot,
        )
        
        Message.objects.filter(sender=receiver, receiver=request.user, is_read=False).update(is_read=True)
        
        channel_layer = get_channel_layer()
        user_ids = sorted([request.user.id, receiver.id])
        room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        room_group_name = f"chat_{room_name}"
        
        file_url = msg_obj.file.url if msg_obj.file else None
        
        reply_data = None
        if reply_to:
            reply_data = {
                'message_id': str(reply_to.id),
                'sender': reply_to.sender.username,
                'message': reply_to.conversation,
                'file_type': reply_to.file_type
            }

        sender_avatar = request.user.profile.picture.url if request.user.profile.picture else ''

        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'chat_message',
                'message_id': str(msg_obj.id),
                'sender': request.user.username,
                'sender_avatar': sender_avatar,
                'receiver': receiver.username,
                'message': message_text,
                'file_type': file_type,
                'file_url': file_url,
                'file_name': file_name or '',
                'time': msg_obj.created_at.isoformat(),
                'reply_to': reply_data,
                'link_preview': link_preview,
                'linked_product_snapshot': linked_product_snapshot,
                'linked_job_snapshot': linked_job_snapshot,
            }
        )
        
        return JsonResponse({'status': 'success', 'message': 'Message sent', 'message_id': msg_obj.id, 'file_url': file_url})
    
    return redirect('message', username=username)


@login_required(login_url='/')
def delete_message(request, message_id):
    if request.method == 'POST':
        try:
            msg_obj = Message.objects.get(id=message_id)
            if msg_obj.sender != request.user and msg_obj.receiver != request.user:
                return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
            
            channel_layer = get_channel_layer()
            user_ids = sorted([msg_obj.sender.id, msg_obj.receiver.id])
            room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
            room_group_name = f"chat_{room_name}"
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'message_deleted',
                    'message_id': msg_obj.id,
                    'sender': msg_obj.sender.username,
                    'receiver': msg_obj.receiver.username,
                }
            )
            
            msg_obj.delete()
            return JsonResponse({'status': 'success', 'message': 'Message deleted successfully'})
            
        except Message.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Message not found'})
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'An error occurred. Please try again.'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)


@login_required(login_url='/')
def react_to_message(request, message_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    from social.models import MessageReaction

    try:
        msg_obj = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)

    if request.user not in (msg_obj.sender, msg_obj.receiver):
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)

    try:
        body  = json.loads(request.body)
        emoji = body.get('emoji', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    ALLOWED_EMOJIS = {'❤️', '😂', '😮', '😢', '😡', '👍', '🔥', '🎉'}
    if emoji not in ALLOWED_EMOJIS:
        return JsonResponse({'status': 'error', 'message': 'Invalid emoji'}, status=400)

    existing = MessageReaction.objects.filter(message=msg_obj, user=request.user).first()

    if existing:
        if existing.emoji == emoji:
            existing.delete()
            user_reaction = None
        else:
            existing.emoji = emoji
            existing.save()
            user_reaction = emoji
    else:
        MessageReaction.objects.create(message=msg_obj, user=request.user, emoji=emoji)
        user_reaction = emoji

    from django.db.models import Count as _Count
    summary = (
        MessageReaction.objects.filter(message=msg_obj)
        .values('emoji').annotate(count=_Count('id')).order_by('emoji')
    )
    reaction_summary = {row['emoji']: row['count'] for row in summary}

    try:
        user_ids = sorted([msg_obj.sender_id, msg_obj.receiver_id])
        room_group_name = f"chat_dm_{user_ids[0]}_{user_ids[1]}"
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'message_reaction',
                'message_id': msg_obj.id,
                'reactions': reaction_summary,
                'actor': request.user.username,
            }
        )
    except Exception:
        pass

    return JsonResponse({
        'status': 'success',
        'message_id': msg_obj.id,
        'reactions': reaction_summary,
        'user_reaction': user_reaction,
    })


# ── SSRF protection ──────────────────────────────────────────────────────────

_BLOCKED_HOSTS = {
    'localhost',
    'metadata.google.internal',
    '169.254.169.254',
    '100.100.100.200',
    'fd00:ec2::254',
}
_PRIVATE_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('::ffff:0:0/96'),
]

def _is_ip_safe(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        if not ip.is_global:
            return False
        for network in _PRIVATE_NETWORKS:
            if ip in network:
                return False
        return True
    except ValueError:
        return False

def _is_safe_url_for_preview(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() in _BLOCKED_HOSTS:
            return False
        try:
            results = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False
        if not results:
            return False
        for res in results:
            ip_str = res[4][0]
            if not _is_ip_safe(ip_str):
                return False
        return True
    except Exception:
        return False


@login_required(login_url='/')
def fetch_link_preview(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from django.core.cache import cache
    rate_key = f'lp_rate_{request.user.id}'
    rate_count = cache.get(rate_key, 0)
    if rate_count >= 30:
        return JsonResponse({'error': 'Too many requests'}, status=429)
    cache.set(rate_key, rate_count + 1, timeout=60)

    url = request.GET.get('url', '').strip()
    if not url:
        return JsonResponse({'error': 'No URL provided'}, status=400)

    url = html_unescape(url)

    if len(url) > 2048:
        return JsonResponse({'error': 'URL too long'}, status=400)

    if not url.startswith(('http://', 'https://')):
        return JsonResponse({'error': 'Invalid URL'}, status=400)

    if not _is_safe_url_for_preview(url):
        return JsonResponse({'error': 'URL not allowed'}, status=400)

    def _try_oembed(target_url):
        parsed_host = urlparse(target_url).hostname or ''
        encoded = url_quote(target_url, safe='')
        oembed_endpoint = None

        if 'youtube.com' in parsed_host or 'youtu.be' in parsed_host:
            oembed_endpoint = f'https://www.youtube.com/oembed?url={encoded}&format=json'
        elif 'vimeo.com' in parsed_host:
            oembed_endpoint = f'https://vimeo.com/api/oembed.json?url={encoded}'
        elif 'tiktok.com' in parsed_host:
            oembed_endpoint = f'https://www.tiktok.com/oembed?url={encoded}'
        elif 'twitter.com' in parsed_host or 'x.com' in parsed_host:
            oembed_endpoint = f'https://publish.twitter.com/oembed?url={encoded}'

        if not oembed_endpoint:
            return None
        try:
            r = requests.get(oembed_endpoint, timeout=5,
                             headers={'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)'},
                             allow_redirects=False)
            if not r.ok:
                return None
            data = r.json()
            thumb  = data.get('thumbnail_url', '') or ''
            title  = data.get('title', '') or ''
            author = data.get('author_name', '') or ''
            domain = parsed_host.replace('www.', '')
            desc   = f'By {author}' if author else ''
            if thumb and not thumb.startswith(('http://', 'https://')):
                thumb = ''
            return {
                'title':       html_escape(title[:200]),
                'description': html_escape(desc[:400]),
                'image':       thumb[:500],
                'domain':      html_escape(domain[:100]),
                'url':         target_url,
            }
        except Exception:
            return None

    oembed_result = _try_oembed(url)
    if oembed_result and (oembed_result['title'] or oembed_result['image']):
        return JsonResponse(oembed_result)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
            'Accept': 'text/html,application/xhtml+xml',
        }
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True, stream=True)
        content = b''
        for chunk in resp.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > 500_000:
                break

        soup = BeautifulSoup(content, 'html.parser')

        def og(prop):
            tag = (
                soup.find('meta', property=f'og:{prop}')
                or soup.find('meta', attrs={'name': f'twitter:{prop}'})
                or soup.find('meta', attrs={'name': prop})
            )
            return tag['content'].strip() if tag and tag.get('content') else ''

        title       = og('title') or (soup.title.string.strip() if soup.title else '')
        description = og('description')
        image       = og('image')
        domain      = urlparse(resp.url).netloc.replace('www.', '')

        if image and not image.startswith(('http://', 'https://')):
            image = ''

        return JsonResponse({
            'title':       html_escape(title[:200]),
            'description': html_escape(description[:400]),
            'image':       image[:500],
            'domain':      html_escape(domain[:100]),
            'url':         url,
        })
    except Exception:
        return JsonResponse({'title': '', 'description': '', 'image': '', 'domain': '', 'url': url})


# ─────────────────────────────────────────────────────────────────────────────
# Notification Views (FollowNotification + BusinessNotification)
# ─────────────────────────────────────────────────────────────────────────────


def _build_activity_notification_entries(user):
    """
    Builds the flat, newest-first list of 'n' dicts shown in the
    Today / This Week / Earlier sections of the notification page:
    personal follows, plus reactions and comments on the user's own
    ProfilePost updates and on the user's own Portfolio/Project,
    Achievement, Experience, Education, and Service items.

    Each dict matches the shape snippet/kvibe_notif_item.html (and, in
    turn, snippet/kvibe_notif_row.html) know how to render:
        group_id, type, latest_actor, post, item, item_section, anchor_id,
        subtab, section_label, follow_id, is_read, created_at,
        others_count, vibe_type, vibe_emoji, is_following_back

    Reaction/comment rows on the same post/item are grouped into a single
    entry (latest actor + "and N others"), the way Instagram-style feeds
    collapse repeat activity on one post instead of listing every single tap.
    """
    following_ids = set(
        user.profile.followings.values_list('pk', flat=True)
    )

    entries = []

    # ── Follows ──────────────────────────────────────────────────────────
    follow_qs = (
        FollowNotification.objects
        .filter(to_user=user)
        .select_related('from_user', 'from_user__profile')
        .order_by('-created_at')[:50]
    )
    for fn in follow_qs:
        entries.append({
            'group_id': f'follow-{fn.pk}',
            'type': 'follow',
            'latest_actor': fn.from_user,
            'post': None,
            'follow_id': fn.pk,
            'is_read': fn.is_read,
            'created_at': fn.created_at,
            'others_count': 0,
            'vibe_type': '',
            'vibe_emoji': '',
            # Lets the row show "Following" instead of "Follow" when the
            # recipient already follows this person back.
            'is_following_back': fn.from_user.profile.pk in following_ids,
        })

    # ── Reactions & comments on the user's own posts ────────────────────
    post_notif_qs = (
        ProfilePostNotification.objects
        .filter(to_user=user)
        .select_related('actor', 'actor__profile', 'post')
        .order_by('-created_at')[:100]
    )

    grouped = {}
    group_order = []
    for pn in post_notif_qs:
        key = ('post', pn.post_id, pn.notif_type)
        if key not in grouped:
            grouped[key] = {
                'group_id': f'profilepost-{pn.notif_type}-{pn.post_id}',
                'type': 'like' if pn.notif_type == ProfilePostNotification.NEW_VIBE else 'comment',
                'latest_actor': pn.actor,
                'post': pn.post,
                'item': None,
                'item_section': '',
                'anchor_id': f'kpp-post-{pn.post_id}',
                'subtab': 'posts',
                'section_label': 'post',
                'follow_id': None,
                'is_read': pn.is_read,
                'created_at': pn.created_at,
                'vibe_type': pn.vibe_type,
                'vibe_emoji': ProfilePostVibe.VIBE_EMOJIS.get(pn.vibe_type, ''),
                'is_following_back': False,
                '_actor_ids': {pn.actor_id},
            }
            group_order.append(key)
        else:
            g = grouped[key]
            g['_actor_ids'].add(pn.actor_id)
            if not pn.is_read:
                g['is_read'] = False

    # ── Reactions & comments on the user's own Portfolio/Project,
    #    Achievement, Experience, Education, and Service items ──────────
    item_notif_qs = (
        ProfileItemNotification.objects
        .filter(to_user=user)
        .select_related(
            'actor', 'actor__profile',
            'portfolio_item', 'achievement', 'experience', 'education', 'service',
        )
        .order_by('-created_at')[:100]
    )

    for inx in item_notif_qs:
        key = ('item', inx.section, inx.target_id, inx.notif_type)
        if key not in grouped:
            grouped[key] = {
                'group_id': f'profileitem-{inx.section}-{inx.notif_type}-{inx.target_id}',
                'type': 'like' if inx.notif_type == ProfileItemNotification.NEW_VIBE else 'comment',
                'latest_actor': inx.actor,
                'post': None,
                'item': inx.target,
                'item_section': inx.section,
                'anchor_id': inx.anchor_id,
                'subtab': inx.subtab,
                'section_label': inx.section_label,
                'follow_id': None,
                'is_read': inx.is_read,
                'created_at': inx.created_at,
                'vibe_type': inx.vibe_type,
                'vibe_emoji': ProfilePostVibe.VIBE_EMOJIS.get(inx.vibe_type, ''),
                'is_following_back': False,
                '_actor_ids': {inx.actor_id},
            }
            group_order.append(key)
        else:
            g = grouped[key]
            g['_actor_ids'].add(inx.actor_id)
            if not inx.is_read:
                g['is_read'] = False

    for key in group_order:
        g = grouped[key]
        g['others_count'] = max(len(g.pop('_actor_ids')) - 1, 0)
        entries.append(g)

    entries.sort(key=lambda e: e['created_at'], reverse=True)

    # Only the very first rendered row should inline the shared
    # <style id="kvibe-notif-row-styles"> block (avoids duplicate <style>
    # tags with the same id when many rows are rendered).
    for i, entry in enumerate(entries):
        entry['is_first_row'] = (i == 0)

    return entries


def _bucket_notifications_by_recency(entries):
    """Splits a list of 'n' dicts (ordered newest-first) into
    today / this-week / earlier buckets, based on created_at."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    today_notifications, week_notifications, earlier_notifications = [], [], []
    for entry in entries:
        created_at = entry['created_at']
        if created_at >= today_start:
            today_notifications.append(entry)
        elif created_at >= week_start:
            week_notifications.append(entry)
        else:
            earlier_notifications.append(entry)

    return today_notifications, week_notifications, earlier_notifications


@login_required(login_url='/')
def notification_list(request):
    FollowNotification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)
    ProfilePostNotification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)
    ProfileItemNotification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)
    BusinessNotification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)
    EventNotification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)

    activity_entries = _build_activity_notification_entries(request.user)
    today_notifications, week_notifications, earlier_notifications = (
        _bucket_notifications_by_recency(activity_entries)
    )

    business_notifications = (
        BusinessNotification.objects
        .filter(to_user=request.user)
        .select_related('business_page', 'actor', 'product', 'post')[:30]
    )
    event_notifications = (
        EventNotification.objects
        .filter(to_user=request.user)
        .select_related('event', 'actor')[:30]
    )

    context = {
        'today_notifications': today_notifications,
        'week_notifications': week_notifications,
        'earlier_notifications': earlier_notifications,
        'business_notifications': business_notifications,
        'event_notifications': event_notifications,
    }

    if request.GET.get('panel') == '1':
        return render(request, 'snippet/notification_panel_partial.html', context)

    return render(request, 'notification.html', context)


def notification_partial(request):
    if request.user.is_authenticated:
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
        unread_profile_post_count = ProfilePostNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
        unread_profile_item_count = ProfileItemNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
        unread_business_count = BusinessNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
        unread_event_count = EventNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
    else:
        unread_follow_count = 0
        unread_profile_post_count = 0
        unread_profile_item_count = 0
        unread_business_count = 0
        unread_event_count = 0
    return render(request, 'snippet/notification_count.html', {
        'unread_follow_count': unread_follow_count,
        'unread_profile_post_count': unread_profile_post_count,
        'unread_profile_item_count': unread_profile_item_count,
        'unread_business_count': unread_business_count,
        'unread_event_count': unread_event_count,
    })


def inbox_partial(request):
    return render(request, 'snippet/inbox_count.html')


@login_required
@require_POST
def delete_notification_group(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    # ── Follow notification ───────────────────────────────────────────────────
    follow_id = data.get('follow_id')
    if follow_id is not None:
        try:
            follow_id = int(follow_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid follow_id'}, status=400)

        deleted_count, _ = FollowNotification.objects.filter(
            pk=follow_id,
            to_user=request.user,
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    # ── Business page notification (new_follower / new_product) ────────────────
    business_notif_id = data.get('business_notif_id')
    if business_notif_id is not None:
        try:
            business_notif_id = int(business_notif_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid business_notif_id'}, status=400)

        deleted_count, _ = BusinessNotification.objects.filter(
            pk=business_notif_id,
            to_user=request.user,
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    # ── Event notification (event_updated / event_reminder / event_cancelled / new_comment) ──
    event_notif_id = data.get('event_notif_id')
    if event_notif_id is not None:
        try:
            event_notif_id = int(event_notif_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid event_notif_id'}, status=400)

        deleted_count, _ = EventNotification.objects.filter(
            pk=event_notif_id,
            to_user=request.user,
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    # ── Grouped reaction/comment notification on one of the user's own
    #    ProfilePost updates. 'notification_type' is the display type used
    #    by snippet/kvibe_notif_row.html ('like' or 'comment'); dismissing
    #    it clears every actor's row in that group at once, matching how
    #    the group is shown as a single entry. ──────────────────────────
    post_id = data.get('post_id')
    notification_type = data.get('notification_type')
    if post_id and notification_type:
        model_notif_type = {
            'like': ProfilePostNotification.NEW_VIBE,
            'comment': ProfilePostNotification.NEW_COMMENT,
        }.get(notification_type)

        if not model_notif_type:
            return JsonResponse({'status': 'error', 'message': 'Invalid notification_type'}, status=400)

        deleted_count, _ = ProfilePostNotification.objects.filter(
            post_id=post_id,
            notif_type=model_notif_type,
            to_user=request.user,
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    # ── Grouped reaction/comment notification on one of the user's own
    #    Portfolio/Project, Achievement, Experience, Education, or Service
    #    items — same one-entry-per-group dismissal as the ProfilePost
    #    case above, keyed off (section, target item) instead of a post. ──
    item_section = data.get('item_section')
    item_id = data.get('item_id')
    if item_section and item_id and notification_type:
        model_notif_type = {
            'like': ProfileItemNotification.NEW_VIBE,
            'comment': ProfileItemNotification.NEW_COMMENT,
        }.get(notification_type)

        valid_sections = dict(ProfileItemNotification.SECTION_CHOICES)
        if not model_notif_type or item_section not in valid_sections:
            return JsonResponse({'status': 'error', 'message': 'Invalid notification_type'}, status=400)

        fk_field = {
            ProfileItemNotification.PORTFOLIO:   'portfolio_item_id',
            ProfileItemNotification.ACHIEVEMENT: 'achievement_id',
            ProfileItemNotification.EXPERIENCE:  'experience_id',
            ProfileItemNotification.EDUCATION:   'education_id',
            ProfileItemNotification.SERVICE:     'service_id',
        }[item_section]

        deleted_count, _ = ProfileItemNotification.objects.filter(
            section=item_section,
            notif_type=model_notif_type,
            to_user=request.user,
            **{fk_field: item_id},
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)


@login_required
@require_POST
def mark_all_notifications_read(request):
    FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    ProfilePostNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    ProfileItemNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    BusinessNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    EventNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    return JsonResponse({'status': 'success'})


# ─────────────────────────────────────────────────────────────────────────────
# Inbox
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def inbox(request):
    conversations = {}
    all_messages = Message.objects.filter(
        Q(sender=request.user) | Q(receiver=request.user)
    )
    conversation_partners = set()
    for msg in all_messages:
        other_user = msg.sender if msg.sender != request.user else msg.receiver
        conversation_partners.add(other_user)
    
    for partner in conversation_partners:
        last_message = Message.objects.filter(
            Q(sender=request.user, receiver=partner) |
            Q(sender=partner, receiver=request.user)
        ).order_by('-created_at').first()
        
        if last_message:
            unread_count = Message.objects.filter(
                sender=partner, receiver=request.user, is_read=False
            ).count()
            conversations[partner] = {'last_message': last_message, 'unread_count': unread_count}
    
    sorted_conversations = sorted(
        conversations.items(),
        key=lambda x: x[1]['last_message'].created_at,
        reverse=True
    )
    
    contacts = conversation_partners
    return render(request, 'inbox.html', {
        'conversations': dict(sorted_conversations),
        'contacts': contacts,
        'user': request.user
    })


# ─────────────────────────────────────────────────────────────────────────────
# DM last-message preview  (used by home-page bubble row popup)
# GET /inbox/last_message/?username=<str>
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_GET
def dm_last_message(request):
    """Return a lightweight JSON preview of the last message with a partner."""
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)
    try:
        partner = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)

    last_msg = (
        Message.objects
        .filter(
            Q(sender=request.user, receiver=partner) |
            Q(sender=partner, receiver=request.user)
        )
        .order_by('-created_at')
        .first()
    )
    if not last_msg:
        return JsonResponse({'message': None, 'unread_count': 0})

    unread = Message.objects.filter(
        sender=partner, receiver=request.user, is_read=False
    ).count()

    return JsonResponse({
        'message':      last_msg.conversation or '',
        'file_type':    last_msg.file_type or '',
        'has_media':    bool(last_msg.file_type),
        'is_mine':      last_msg.sender_id == request.user.id,
        'unread_count': unread,
    })


# ─────────────────────────────────────────────────────────────────────────────
# DM full conversation  (used by home-page chat modal)
# GET /inbox/conversation/?username=<str>
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_GET
def dm_conversation(request):
    """Return the full conversation with a partner as JSON, mark unread as read."""
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)
    try:
        partner = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)

    # Mark incoming unread messages as read
    Message.objects.filter(
        sender=partner, receiver=request.user, is_read=False
    ).update(is_read=True)

    msgs = (
        Message.objects
        .filter(
            Q(sender=request.user, receiver=partner) |
            Q(sender=partner, receiver=request.user)
        )
        .select_related('sender', 'reply_to', 'reply_to__sender')
        .order_by('created_at')
    )

    def file_url(msg):
        if not msg.file:
            return None
        try:
            return msg.file.url
        except Exception:
            return None

    # ── Reactions for all messages in this conversation ──────────────────
    from social.models import MessageReaction
    from django.db.models import Count as _Count

    reaction_rows = (
        MessageReaction.objects
        .filter(message__in=msgs)
        .values('message_id', 'emoji')
        .annotate(count=_Count('id'))
    )
    reactions_by_msg = {}
    for row in reaction_rows:
        reactions_by_msg.setdefault(row['message_id'], {})[row['emoji']] = row['count']

    user_reaction_rows = MessageReaction.objects.filter(
        message__in=msgs, user=request.user
    ).values('message_id', 'emoji')
    user_reactions = {r['message_id']: r['emoji'] for r in user_reaction_rows}

    messages_data = []
    for msg in msgs:
        reply_preview = None
        if msg.reply_to:
            rp = msg.reply_to
            reply_preview = {
                'sender':  rp.sender.username,
                'text':    (rp.conversation or '')[:80],
                'file_type': rp.file_type or '',
            }

        # iso: UTC ISO string so the JS formatDmTime() can convert to user's local tz
        try:
            iso_str = msg.created_at.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        except Exception:
            iso_str = None

        messages_data.append({
            'id':           msg.id,
            'text':         msg.conversation or '',
            'file_type':    msg.file_type or '',
            'file_url':     file_url(msg),
            'is_mine':      msg.sender_id == request.user.id,
            'time':         msg.chat_time,
            'iso':          iso_str,
            'date_label':   msg.chat_date_label,
            'reply_to':     reply_preview,
            'link_preview': msg.link_preview,
            'reactions':    reactions_by_msg.get(msg.id, {}),
            'my_reaction':  user_reactions.get(msg.id, None),
        })

    partner_avatar = None
    try:
        if partner.profile.picture:
            partner_avatar = partner.profile.picture.url
    except Exception:
        pass

    return JsonResponse({
        'partner':        partner.username,
        'partner_avatar': partner_avatar,
        'messages':       messages_data,
    })


@login_required
def channel_create(request):
    if request.method == 'POST':
        # ── Profile guard ──────────────────────────────────────────────────
        can_post, missing = _profile_post_status(request.user)
        if not can_post:
            from django.contrib import messages as _msgs
            _msgs.error(
                request,
                'Complete your profile before creating a channel. Missing: ' + ', '.join(missing) + '.'
            )
            return redirect('channel_create')
        # ───────────────────────────────────────────────────────────────────

        name  = request.POST.get('name')
        about = request.POST.get('about')
        icon  = request.FILES.get('icon')
        new_channel = Channel.objects.create(
            channel_owner=request.user,
            channel_name=name,
            about=about,
            image=icon if icon else 'male.png'
        )
        new_channel.subscriber.add(request.user)
        return redirect('channel', channel_id=new_channel.channel_id)

    user_can_post, missing_fields = _profile_post_status(request.user)

    followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')

    followed_list = []
    total_unread = 0
    
    for c in followed_channels:
        unread = c.unread_count_for_user(request.user)
        total_unread += unread
        last_msg = c.channel_messages.order_by('-created_at').first()
        msg_type = 'text'
        if last_msg:
            if last_msg.file_type == 'audio':   msg_type = 'audio'
            elif last_msg.file_type == 'video': msg_type = 'video'
            elif last_msg.file_type == 'image': msg_type = 'image'
        followed_list.append({
            'channel': c, 'unread_count': unread,
            'last_message': last_msg.message if last_msg else "No messages yet",
            'last_time': last_msg.created_at if last_msg else None,
            'message_type': msg_type
        })

    unfollowed_channels = Channel.objects.exclude(subscriber=request.user).order_by('-created_at')
    context = {
        'followed_list': followed_list,
        'unfollowed_channels': unfollowed_channels,
        'total_followed_unread': total_unread,
        'user_can_post':  user_can_post,
        'missing_fields': missing_fields,
    }
    return render(request, 'channel_create.html', context)


@login_required(login_url='/')
def follow_channel(request, channel_id):
    channel = get_object_or_404(Channel, channel_id=channel_id)
    if request.user not in channel.subscriber.all():
        channel.subscriber.add(request.user)
    else:
        channel.subscriber.remove(request.user)
    return _safe_redirect_back(request, fallback='home')


@login_required
def channel(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)

    if request.user in channel_obj.blocked_users.all():
        return redirect('home')

    ChannelUserLastSeen.objects.update_or_create(
        channel=channel_obj, user=request.user,
        defaults={'last_seen_at': timezone.now()}
    )

    from social.models import ChannelMessageReaction
    from django.db.models import Count as _Count

    channel_messages_qs = ChannelMessage.objects.filter(
        channel=channel_obj
    ).select_related('author', 'author__profile', 'reply_to', 'reply_to__author').order_by('created_at')

    grouped_messages = {}
    for msg in channel_messages_qs:
        date_label = msg.chat_date_label
        if date_label not in grouped_messages:
            grouped_messages[date_label] = []
        # Attach reaction summary and current user's reaction
        reactions_qs = ChannelMessageReaction.objects.filter(message=msg).values('emoji').annotate(count=_Count('id'))
        msg.reactions_summary = {row['emoji']: row['count'] for row in reactions_qs}
        user_rxn = ChannelMessageReaction.objects.filter(message=msg, user=request.user).first()
        msg.my_reaction = user_rxn.emoji if user_rxn else None
        grouped_messages[date_label].append(msg)

    subscribed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(ch.unread_count_for_user(request.user) for ch in subscribed_channels)

    context = {
        'channel': channel_obj,
        'grouped_messages': grouped_messages,
        'channel_id': str(channel_id),
        'total_unread': total_unread,
        'is_admin': channel_obj.is_user_admin(request.user),
        'is_owner': channel_obj.channel_owner == request.user
    }
    return render(request, 'channel.html', context)


@login_required
def channel_message(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)

    if channel_obj.is_broadcast_only and not channel_obj.is_user_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'Only admins can post in this channel.'}, status=403)

    if request.method == 'POST':
        message_text = request.POST.get('message', '')
        file_upload  = request.FILES.get('file_upload')
        reply_to_id  = request.POST.get('reply_to')

        if message_text and len(message_text) > 5000:
            return JsonResponse({'status': 'error', 'message': 'Message too long.'}, status=400)

        file_type = None
        file_name = None
        if file_upload:
            raw_name = file_upload.name or 'file'
            raw_name = os.path.basename(raw_name.replace('\\', '/'))
            raw_name = re.sub(r'[^\w\s\-\.]', '', raw_name).strip()[:100] or 'file'
            file_name = raw_name
            _ext = os.path.splitext(file_name)[1].lower()
            _ALLOWED = {
                'image':    {'.jpg', '.jpeg', '.png', '.gif'},
                'video':    {'.mp4', '.mov', '.avi'},
                'audio':    {'.mp3', '.wav', '.webm', '.ogg', '.m4a'},
                'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'},
            }
            file_type = next((t for t, exts in _ALLOWED.items() if _ext in exts), None)
            if not file_type:
                return JsonResponse({'status': 'error', 'message': 'Unsupported file type'}, status=400)
            if file_upload.size > 50 * 1024 * 1024:
                return JsonResponse({'status': 'error', 'message': 'File too large. Maximum size is 50MB.'}, status=400)

        # Link preview — only for text messages containing a URL
        link_preview = None
        if message_text:
            url_match = re.search(r'https?://[^\s]+', message_text)
            if url_match:
                preview_url = url_match.group(0)
                if _is_safe_url_for_preview(preview_url):
                    try:
                        _headers = {
                            'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
                            'Accept': 'text/html,application/xhtml+xml',
                        }
                        _resp = requests.get(preview_url, headers=_headers, timeout=4,
                                             allow_redirects=True, stream=True)
                        _content = b''
                        for _chunk in _resp.iter_content(chunk_size=8192):
                            _content += _chunk
                            if len(_content) > 500_000:
                                break
                        _soup = BeautifulSoup(_content, 'html.parser')

                        def _og(prop):
                            tag = (
                                _soup.find('meta', property=f'og:{prop}')
                                or _soup.find('meta', attrs={'name': f'twitter:{prop}'})
                            )
                            return tag['content'].strip() if tag and tag.get('content') else ''

                        _image = _og('image')
                        if _image and not _image.startswith(('http://', 'https://')):
                            _image = ''

                        link_preview = {
                            'title':       html_escape((_og('title') or (_soup.title.string.strip() if _soup.title else ''))[:200]),
                            'description': html_escape(_og('description')[:400]),
                            'image':       _image[:500],
                            'domain':      html_escape(urlparse(_resp.url).netloc.replace('www.', '')[:100]),
                            'url':         preview_url,
                        }
                    except Exception:
                        link_preview = None

        channel_msg = ChannelMessage.objects.create(
            channel=channel_obj,
            author=request.user,
            message=message_text if message_text else '',
            file_type=file_type,
            file=file_upload,
            reply_to_id=reply_to_id if reply_to_id else None,
            link_preview=link_preview,
        )

        layer = get_channel_layer()
        group_name = f'channel_{channel_id}'
        file_url = channel_msg.file.url if channel_msg.file else None

        # Author avatar
        try:
            author_avatar = request.user.profile.picture.url if request.user.profile.picture else ''
        except Exception:
            author_avatar = ''

        reply_data = None
        if channel_msg.reply_to:
            reply_data = {
                'author': channel_msg.reply_to.author.username,
                'message': channel_msg.reply_to.message[:50] if channel_msg.reply_to.message else "Media file",
                'file_type': channel_msg.reply_to.file_type,
                'message_id': str(channel_msg.reply_to.channelmessage_id),
            }

        async_to_sync(layer.group_send)(
            group_name,
            {
                'type': 'channel_message',
                'author': channel_msg.author.username,
                'author_avatar': author_avatar,
                'message': channel_msg.message,
                'file_type': file_type,
                'file_url': file_url,
                'file_name': file_name or '',
                'time': channel_msg.created_at.isoformat(),
                'message_id': str(channel_msg.channelmessage_id),
                'reply_to': reply_data,
                'link_preview': link_preview,
            }
        )

        # Notify subscribers with unread counts
        subscribers = channel_obj.subscriber.exclude(id=request.user.id)
        for subscriber in subscribers:
            unread_count = channel_obj.unread_count_for_user(subscriber)
            user_group_name = f'user_{subscriber.id}_channels'
            async_to_sync(layer.group_send)(
                user_group_name,
                {
                    'type': 'unread_update',
                    'channel_id': str(channel_obj.channel_id),
                    'unread_count': unread_count,
                    'channel_name': channel_obj.channel_name,
                    'message_preview': message_text[:30] if message_text else "New media message",
                }
            )

        return JsonResponse({
            'status': 'success',
            'message_id': str(channel_msg.channelmessage_id),
            'file_url': file_url,
        })

    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


@login_required
def update_channel(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    if request.user != channel_obj.channel_owner:
        return redirect('channel', channel_id=channel_id)

    if request.method == 'POST':
        channel_obj.channel_name = request.POST.get('name', channel_obj.channel_name)
        channel_obj.about = request.POST.get('about', channel_obj.about)
        broadcast = request.POST.get('broadcast')
        channel_obj.is_broadcast_only = (broadcast == 'true')
        if request.FILES.get('image'):
            channel_obj.image = request.FILES.get('image')
        channel_obj.save()
        
    return redirect('channel', channel_id=channel_id)


@login_required
def manage_member(request, channel_id, user_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    
    if not channel_obj.is_user_admin(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            target_user = get_object_or_404(User, id=user_id)
            
            is_target_admin = channel_obj.admins.filter(id=target_user.id).exists()
            is_target_owner = (target_user == channel_obj.channel_owner)

            if (is_target_admin or is_target_owner) and request.user != channel_obj.channel_owner:
                return JsonResponse({
                    'success': False,
                    'message': 'Permission denied: Only the owner can remove admins.'
                }, status=403)
            
            if action in ('remove', 'block'):
                channel_obj.subscriber.remove(target_user)
                channel_obj.admins.remove(target_user)
                if action == 'block':
                    channel_obj.blocked_users.add(target_user)
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'message': 'Unknown action'}, status=400)

        except (json.JSONDecodeError, User.DoesNotExist):
            return JsonResponse({'success': False, 'message': 'Invalid request data'}, status=400)

    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)


@login_required
def toggle_admin(request, channel_id, user_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    if request.user != channel_obj.channel_owner:
        return JsonResponse({'success': False}, status=403)

    target_user = get_object_or_404(User, id=user_id)
    if channel_obj.admins.filter(id=target_user.id).exists():
        channel_obj.admins.remove(target_user)
    else:
        channel_obj.admins.add(target_user)
    return JsonResponse({'success': True})


@login_required
def channelmessage_like(request, channelmessage_id):
    channelmessage = get_object_or_404(ChannelMessage, channelmessage_id=channelmessage_id)
    if request.user not in channelmessage.like.all():
        channelmessage.like.add(request.user)
        liked = True
    else:
        channelmessage.like.remove(request.user)
        liked = False
    return JsonResponse({'liked': liked, 'like_count': channelmessage.like.count()})


@login_required
def delete_channel_message(request, channel_id, message_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
    try:
        channel_obj = get_object_or_404(Channel, channel_id=channel_id)
        msg_obj = get_object_or_404(ChannelMessage, channelmessage_id=message_id, channel=channel_obj)

        # Only the message author OR channel admin can delete
        if msg_obj.author != request.user and not channel_obj.is_user_admin(request.user):
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)

        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            f'channel_{channel_id}',
            {
                'type': 'message_deleted',
                'message_id': str(message_id),
            }
        )
        msg_obj.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def react_to_channel_message(request, message_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    from social.models import ChannelMessageReaction

    try:
        msg_obj = ChannelMessage.objects.select_related('channel').get(channelmessage_id=message_id)
    except ChannelMessage.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)

    # Only channel subscribers can react
    if not msg_obj.channel.subscriber.filter(id=request.user.id).exists():
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)

    try:
        body  = json.loads(request.body)
        emoji = body.get('emoji', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    ALLOWED_EMOJIS = {'❤️', '😂', '😮', '😢', '😡', '👍', '🔥', '🎉'}
    if emoji not in ALLOWED_EMOJIS:
        return JsonResponse({'status': 'error', 'message': 'Invalid emoji'}, status=400)

    existing = ChannelMessageReaction.objects.filter(message=msg_obj, user=request.user).first()

    if existing:
        if existing.emoji == emoji:
            existing.delete()
            user_reaction = None
        else:
            existing.emoji = emoji
            existing.save()
            user_reaction = emoji
    else:
        ChannelMessageReaction.objects.create(message=msg_obj, user=request.user, emoji=emoji)
        user_reaction = emoji

    from django.db.models import Count as _Count
    summary = (
        ChannelMessageReaction.objects.filter(message=msg_obj)
        .values('emoji').annotate(count=_Count('id')).order_by('emoji')
    )
    reaction_summary = {row['emoji']: row['count'] for row in summary}

    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'channel_{msg_obj.channel.channel_id}',
            {
                'type': 'message_reaction',
                'message_id': str(msg_obj.channelmessage_id),
                'reactions': reaction_summary,
                'actor': request.user.username,
                'user_reaction': user_reaction,
            }
        )
    except Exception:
        pass

    return JsonResponse({
        'status': 'success',
        'message_id': str(msg_obj.channelmessage_id),
        'reactions': reaction_summary,
        'user_reaction': user_reaction,
    })


# ======= Ads =======

@login_required(login_url='/')
def market(request):
    category = request.GET.get('category', 'all')
    if category == 'all':
        products = Market.objects.all().order_by('-posted_on')
    else:
        products = Market.objects.filter(product_category=category).order_by('-posted_on')

    products = products.select_related('business_page', 'product_owner', 'product_owner__profile')

    highest_price = products.aggregate(Max('product_price'))['product_price__max']
    lowest_price  = products.aggregate(Min('product_price'))['product_price__min']

    # ── Jumia-style category grouping ──────────────────────────────────────
    # When browsing "all" categories, group products into per-category rows
    # (each capped at a handful of items) so the template can render
    # horizontal-scroll sections per category, like Jumia's homepage.
    categories_with_products = []
    if category == 'all':
        products = products.prefetch_related('images').select_related('product_owner')
        _by_cat = {}
        for p in products:
            _by_cat.setdefault(p.product_category, []).append(p)
        # Preserve the canonical category order from CATEGORY_CHOICES,
        # only including categories that actually have listings.
        for cat_key, cat_label in Market.CATEGORY_CHOICES:
            items = _by_cat.get(cat_key)
            if items:
                categories_with_products.append({
                    'key':      cat_key,
                    'label':    cat_label,
                    'icon':     Market.CATEGORY_ICONS.get(cat_key, '📦'),
                    'products': items[:12],
                    'has_more': len(items) > 12,
                })

    filter_categories = [
        {'key': k, 'label': l, 'icon': Market.CATEGORY_ICONS.get(k, '📦')}
        for k, l in Market.CATEGORY_CHOICES
    ]

    # ── Wishlist state — so the shared mfy-jcard card can show saved hearts ──
    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    context = {
        'products':                 products,
        'highest_price':            highest_price or 0,
        'lowest_price':             lowest_price  or 0,
        'selected_category':        category,
        'categories_with_products': categories_with_products,
        'all_categories':           Market.CATEGORY_CHOICES,
        'filter_categories':        filter_categories,
        'wishlist_ids':             wishlist_ids,
    }
    return render(request, 'marketplace.html', context)


@login_required(login_url='/')
def product_detail(request, product_id):
    product = get_object_or_404(Market, product_id=product_id)
    if product.views_count is None:
        product.views_count = 0
    product.views_count += 1
    product.save()

    images = product.images.all()
    related_products = Market.objects.filter(
        product_category=product.product_category
    ).exclude(product_id=product_id)[:4]
    seller_profile = get_object_or_404(Profile, user=product.product_owner)

    in_wishlist = False
    if request.user.is_authenticated:
        in_wishlist = Wishlist.objects.filter(user=request.user, product=product).exists()

    # ── Reviews & Ratings ────────────────────────────────────────────────────
    reviews = (
        product.reviews
        .select_related('user', 'user__profile')
        .exclude(user=request.user)
        if request.user.is_authenticated else product.reviews.select_related('user', 'user__profile')
    )
    user_review = None
    if request.user.is_authenticated:
        user_review = ProductReview.objects.filter(product=product, user=request.user).select_related('user').first()
    can_review = (
        request.user.is_authenticated
        and request.user != product.product_owner
        and user_review is None
    )

    context = {
        'product': product, 'images': images,
        'related_products': related_products, 'seller': seller_profile,
        'all_categories': Market.CATEGORY_CHOICES,
        'business_page': product.business_page,
        'in_wishlist': in_wishlist,
        'reviews': reviews,
        'user_review': user_review,
        'can_review': can_review,
        'rating_breakdown': product.rating_breakdown,
    }
    return render(request, 'product_details.html', context)


@login_required(login_url='/')
@require_POST
def submit_review(request, product_id):
    """
    AJAX create/update — a buyer leaves (or edits) a star rating + comment
    on a Market listing. One review per (product, user); resubmitting
    updates the existing row instead of creating a duplicate.
    """
    import uuid as _uuid_mod
    try:
        _pid = _uuid_mod.UUID(str(product_id))
        product = get_object_or_404(Market, product_id=_pid)
    except Exception:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    if product.product_owner_id == request.user.id:
        return JsonResponse({'error': 'You cannot review your own listing.'}, status=400)

    try:
        rating = int(request.POST.get('rating', 0))
    except (TypeError, ValueError):
        rating = 0
    comment = (request.POST.get('comment') or '').strip()

    if rating < 1 or rating > 5:
        return JsonResponse({'error': 'Please select a rating between 1 and 5 stars.'}, status=400)

    existing = ProductReview.objects.filter(product=product, user=request.user).first()
    created = existing is None

    if created:
        review = ProductReview.objects.create(
            product=product, user=request.user, rating=rating, comment=comment,
        )
    else:
        existing.rating = rating
        existing.comment = comment
        existing.is_edited = True
        existing.save()
        review = existing

    seller_profile = getattr(request.user, 'profile', None)

    return JsonResponse({
        'success': True,
        'created': created,
        'review': {
            'id': str(review.id),
            'rating': review.rating,
            'comment': review.comment,
            'reviewer_name': request.user.get_full_name() or request.user.username,
            'reviewer_username': request.user.username,
            'reviewer_picture': seller_profile.get_picture_url if seller_profile and hasattr(seller_profile, 'get_picture_url') else '',
            'created_at': review.created_at.strftime('%b %d, %Y'),
            'is_edited': review.is_edited,
        },
        'average_rating': product.average_rating,
        'review_count': product.review_count,
        'rating_breakdown': product.rating_breakdown,
    })


@login_required(login_url='/')
@require_POST
def delete_review(request, product_id, review_id):
    """Delete the current user's own review on a listing."""
    import uuid as _uuid_mod
    try:
        _pid = _uuid_mod.UUID(str(product_id))
        _rid = _uuid_mod.UUID(str(review_id))
        product = get_object_or_404(Market, product_id=_pid)
        review = get_object_or_404(ProductReview, id=_rid, product=product)
    except Exception:
        return JsonResponse({'error': 'Review not found.'}, status=404)

    if review.user_id != request.user.id and not request.user.is_staff:
        return JsonResponse({'error': 'You can only delete your own review.'}, status=403)

    review.delete()

    return JsonResponse({
        'success': True,
        'average_rating': product.average_rating,
        'review_count': product.review_count,
        'rating_breakdown': product.rating_breakdown,
    })


@login_required(login_url='/')
@require_POST
def toggle_wishlist(request, product_id):
    """
    AJAX toggle — save/unsave a product for later.
    Returns JSON so the heart icon can update instantly on any page
    (product detail, marketplace grid, business page listings, etc.)
    """
    import uuid as _uuid_mod
    try:
        _pid = _uuid_mod.UUID(str(product_id))
        product = get_object_or_404(Market, product_id=_pid)
    except Exception:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    existing = Wishlist.objects.filter(user=request.user, product=product).first()
    if existing:
        existing.delete()
        saved = False
    else:
        Wishlist.objects.create(user=request.user, product=product)
        saved = True

    return JsonResponse({
        'saved': saved,
        'wishlist_count': Wishlist.objects.filter(user=request.user).count(),
    })


@login_required(login_url='/')
def wishlist_view(request):
    """
    Products the current user has saved for later.
    Reuses the Market model + the shared 'mfy-jcard' product card markup.
    """
    saved_items = (
        Wishlist.objects.filter(user=request.user)
        .select_related('product')
        .prefetch_related('product__images')
        .order_by('-created_at')
    )
    products = [item.product for item in saved_items]

    paginator = Paginator(products, 24)
    page_obj  = paginator.get_page(request.GET.get('page'))

    # ── Right-sidebar widget data (same widgets as home.html / profile.html /
    # business_page_detail.html) — always about request.user, regardless of
    # which page is being viewed.
    viewer_profile          = request.user.profile
    viewer_following_ids    = list(viewer_profile.followings.values_list('user', flat=True))
    viewer_following_count  = viewer_profile.followings.count()
    viewer_follower_count   = viewer_profile.followers.count()
    sidebar_suggested_users = list(
        User.objects.exclude(id__in=viewer_following_ids)
               .exclude(id=request.user.id)
               .order_by('?')[:3]
    )

    # ── Viewer's own business page — for the "Your business page" /
    # "Grow your business" sidebar widget.
    viewer_business_pages = (
        BusinessPage.objects.filter(owner=request.user, is_active=True)
        .order_by('-created_at')
    )
    viewer_business_page_count   = viewer_business_pages.count()
    viewer_primary_business_page = viewer_business_pages.first()

    # ── Right-sidebar "Suggestions for you" — business pages ────────────────
    followed_business_ids = set(
        BusinessPage.objects.filter(followers=request.user).values_list('page_id', flat=True)
    )
    suggested_pages = list(
        BusinessPage.objects
        .filter(is_active=True)
        .exclude(owner=request.user)
        .exclude(page_id__in=followed_business_ids)
        .select_related('owner')
        .order_by('-created_at')[:5]
    )

    return render(request, 'wishlist.html', {
        'products':      page_obj,
        'wishlist_count': len(products),
        'viewer_following_count':  viewer_following_count,
        'viewer_follower_count':   viewer_follower_count,
        'sidebar_suggested_users': sidebar_suggested_users,
        'viewer_business_page_count':   viewer_business_page_count,
        'viewer_primary_business_page': viewer_primary_business_page,
        'suggested_pages': suggested_pages,
    })


@login_required(login_url='/')
def contact_seller(request, product_id):
    import uuid as _uuid_mod
    try:
        _pid = _uuid_mod.UUID(str(product_id))
        product = get_object_or_404(Market, product_id=_pid)
    except Exception:
        return redirect('market')

    seller = product.product_owner

    # Buyer cannot message themselves
    if seller == request.user:
        return redirect('product_detail', product_id=product_id)

    # Block check
    try:
        if request.user.profile.has_blocked(seller.profile) or seller.profile.has_blocked(request.user.profile):
            from django.contrib import messages as _msgs
            _msgs.error(request, 'You cannot message this seller.')
            return redirect('product_detail', product_id=product_id)
    except Exception:
        pass

    from django.urls import reverse
    base_url = reverse('message', kwargs={'username': seller.username})
    return redirect(f"{base_url}?product={product_id}")








def get_location(request, username):
    user = Profile.objects.get(user__username=username)
    return JsonResponse({'lat': user.latitude, 'lng': user.longitude})


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request, exception):
    return render(request, '500.html', status=500)


def logout(request):
    if request.user.is_authenticated:
        try:
            from social.models import Profile
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            Profile.mark_user_offline(request.user.id)
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'online_status_group',
                {'type': 'user_status_event', 'user_id': request.user.id, 'status': 'Offline'}
            )
        except Exception:
            pass
    auth.logout(request)
    messages.info(request, 'Logout Successfully')
    return redirect('/')


@require_POST
def set_offline(request):
    logger = logging.getLogger(__name__)
    try:
        user_id = int(request.POST.get('user_id', 0))
    except (ValueError, TypeError):
        return HttpResponse(status=400)

    if not request.user.is_authenticated or request.user.id != user_id:
        return HttpResponse(status=403)

    try:
        Profile.mark_user_offline(user_id)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'online_status_group',
            {'type': 'user_status_event', 'user_id': user_id, 'status': 'Offline'}
        )
    except Exception:
        logger.exception('set_offline: failed to mark user %s offline', user_id)

    return HttpResponse(status=204)














# ─── Online Status API ────────────────────────────────────────────────────────

@login_required
def online_status_api(request, user_id):
    try:
        from social.models import Profile
        profile_obj = Profile.objects.get(user__id=user_id)
        return JsonResponse({'is_online': profile_obj.is_online})
    except Profile.DoesNotExist:
        return JsonResponse({'is_online': False})


# ─── Change Password ──────────────────────────────────────────────────────────

@login_required
@require_POST
def change_password(request):
    """
    AJAX-only endpoint. Verifies the current password then sets the new one.
    Keeps the user logged in via update_session_auth_hash.
    """
    from django.core.cache import cache
    rate_key  = f'chpw_{request.user.id}'
    pw_hits   = cache.get(rate_key, 0)
    if pw_hits >= 5:
        return JsonResponse({
            'success': False,
            'message': 'Too many password change attempts. Please try again in an hour.',
        }, status=429)
    cache.set(rate_key, pw_hits + 1, timeout=3600)

    _COMMON_PW = {
        'password', 'password1', '12345678', '123456789', 'qwerty123',
        'iloveyou', 'admin123', 'letmein1', 'welcome1', 'monkey123',
    }

    current = request.POST.get('current_password', '').strip()
    new_pw  = request.POST.get('new_password', '')
    confirm = request.POST.get('confirm_password', '')

    if not current:
        return JsonResponse({'success': False, 'message': 'Current password is required.', 'field': 'current'}, status=400)

    if not request.user.check_password(current):
        return JsonResponse({'success': False, 'message': 'Current password is incorrect.', 'field': 'current'}, status=400)

    if not new_pw:
        return JsonResponse({'success': False, 'message': 'New password is required.'}, status=400)

    if len(new_pw) < 8:
        return JsonResponse({'success': False, 'message': 'New password must be at least 8 characters.'}, status=400)

    if new_pw.lower() in _COMMON_PW:
        return JsonResponse({'success': False, 'message': 'That password is too common — please choose a stronger one.'}, status=400)

    if new_pw == current:
        return JsonResponse({'success': False, 'message': 'New password must be different from your current password.'}, status=400)

    if new_pw != confirm:
        return JsonResponse({'success': False, 'message': 'Passwords do not match.'}, status=400)

    request.user.set_password(new_pw)
    request.user.save()

    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)
    cache.delete(rate_key)

    return JsonResponse({'success': True, 'message': 'Password updated successfully!'})



@login_required(login_url='/')
def services(request):
    """
    Services landing page.
    Passes the next 5 upcoming SocialEvents (today or later) to the sidebar,
    plus per-type counts for the stats strip.
    """
    today = timezone.now().date()

    upcoming_events = (
        SocialEvent.objects
        .filter(date__gte=today)
        .order_by('date', 'time')
        [:5]
    )

    event_counts = {
        'town':     SocialEvent.objects.filter(event_type='town').count(),
        'festival': SocialEvent.objects.filter(event_type='festival').count(),
        'wedding':  SocialEvent.objects.filter(event_type='wedding').count(),
        'other':    SocialEvent.objects.filter(event_type='other').count(),
        'total':    SocialEvent.objects.count(),
    }

    return render(request, 'services.html', {
        'upcoming_events': upcoming_events,
        'event_counts':    event_counts,
    })


# ─── Event Calendar ───────────────────────────────────────────────────────────

@login_required(login_url='/')
def event_calendar(request):
    """
    Main event calendar page.
    Supports optional ?type= filter (any SocialEvent.TYPE_CHOICES key).
    """
    event_type = request.GET.get('type', '').strip()

    events = (
        SocialEvent.objects
        .select_related('created_by')
        .prefetch_related('follows')
        .all().order_by('date', 'time')
    )
    if event_type and event_type in dict(SocialEvent.TYPE_CHOICES):
        events = events.filter(event_type=event_type)

    counts = {
        key: SocialEvent.objects.filter(event_type=key).count()
        for key, _label in SocialEvent.TYPE_CHOICES
    }
    counts['total'] = SocialEvent.objects.count()

    event_type_meta = [
        {
            'key': key,
            'label': label,
            'emoji': SocialEvent.TYPE_EMOJIS.get(key, '📌'),
            'color': SocialEvent.TYPE_COLORS.get(key, '#0095f6'),
            'count': counts.get(key, 0),
        }
        for key, label in SocialEvent.TYPE_CHOICES
    ]

    # This user's current follow status per event: {event_id: 'interested'|'going'}
    my_follows = {}
    if request.user.is_authenticated:
        my_follows = dict(
            EventFollow.objects.filter(user=request.user).values_list('event_id', 'status')
        )

    events_list = list(events)
    events_js = [
        {
            'id': ev.id,
            'title': ev.title,
            'type': ev.event_type,
            'date': ev.date.isoformat(),
            'time': ev.time.strftime('%H:%M') if ev.time else '',
            'endDate': ev.end_date.isoformat() if ev.end_date else '',
            'endTime': ev.end_time.strftime('%H:%M') if ev.end_time else '',
            'location': ev.location,
            'desc': ev.description,
            'organizer': ev.organizer_name,
            'contactEmail': ev.contact_email,
            'contactPhone': ev.contact_phone,
            'isVirtual': ev.is_virtual,
            'virtualLink': ev.virtual_link,
            'isFree': ev.is_free,
            'price': str(ev.price) if ev.price is not None else '',
            'capacity': ev.capacity,
            'isCancelled': ev.is_cancelled,
            'goingCount': ev.going_count,
            'interestedCount': ev.interested_count,
            'followerCount': ev.follower_count,
            'myStatus': my_follows.get(ev.id),
            'coverImage': _event_image_url(ev),
            'isOwner': bool(request.user.is_authenticated and ev.created_by_id == request.user.id),
        }
        for ev in events_list
    ]

    user_can_post = False
    missing_fields = []
    if request.user.is_authenticated:
        user_can_post, missing_fields = _profile_post_status(request.user)

    return render(request, 'event_calendar.html', {
        'events':          events_list,
        'events_json':     json.dumps(events_js),
        'event_type':      event_type,
        'counts':          counts,
        'event_types':     SocialEvent.TYPE_CHOICES,
        'event_type_meta': event_type_meta,
        'event_type_meta_json': json.dumps(event_type_meta),
        'my_follows':      my_follows,
        'user_can_post':   user_can_post,
        'missing_fields':  missing_fields,
    })


@login_required(login_url='/')
def event_detail(request, event_id):
    """
    Full LinkedIn-style event page: cover, details, RSVP, comments,
    and the list of people who are interested/going.
    """
    event = get_object_or_404(
        SocialEvent.objects.select_related('created_by', 'created_by__profile'),
        id=event_id,
    )

    going_qs = (
        EventFollow.objects
        .filter(event=event, status=EventFollow.STATUS_GOING)
        .select_related('user', 'user__profile')
        .order_by('-created_at')
    )
    interested_qs = (
        EventFollow.objects
        .filter(event=event, status=EventFollow.STATUS_INTERESTED)
        .select_related('user', 'user__profile')
        .order_by('-created_at')
    )
    going_list = list(going_qs[:200])
    interested_list = list(interested_qs[:200])

    # Small avatar-stack preview (going first, then interested), like the LinkedIn header
    preview_follows = (going_list + interested_list)[:5]

    my_status = None
    if request.user.is_authenticated:
        fol = EventFollow.objects.filter(event=event, user=request.user).first()
        my_status = fol.status if fol else None

    is_owner = bool(request.user.is_authenticated and event.created_by_id == request.user.id)

    today = timezone.localdate()
    end_date = event.end_date or event.date
    if event.is_cancelled:
        status_label, status_class = 'Event cancelled', 'cancelled'
    elif end_date < today:
        status_label, status_class = 'Event ended', 'ended'
    elif event.date <= today <= end_date:
        status_label, status_class = 'Happening now', 'ongoing'
    else:
        status_label, status_class = 'Upcoming', 'upcoming'

    return render(request, 'event_detail.html', {
        'event':            event,
        'going_list':       going_list,
        'interested_list':  interested_list,
        'going_count':      len(going_list) if len(going_list) < 200 else event.going_count,
        'interested_count': len(interested_list) if len(interested_list) < 200 else event.interested_count,
        'preview_follows':  preview_follows,
        'my_status':        my_status,
        'is_owner':         is_owner,
        'status_label':     status_label,
        'status_class':     status_class,
        'share_url':        request.build_absolute_uri(reverse('event_detail', args=[event.id])),
        'cover_url':        _event_image_url(event),
    })


def _event_parse_and_validate(post_data, files):
    """Shared validation for create/edit. Returns (cleaned_data, error_str)."""
    title       = html_escape(post_data.get('title', '').strip())
    event_type  = post_data.get('event_type', '').strip()
    date_str    = post_data.get('date', '').strip()
    time_str    = post_data.get('time', '').strip()
    end_date_str = post_data.get('end_date', '').strip()
    end_time_str = post_data.get('end_time', '').strip()
    location    = html_escape(post_data.get('location', '').strip())
    description = html_escape(post_data.get('description', '').strip())
    cover_image = files.get('cover_image') if files else None

    organizer_name = html_escape(post_data.get('organizer_name', '').strip())
    contact_email  = post_data.get('contact_email', '').strip()
    contact_phone  = post_data.get('contact_phone', '').strip()

    is_virtual   = post_data.get('is_virtual') in ('1', 'true', 'on')
    virtual_link = post_data.get('virtual_link', '').strip()

    is_free   = post_data.get('is_free', '1') in ('1', 'true', 'on')
    price_raw = post_data.get('price', '').strip()

    capacity_raw = post_data.get('capacity', '').strip()

    if not title:
        return None, 'Title is required.'
    if event_type not in dict(SocialEvent.TYPE_CHOICES):
        return None, 'Invalid event type.'
    if not date_str:
        return None, 'Date is required.'

    try:
        ev_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None, 'Invalid date format.'

    time_obj = None
    if time_str:
        try:
            time_obj = datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            pass

    end_date_obj = None
    if end_date_str:
        try:
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date_obj = None
        if end_date_obj and end_date_obj < ev_date:
            return None, 'End date cannot be before the start date.'

    end_time_obj = None
    if end_time_str:
        try:
            end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            pass

    if is_virtual and virtual_link:
        try:
            virtual_link = validate_url(virtual_link)
        except _ModelValidationError:
            return None, 'Please enter a valid virtual event link.'
    elif not is_virtual:
        virtual_link = ''

    price_val = None
    if not is_free:
        try:
            price_val = float(price_raw) if price_raw else None
            if price_val is not None and price_val < 0:
                return None, 'Price cannot be negative.'
        except ValueError:
            return None, 'Please enter a valid price.'

    capacity_val = None
    if capacity_raw:
        try:
            capacity_val = int(capacity_raw)
            if capacity_val < 1:
                return None, 'Capacity must be at least 1.'
        except ValueError:
            return None, 'Please enter a valid capacity.'

    if contact_email:
        try:
            from django.core.validators import validate_email
            validate_email(contact_email)
        except _ModelValidationError:
            return None, 'Please enter a valid contact email.'

    if cover_image:
        _ALLOWED_IMG = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if cover_image.content_type not in _ALLOWED_IMG:
            return None, 'Only JPEG, PNG, WebP or GIF images are allowed.'
        if cover_image.size > 10 * 1024 * 1024:
            return None, 'Image must be under 10 MB.'

    return {
        'title': title, 'event_type': event_type, 'date': ev_date,
        'time': time_obj, 'end_date': end_date_obj, 'end_time': end_time_obj,
        'location': location, 'description': description,
        'organizer_name': organizer_name, 'contact_email': contact_email,
        'contact_phone': contact_phone, 'is_virtual': is_virtual,
        'virtual_link': virtual_link, 'is_free': is_free, 'price': price_val,
        'capacity': capacity_val, 'cover_image': cover_image,
    }, None


def _event_image_url(event):
    """Return a public URL for the event's cover image, or None."""
    if not event.cover_image:
        return None
    try:
        from cloudinary.utils import cloudinary_url
        url, _ = cloudinary_url(str(event.cover_image), secure=True)
        return url
    except Exception:
        pass
    try:
        return event.cover_image.url
    except Exception:
        return None


def _event_serialize(event, request_user=None):
    """Shared JSON shape for an event, including 'useful info' + follow state."""
    my_status = None
    if request_user is not None and request_user.is_authenticated:
        fol = EventFollow.objects.filter(event=event, user=request_user).first()
        my_status = fol.status if fol else None

    return {
        'id':              event.id,
        'title':           event.title,
        'event_type':      event.event_type,
        'event_type_label': event.get_event_type_display(),
        'date':            event.date.isoformat(),
        'time':            event.time.strftime('%H:%M') if event.time else '',
        'end_date':        event.end_date.isoformat() if event.end_date else '',
        'end_time':        event.end_time.strftime('%H:%M') if event.end_time else '',
        'location':        event.location,
        'description':     event.description,
        'organizer_name':  event.organizer_name,
        'contact_email':   event.contact_email,
        'contact_phone':   event.contact_phone,
        'is_virtual':      event.is_virtual,
        'virtual_link':    event.virtual_link,
        'is_free':         event.is_free,
        'price':           str(event.price) if event.price is not None else '',
        'capacity':        event.capacity,
        'spots_left':      event.spots_left,
        'is_cancelled':    event.is_cancelled,
        'cover_image':     _event_image_url(event),
        'is_owner':        bool(request_user and request_user.is_authenticated and event.created_by_id == request_user.id),
        'follower_count':  event.follower_count,
        'going_count':     event.going_count,
        'interested_count': event.interested_count,
        'my_status':       my_status,
    }


def _notify_event_followers(event, actor, notif_type):
    """Bulk-create EventNotifications for everyone following an event (except the actor)."""
    recipients = list(
        EventFollow.objects.filter(event=event, notify=True)
        .exclude(user=actor)
        .values_list('user_id', flat=True)
    )
    if not recipients:
        return
    EventNotification.objects.bulk_create([
        EventNotification(notif_type=notif_type, event=event, actor=actor, to_user_id=uid)
        for uid in recipients
    ])


@login_required(login_url='/')
@require_POST
def event_calendar_create(request):
    """AJAX endpoint — create a new SocialEvent from the in-page modal."""
    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before posting events. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'error': msg, 'error_code': 'incomplete_profile'}, status=403)

    data, err = _event_parse_and_validate(request.POST, request.FILES)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)

    event = SocialEvent(
        title=data['title'],
        event_type=data['event_type'],
        date=data['date'],
        time=data['time'],
        end_date=data['end_date'],
        end_time=data['end_time'],
        location=data['location'],
        description=data['description'],
        organizer_name=data['organizer_name'] or request.user.get_full_name() or request.user.username,
        contact_email=data['contact_email'],
        contact_phone=data['contact_phone'],
        is_virtual=data['is_virtual'],
        virtual_link=data['virtual_link'],
        is_free=data['is_free'],
        price=data['price'],
        capacity=data['capacity'],
        created_by=request.user,
    )
    if data['cover_image']:
        event.cover_image = data['cover_image']
    event.save()

    # Organizer automatically "goes" and follows their own event for notifications
    EventFollow.objects.get_or_create(
        event=event, user=request.user, defaults={'status': EventFollow.STATUS_GOING}
    )

    return JsonResponse({'success': True, 'event': _event_serialize(event, request.user)})


@login_required(login_url='/')
@require_POST
def event_calendar_edit(request, event_id):
    """AJAX endpoint — edit an existing SocialEvent (owner only)."""
    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before editing events. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'error': msg, 'error_code': 'incomplete_profile'}, status=403)

    event = get_object_or_404(SocialEvent, id=event_id)
    if event.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    data, err = _event_parse_and_validate(request.POST, request.FILES)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)

    event.title           = data['title']
    event.event_type      = data['event_type']
    event.date             = data['date']
    event.time              = data['time']
    event.end_date          = data['end_date']
    event.end_time          = data['end_time']
    event.location          = data['location']
    event.description       = data['description']
    event.organizer_name    = data['organizer_name']
    event.contact_email     = data['contact_email']
    event.contact_phone     = data['contact_phone']
    event.is_virtual        = data['is_virtual']
    event.virtual_link      = data['virtual_link']
    event.is_free           = data['is_free']
    event.price             = data['price']
    event.capacity          = data['capacity']

    if data['cover_image']:
        # Delete old Cloudinary image if present
        if event.cover_image:
            try:
                import cloudinary.uploader as _cu
                _cu.destroy(str(event.cover_image))
            except Exception:
                pass
        event.cover_image = data['cover_image']

    # Allow clearing the image
    if request.POST.get('clear_image') == '1' and event.cover_image:
        try:
            import cloudinary.uploader as _cu
            _cu.destroy(str(event.cover_image))
        except Exception:
            pass
        event.cover_image = None

    event.save()

    # Let interested/going followers know the event changed
    _notify_event_followers(event, request.user, EventNotification.EVENT_UPDATED)

    return JsonResponse({'success': True, 'event': _event_serialize(event, request.user)})


@login_required(login_url='/')
@require_POST
def event_calendar_delete(request, event_id):
    """AJAX endpoint — delete a SocialEvent (owner only)."""
    event = get_object_or_404(SocialEvent, id=event_id)
    if event.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    # Notify followers before the event (and its notifications, via CASCADE) disappear
    _notify_event_followers(event, request.user, EventNotification.EVENT_CANCELLED)

    if event.cover_image:
        try:
            import cloudinary.uploader as _cu
            _cu.destroy(str(event.cover_image))
        except Exception:
            pass

    event.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def event_follow_toggle(request, event_id):
    """
    AJAX endpoint — LinkedIn-style Follow/RSVP toggle.
    POST body: status = 'interested' | 'going' | 'none' (none = unfollow).
    """
    event = get_object_or_404(SocialEvent, id=event_id)
    status = request.POST.get('status', '').strip()

    if status == 'none':
        EventFollow.objects.filter(event=event, user=request.user).delete()
        return JsonResponse({
            'success': True, 'status': None,
            'follower_count': event.follower_count,
            'going_count': event.going_count,
            'interested_count': event.interested_count,
        })

    if status not in (EventFollow.STATUS_INTERESTED, EventFollow.STATUS_GOING):
        return JsonResponse({'success': False, 'error': 'Invalid status.'}, status=400)

    if event.is_full and status == EventFollow.STATUS_GOING:
        already_going = EventFollow.objects.filter(
            event=event, user=request.user, status=EventFollow.STATUS_GOING
        ).exists()
        if not already_going:
            return JsonResponse({'success': False, 'error': 'This event is full.'}, status=409)

    EventFollow.objects.update_or_create(
        event=event, user=request.user, defaults={'status': status, 'notify': True}
    )

    return JsonResponse({
        'success': True, 'status': status,
        'follower_count': event.follower_count,
        'going_count': event.going_count,
        'interested_count': event.interested_count,
    })


# =============================================================================
# JOB VACANCY VIEWS - Updated to work with Cloudinary in both debug/production
# =============================================================================

@login_required(login_url='/')
def job_vacancy(request):
    """
    Job Vacancy listing page.
    Supports optional ?category= filter (gig | fulltime | apprenticeship).
    """
    category  = request.GET.get('category', '').strip()
    work_mode = request.GET.get('work_mode', '').strip()

    qs = JobVacancy.objects.filter(is_open=True).select_related('posted_by__profile')
    if category and category in dict(JobVacancy.CATEGORY_CHOICES):
        qs = qs.filter(category=category)
    if work_mode and work_mode in dict(JobVacancy.WORK_MODE_CHOICES):
        qs = qs.filter(work_mode=work_mode)

    counts = {
        'gig':            JobVacancy.objects.filter(is_open=True, category='gig').count(),
        'fulltime':       JobVacancy.objects.filter(is_open=True, category='fulltime').count(),
        'apprenticeship': JobVacancy.objects.filter(is_open=True, category='apprenticeship').count(),
        'total':          JobVacancy.objects.filter(is_open=True).count(),
    }

    work_mode_counts = {
        'on_site': JobVacancy.objects.filter(is_open=True, work_mode='on_site').count(),
        'remote':  JobVacancy.objects.filter(is_open=True, work_mode='remote').count(),
        'hybrid':  JobVacancy.objects.filter(is_open=True, work_mode='hybrid').count(),
    }

    paginator = Paginator(qs, 12)
    page_obj  = paginator.get_page(request.GET.get('page'))

    user_can_post, missing_fields = _profile_post_status(request.user)

    return render(request, 'job_vacancy.html', {
        'jobs':             page_obj,
        'counts':           counts,
        'work_mode_counts': work_mode_counts,
        'category':         category,
        'work_mode':        work_mode,
        'user_can_post':    user_can_post,
        'missing_fields':   missing_fields,
    })


def job_detail(request, job_id):
    """
    Full-page detail view for a single Job Vacancy — mirrors product_detail.
    """
    job = get_object_or_404(
        JobVacancy.objects.select_related('posted_by__profile', 'business_page'),
        id=job_id,
    )

    related_jobs = JobVacancy.objects.filter(
        category=job.category, is_open=True
    ).exclude(id=job.id).select_related('posted_by__profile')[:4]

    poster_profile = get_object_or_404(Profile, user=job.posted_by)

    # ── Vibe reactions summary ──────────────────────────────────────────────
    vibe_rows = (
        JobVibe.objects.filter(job=job)
        .values('vibe_type')
        .annotate(cnt=Count('id'))
    )
    vibe_summary = {r['vibe_type']: r['cnt'] for r in vibe_rows}
    vibe_total = sum(vibe_summary.values())

    user_vibe = None
    if request.user.is_authenticated:
        v = JobVibe.objects.filter(job=job, user=request.user).first()
        if v:
            user_vibe = v.vibe_type

    vibe_data = [
        {
            'value':  value,
            'label':  label,
            'emoji':  JobVibe.VIBE_EMOJIS.get(value, ''),
            'color':  JobVibe.VIBE_COLORS.get(value, '#0095f6'),
            'count':  vibe_summary.get(value, 0),
            'active': user_vibe == value,
        }
        for value, label in JobVibe.VIBE_CHOICES
    ]

    # ── Comments ─────────────────────────────────────────────────────────────
    comments = (
        JobComment.objects.filter(job=job)
        .select_related('author', 'author__profile')
        .order_by('created_at')[:50]
    )
    comments_count = JobComment.objects.filter(job=job).count()

    is_owner = request.user.is_authenticated and request.user == job.posted_by

    context = {
        'job':             job,
        'related_jobs':    related_jobs,
        'poster':          poster_profile,
        'business_page':   job.business_page,
        'is_owner':        is_owner,
        'vibe_summary':    vibe_summary,
        'vibe_total':      vibe_total,
        'user_vibe':       user_vibe,
        'vibe_data':       vibe_data,
        'comments':        comments,
        'comments_count':  comments_count,
    }
    return render(request, 'job_details.html', context)


def contact_poster(request, job_id):
    """AJAX/redirect target for messaging a job poster — mirrors contact_seller."""
    job = get_object_or_404(JobVacancy, id=job_id)
    poster = job.posted_by

    if poster == request.user:
        return redirect('job_detail', job_id=job_id)

    if not request.user.is_authenticated:
        return redirect('/')

    try:
        if request.user.profile.has_blocked(poster.profile) or poster.profile.has_blocked(request.user.profile):
            from django.contrib import messages as _msgs
            _msgs.error(request, 'You cannot message this poster.')
            return redirect('job_detail', job_id=job_id)
    except Exception:
        pass

    from django.urls import reverse
    base_url = reverse('message', kwargs={'username': poster.username})
    return redirect(f"{base_url}?job={job_id}")


@login_required(login_url='/')
@require_POST
def job_vacancy_create(request):
    """AJAX — create a new JobVacancy."""
    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before posting jobs. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'error': msg, 'error_code': 'incomplete_profile'}, status=403)

    title           = html_escape(request.POST.get('title', '').strip())
    category        = request.POST.get('category', '').strip()
    work_mode       = request.POST.get('work_mode', '').strip()
    advertiser_type = request.POST.get('advertiser_type', '').strip()
    company         = html_escape(request.POST.get('company', '').strip())
    location        = html_escape(request.POST.get('location', '').strip())
    description     = html_escape(request.POST.get('description', '').strip())
    requirements    = html_escape(request.POST.get('requirements', '').strip())
    contact_info    = html_escape(request.POST.get('contact_info', '').strip())
    salary_range    = html_escape(request.POST.get('salary_range', '').strip())
    cover_image     = request.FILES.get('cover_image')
    page_slug       = request.POST.get('business_page', '').strip()

    if not title:
        return JsonResponse({'success': False, 'error': 'Job title is required.'}, status=400)
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid category.'}, status=400)
    if not work_mode:
        work_mode = JobVacancy.WORK_ONSITE
    if work_mode not in dict(JobVacancy.WORK_MODE_CHOICES):
        return JsonResponse({'success': False, 'error': 'Please select a valid work mode (On-site, Remote, or Hybrid).'}, status=400)
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required.'}, status=400)
    if not advertiser_type:
        advertiser_type = JobVacancy.ADV_PERSONAL
    if advertiser_type not in dict(JobVacancy.ADVERTISER_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid advertiser type.'}, status=400)

    apply_link, link_error = _clean_apply_link(request.POST.get('apply_link', ''))
    if link_error:
        return JsonResponse({'success': False, 'error': link_error}, status=400)

    # Optional — post this job vacancy under one of the user's own business pages
    business_page = None
    if page_slug:
        business_page = get_object_or_404(BusinessPage, slug=page_slug)
        if business_page.owner != request.user:
            return JsonResponse({'success': False, 'error': 'Not authorised for that business page.'}, status=403)
        if not company:
            company = business_page.name

    job = JobVacancy(
        posted_by       = request.user,
        title           = title,
        category        = category,
        work_mode       = work_mode,
        advertiser_type = advertiser_type,
        company         = company,
        location        = location,
        description     = description,
        requirements    = requirements,
        contact_info    = contact_info,
        apply_link      = apply_link,
        salary_range    = salary_range,
        business_page   = business_page,
    )

    if cover_image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if cover_image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if cover_image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)
        
        job.cover_image = cover_image

    job.save()

    return JsonResponse({
        'success': True,
        'job': {
            'id':        str(job.id),
            'title':     job.title,
            'category':  job.category,
            'work_mode': job.work_mode,
        }
    })


@login_required(login_url='/')
@require_POST
def job_vacancy_edit(request, job_id):
    """AJAX — edit an existing JobVacancy (owner only)."""
    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before editing jobs. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'error': msg, 'error_code': 'incomplete_profile'}, status=403)

    job = get_object_or_404(JobVacancy, id=job_id)
    if job.posted_by != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    title           = html_escape(request.POST.get('title', '').strip())
    category        = request.POST.get('category', '').strip()
    work_mode       = request.POST.get('work_mode', '').strip()
    advertiser_type = request.POST.get('advertiser_type', '').strip()
    company         = html_escape(request.POST.get('company', '').strip())
    location        = html_escape(request.POST.get('location', '').strip())
    description     = html_escape(request.POST.get('description', '').strip())
    requirements    = html_escape(request.POST.get('requirements', '').strip())
    contact_info    = html_escape(request.POST.get('contact_info', '').strip())
    salary_range    = html_escape(request.POST.get('salary_range', '').strip())
    is_open         = request.POST.get('is_open', '1').strip() == '1'
    cover_image     = request.FILES.get('cover_image')
    page_slug       = request.POST.get('business_page', None)

    if not title:
        return JsonResponse({'success': False, 'error': 'Job title is required.'}, status=400)
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid category.'}, status=400)
    if not work_mode:
        work_mode = JobVacancy.WORK_ONSITE
    if work_mode not in dict(JobVacancy.WORK_MODE_CHOICES):
        return JsonResponse({'success': False, 'error': 'Please select a valid work mode (On-site, Remote, or Hybrid).'}, status=400)
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required.'}, status=400)
    if not advertiser_type:
        advertiser_type = JobVacancy.ADV_PERSONAL
    if advertiser_type not in dict(JobVacancy.ADVERTISER_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid advertiser type.'}, status=400)

    apply_link, link_error = _clean_apply_link(request.POST.get('apply_link', ''))
    if link_error:
        return JsonResponse({'success': False, 'error': link_error}, status=400)

    # Optional — reassign the business page this job is posted under (owner only)
    if page_slug is not None:
        if page_slug.strip() == '':
            job.business_page = None
        else:
            business_page = get_object_or_404(BusinessPage, slug=page_slug.strip())
            if business_page.owner != request.user:
                return JsonResponse({'success': False, 'error': 'Not authorised for that business page.'}, status=403)
            job.business_page = business_page

    job.title           = title
    job.category        = category
    job.work_mode       = work_mode
    job.advertiser_type = advertiser_type
    job.company         = company
    job.location        = location
    job.description     = description
    job.requirements    = requirements
    job.contact_info    = contact_info
    job.apply_link      = apply_link
    job.salary_range    = salary_range
    job.is_open         = is_open

    if cover_image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if cover_image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if cover_image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)
        
        job.cover_image = cover_image

    job.save()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def job_vacancy_delete(request, job_id):
    """AJAX — delete a JobVacancy (owner only)."""
    job = get_object_or_404(JobVacancy, id=job_id)
    if job.posted_by != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)
    
    # Delete cover image from Cloudinary if it exists
    if job.cover_image:
        try:
            import cloudinary.uploader as _cu
            _cu.destroy(job.cover_image)
        except Exception:
            pass
    
    job.delete()
    return JsonResponse({'success': True})

# =============================================================================
# Card Vibe & Comment Views — Market ads, Job vacancies, Social events
# =============================================================================

def _card_vibe_toggle(request, obj, VibeCls, fk_field):
    """
    Generic vibe toggle for Market / Job / Event cards.
    Returns JSON matching the shape of get_post_vibes.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login required'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        body = json.loads(request.body)
        vibe_type = body.get('vibe_type', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    allowed = {'fire', 'real', 'vibing', 'dead', 'cringe', 'chill', 'love'}
    if vibe_type not in allowed:
        return JsonResponse({'error': 'invalid vibe_type'}, status=400)

    existing = VibeCls.objects.filter(**{fk_field: obj, 'user': request.user}).first()

    if existing:
        if existing.vibe_type == vibe_type:
            existing.delete()
            user_vibe = None
        else:
            existing.vibe_type = vibe_type
            existing.save(update_fields=['vibe_type'])
            user_vibe = vibe_type
    else:
        VibeCls.objects.create(**{fk_field: obj, 'user': request.user, 'vibe_type': vibe_type})
        user_vibe = vibe_type

    rows = (
        VibeCls.objects.filter(**{fk_field: obj})
        .values('vibe_type')
        .annotate(cnt=Count('id'))
    )
    summary = {r['vibe_type']: r['cnt'] for r in rows}
    total = sum(summary.values())

    return JsonResponse({'user_vibe': user_vibe, 'summary': summary, 'total': total})


def _card_vibe_get(request, obj, VibeCls, fk_field):
    """GET vibe summary for a card (hydration on scroll-into-view)."""
    rows = (
        VibeCls.objects.filter(**{fk_field: obj})
        .values('vibe_type')
        .annotate(cnt=Count('id'))
    )
    summary = {r['vibe_type']: r['cnt'] for r in rows}
    total   = sum(summary.values())

    user_vibe = None
    if request.user.is_authenticated:
        v = VibeCls.objects.filter(**{fk_field: obj, 'user': request.user}).first()
        if v:
            user_vibe = v.vibe_type

    return JsonResponse({'user_vibe': user_vibe, 'summary': summary, 'total': total})


def _card_comments_get(request, obj, CommentCls, fk_field):
    """GET latest 50 comments for a card."""
    qs = (
        CommentCls.objects.filter(**{fk_field: obj})
        .select_related('author', 'author__profile')
        .order_by('created_at')[:50]
    )
    data = [{
        'id':          str(c.id),
        'text':        c.text,
        'author':      c.author.username,
        'author_name': f"{c.author.first_name} {c.author.last_name}".strip() or c.author.username,
        'avatar':      c.author.profile.get_picture_url,
        'time':        c.created_at.strftime('%b %d'),
    } for c in qs]
    return JsonResponse({'comments': data, 'count': CommentCls.objects.filter(**{fk_field: obj}).count()})


def _card_comments_post(request, obj, CommentCls, fk_field):
    """POST a new comment on a card."""
    try:
        body = json.loads(request.body)
        text = body.get('text', '').strip()
    except (json.JSONDecodeError, AttributeError):
        text = request.POST.get('text', '').strip()

    if not text:
        return JsonResponse({'error': 'comment cannot be empty'}, status=400)
    if len(text) > 5000:
        return JsonResponse({'error': 'comment too long'}, status=400)

    comment = CommentCls.objects.create(**{fk_field: obj, 'author': request.user, 'text': text})
    return JsonResponse({
        'id':          str(comment.id),
        'text':        comment.text,
        'author':      request.user.username,
        'author_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
        'avatar':      request.user.profile.get_picture_url,
        'time':        comment.created_at.strftime('%b %d'),
        'count':       CommentCls.objects.filter(**{fk_field: obj}).count(),
    })


def _notify_profile_item_vibe(request, item, section, notif_fk_field, response):
    """
    Generic vibe-notification sync for the profile's 'extra' sections
    (Portfolio/Project, Achievement, Experience, Education, Service).
    Mirrors profile_post_vibe / business_post_vibe's get-or-create-or-delete
    pattern, but keyed off ProfileItemNotification's `section` field plus
    whichever of its five target FKs applies (`notif_fk_field`, e.g.
    'portfolio_item', 'achievement', ...).
    """
    if response.status_code != 200:
        return
    owner = item.owner_user
    if owner == request.user:
        return
    try:
        data = json.loads(response.content)
        user_vibe = data.get('user_vibe')
        lookup = {
            'notif_type': ProfileItemNotification.NEW_VIBE,
            'section': section,
            'actor': request.user,
            notif_fk_field: item,
        }
        if user_vibe:
            # One reaction notification per (item, actor) — re-vibing
            # (or switching vibe types) refreshes it instead of spamming
            # a new row for every tap.
            notif, created = ProfileItemNotification.objects.get_or_create(
                **lookup, defaults={'to_user': owner, 'vibe_type': user_vibe},
            )
            if not created:
                notif.vibe_type  = user_vibe
                notif.is_read    = False
                notif.created_at = timezone.now()
                notif.save(update_fields=['vibe_type', 'is_read', 'created_at'])
        else:
            # Un-reacting removes the notification entirely.
            ProfileItemNotification.objects.filter(**lookup).delete()
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            'Failed to sync vibe notification for %s %s', section, getattr(item, 'pk', None)
        )


def _notify_profile_item_comment(request, item, section, notif_fk_field, response):
    """Generic comment-notification creation counterpart to
    _notify_profile_item_vibe — notifies the item owner unless they
    commented on their own item."""
    if response.status_code != 200:
        return
    owner = item.owner_user
    if owner == request.user:
        return
    try:
        ProfileItemNotification.objects.create(
            notif_type=ProfileItemNotification.NEW_COMMENT,
            section=section,
            actor=request.user,
            to_user=owner,
            **{notif_fk_field: item},
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            'Failed to create comment notification for %s %s', section, getattr(item, 'pk', None)
        )


# ── Job vacancy reactions ──────────────────────────────────────────────────────

@login_required(login_url='/')
def job_vibe(request, job_id):
    job = get_object_or_404(JobVacancy, id=job_id)
    if request.method == 'GET':
        return _card_vibe_get(request, job, JobVibe, 'job')
    return _card_vibe_toggle(request, job, JobVibe, 'job')


@login_required(login_url='/')
def job_comments(request, job_id):
    job = get_object_or_404(JobVacancy, id=job_id)
    if request.method == 'POST':
        return _card_comments_post(request, job, JobComment, 'job')
    return _card_comments_get(request, job, JobComment, 'job')


# ── Social event reactions ─────────────────────────────────────────────────────

@login_required(login_url='/')
def event_vibe(request, event_id):
    event = get_object_or_404(SocialEvent, id=event_id)
    if request.method == 'GET':
        return _card_vibe_get(request, event, EventVibe, 'event')
    return _card_vibe_toggle(request, event, EventVibe, 'event')


@login_required(login_url='/')
def event_comments(request, event_id):
    event = get_object_or_404(SocialEvent, id=event_id)
    if request.method == 'POST':
        response = _card_comments_post(request, event, EventComment, 'event')
        if response.status_code == 200:
            _notify_event_followers(event, request.user, EventNotification.NEW_COMMENT)
        return response
    return _card_comments_get(request, event, EventComment, 'event')


# ── Business page post reactions & comments ────────────────────────────────

@login_required(login_url='/')
def business_post_vibe(request, post_id):
    post = get_object_or_404(BusinessPost, pk=post_id)
    if request.method == 'GET':
        return _card_vibe_get(request, post, BusinessPostVibe, 'post')

    response = _card_vibe_toggle(request, post, BusinessPostVibe, 'post')

    if response.status_code == 200 and post.business_page.owner != request.user:
        try:
            data = json.loads(response.content)
            user_vibe = data.get('user_vibe')
            if user_vibe:
                # One reaction notification per (post, actor) — re-vibing
                # (or switching vibe types) refreshes it instead of spamming
                # a new row for every tap.
                notif, created = BusinessNotification.objects.get_or_create(
                    notif_type=BusinessNotification.NEW_VIBE,
                    business_page=post.business_page,
                    actor=request.user,
                    post=post,
                    defaults={'to_user': post.business_page.owner, 'vibe_type': user_vibe},
                )
                if not created:
                    notif.vibe_type  = user_vibe
                    notif.is_read    = False
                    notif.created_at = timezone.now()
                    notif.save(update_fields=['vibe_type', 'is_read', 'created_at'])
            else:
                # Un-reacting removes the notification entirely.
                BusinessNotification.objects.filter(
                    notif_type=BusinessNotification.NEW_VIBE,
                    business_page=post.business_page,
                    actor=request.user,
                    post=post,
                ).delete()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to sync vibe notification for post %s', post.pk
            )

    return response


@login_required(login_url='/')
def business_post_comments(request, post_id):
    post = get_object_or_404(BusinessPost, pk=post_id)
    if request.method == 'POST':
        response = _card_comments_post(request, post, BusinessPostComment, 'post')
        if response.status_code == 200:
            # Notify the page owner someone commented, unless they commented
            # on their own post.
            try:
                if post.business_page.owner != request.user:
                    BusinessNotification.objects.create(
                        notif_type=BusinessNotification.NEW_COMMENT,
                        business_page=post.business_page,
                        actor=request.user,
                        to_user=post.business_page.owner,
                        post=post,
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Failed to create comment notification for post %s', post.pk
                )
        return response
    return _card_comments_get(request, post, BusinessPostComment, 'post')


# ── Profile — Portfolio / Project reactions & comments ─────────────────────

@login_required(login_url='/')
def profile_portfolio_vibe(request, item_id):
    item = get_object_or_404(ProfilePortfolioItem, item_id=item_id)
    if request.method == 'GET':
        return _card_vibe_get(request, item, ProfilePortfolioItemVibe, 'item')
    response = _card_vibe_toggle(request, item, ProfilePortfolioItemVibe, 'item')
    _notify_profile_item_vibe(request, item, ProfileItemNotification.PORTFOLIO, 'portfolio_item', response)
    return response


@login_required(login_url='/')
def profile_portfolio_comments(request, item_id):
    item = get_object_or_404(ProfilePortfolioItem, item_id=item_id)
    if request.method == 'POST':
        response = _card_comments_post(request, item, ProfilePortfolioItemComment, 'item')
        _notify_profile_item_comment(request, item, ProfileItemNotification.PORTFOLIO, 'portfolio_item', response)
        return response
    return _card_comments_get(request, item, ProfilePortfolioItemComment, 'item')


# ── Profile — Achievement reactions & comments ──────────────────────────────

@login_required(login_url='/')
def profile_achievement_vibe(request, achievement_id):
    achievement = get_object_or_404(ProfileAchievement, achievement_id=achievement_id)
    if request.method == 'GET':
        return _card_vibe_get(request, achievement, ProfileAchievementVibe, 'achievement')
    response = _card_vibe_toggle(request, achievement, ProfileAchievementVibe, 'achievement')
    _notify_profile_item_vibe(request, achievement, ProfileItemNotification.ACHIEVEMENT, 'achievement', response)
    return response


@login_required(login_url='/')
def profile_achievement_comments(request, achievement_id):
    achievement = get_object_or_404(ProfileAchievement, achievement_id=achievement_id)
    if request.method == 'POST':
        response = _card_comments_post(request, achievement, ProfileAchievementComment, 'achievement')
        _notify_profile_item_comment(request, achievement, ProfileItemNotification.ACHIEVEMENT, 'achievement', response)
        return response
    return _card_comments_get(request, achievement, ProfileAchievementComment, 'achievement')


# ── Profile — Experience reactions & comments ───────────────────────────────

@login_required(login_url='/')
def profile_experience_vibe(request, experience_id):
    experience = get_object_or_404(ProfileExperience, experience_id=experience_id)
    if request.method == 'GET':
        return _card_vibe_get(request, experience, ProfileExperienceVibe, 'experience')
    response = _card_vibe_toggle(request, experience, ProfileExperienceVibe, 'experience')
    _notify_profile_item_vibe(request, experience, ProfileItemNotification.EXPERIENCE, 'experience', response)
    return response


@login_required(login_url='/')
def profile_experience_comments(request, experience_id):
    experience = get_object_or_404(ProfileExperience, experience_id=experience_id)
    if request.method == 'POST':
        response = _card_comments_post(request, experience, ProfileExperienceComment, 'experience')
        _notify_profile_item_comment(request, experience, ProfileItemNotification.EXPERIENCE, 'experience', response)
        return response
    return _card_comments_get(request, experience, ProfileExperienceComment, 'experience')


# ── Profile — Education reactions & comments ────────────────────────────────

@login_required(login_url='/')
def profile_education_vibe(request, education_id):
    education = get_object_or_404(ProfileEducation, education_id=education_id)
    if request.method == 'GET':
        return _card_vibe_get(request, education, ProfileEducationVibe, 'education')
    response = _card_vibe_toggle(request, education, ProfileEducationVibe, 'education')
    _notify_profile_item_vibe(request, education, ProfileItemNotification.EDUCATION, 'education', response)
    return response


@login_required(login_url='/')
def profile_education_comments(request, education_id):
    education = get_object_or_404(ProfileEducation, education_id=education_id)
    if request.method == 'POST':
        response = _card_comments_post(request, education, ProfileEducationComment, 'education')
        _notify_profile_item_comment(request, education, ProfileItemNotification.EDUCATION, 'education', response)
        return response
    return _card_comments_get(request, education, ProfileEducationComment, 'education')


# ── Profile — Service reactions & comments ──────────────────────────────────

@login_required(login_url='/')
def profile_service_vibe(request, service_id):
    service = get_object_or_404(ProfileService, service_id=service_id)
    if request.method == 'GET':
        return _card_vibe_get(request, service, ProfileServiceVibe, 'service')
    response = _card_vibe_toggle(request, service, ProfileServiceVibe, 'service')
    _notify_profile_item_vibe(request, service, ProfileItemNotification.SERVICE, 'service', response)
    return response


@login_required(login_url='/')
def profile_service_comments(request, service_id):
    service = get_object_or_404(ProfileService, service_id=service_id)
    if request.method == 'POST':
        response = _card_comments_post(request, service, ProfileServiceComment, 'service')
        _notify_profile_item_comment(request, service, ProfileItemNotification.SERVICE, 'service', response)
        return response
    return _card_comments_get(request, service, ProfileServiceComment, 'service')


# =============================================================================
# ADMIN DASHBOARD VIEWS
# Add these to the bottom of your existing views.py
# =============================================================================

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Count
from social.models import (
    Profile, UserReport, BlockedUser,
    Message, Channel, Market, SocialEvent, JobVacancy, BusinessPage,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Main admin dashboard
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_dashboard(request):
    """
    Central KVibe admin dashboard.
    Accessible only to staff / superuser accounts.
    """
    from datetime import date

    context = {
        # ── Overview counts ───────────────────────────────────────────────
        'total_users':     User.objects.count(),
        'online_users':    Profile.objects.filter(online=True).count(),
        'total_products':  Market.objects.count(),
        'total_channels':  Channel.objects.count(),
        # SocialEvent field is `date` (not event_date)
        'upcoming_events': SocialEvent.objects.filter(date__gte=date.today()).count(),
        'pending_reports': UserReport.objects.filter(status='pending').count(),
        'total_reports':   UserReport.objects.count(),
        # ── Recent users ──────────────────────────────────────────────────
        'recent_users': (
            User.objects
            .select_related('profile')
            .order_by('-date_joined')[:10]
        ),

        # ── Recent reports ────────────────────────────────────────────────
        'recent_reports': (
            UserReport.objects
            .select_related('reporter__profile', 'reported__profile')
            .order_by('-created_at')[:5]
        ),

        # ── All users ─────────────────────────────────────────────────────
        'all_users': (
            User.objects
            .select_related('profile')
            .order_by('-date_joined')
        ),

        # ── All reports ───────────────────────────────────────────────────
        'all_reports': (
            UserReport.objects
            .select_related('reporter__profile', 'reported__profile')
            .order_by('-created_at')
        ),

        # ── Blocked list ──────────────────────────────────────────────────
        'blocked_list': (
            BlockedUser.objects
            .select_related('blocker__profile', 'blocked__profile')
            .order_by('-created_at')[:100]
        ),

        # ── Channels
        # Channel fields: channel_owner, channel_name, subscriber (M2M), channel_messages (related_name)
        'all_channels': (
            Channel.objects
            .select_related('channel_owner__profile')
            .prefetch_related('subscriber', 'channel_messages')
            .order_by('-created_at')
        ),

        # ── Marketplace
        # Market fields: product_owner (FK), product_name, product_price, posted_on (DateTimeField)
        'all_products': (
            Market.objects
            .select_related('product_owner__profile')
            .order_by('-posted_on')
        ),

        # ── Events
        # SocialEvent fields: title, event_type, date, time, location, description, created_by, vibes (related)
        'all_events': (
            SocialEvent.objects
            .select_related('created_by__profile')
            .prefetch_related('vibes')
            .order_by('-date')
        ),

        # ── Jobs
        # JobVacancy fields: id (UUID PK), posted_by, title, category, is_open, created_at
        'all_jobs': (
            JobVacancy.objects
            .select_related('posted_by__profile')
            .order_by('-created_at')
        ),

        # ── Recent messages
        # Message fields: sender, receiver, conversation (text), file_type, created_at
        'recent_messages': (
            Message.objects
            .select_related('sender__profile', 'receiver__profile')
            .order_by('-created_at')[:100]
        ),
    }

    return render(request, 'social/admin_dashboard.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Resolve / update a UserReport status
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
@require_POST
def admin_resolve_report(request, report_id):
    report = get_object_or_404(UserReport, id=report_id)
    new_status = request.POST.get('status', 'reviewed')
    allowed = {'reviewed', 'resolved', 'dismissed'}
    if new_status in allowed:
        report.status = new_status
        report.save(update_fields=['status'])
        messages.success(request, f'Report updated to "{new_status}".')
    else:
        messages.error(request, 'Invalid status value.')
    return redirect('/admin-dashboard/#reports')


# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Delete a user
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_delete_user(request, user_id):
    target = get_object_or_404(User, id=user_id)
    if target.is_staff or target.is_superuser:
        messages.error(request, 'Cannot delete staff or superuser accounts.')
        return redirect('/admin-dashboard/#users')
    username = target.username
    target.delete()
    messages.success(request, f'User "{username}" has been deleted.')
    return redirect('/admin-dashboard/#users')




# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Delete a channel
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_delete_channel(request, channel_id):
    ch = get_object_or_404(Channel, channel_id=channel_id)
    name = ch.channel_name  # real field name is channel_name
    ch.delete()
    messages.success(request, f'Channel "{name}" deleted.')
    return redirect('/admin-dashboard/#channels')


# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Delete a product
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_delete_product(request, product_id):
    product = get_object_or_404(Market, product_id=product_id)
    name = product.product_name
    product.delete()
    messages.success(request, f'Product "{name}" deleted.')
    return redirect('/admin-dashboard/#market')


# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Delete an event
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_delete_event(request, event_id):
    event = get_object_or_404(SocialEvent, id=event_id)
    title = event.title
    event.delete()
    messages.success(request, f'Event "{title}" deleted.')
    return redirect('/admin-dashboard/#events')


# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Delete a job
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
def admin_delete_job(request, job_id):
    # JobVacancy PK is `id` (UUID) — not job_id
    job = get_object_or_404(JobVacancy, id=job_id)
    title = job.title
    job.delete()
    messages.success(request, f'Job "{title}" deleted.')
    return redirect('/admin-dashboard/#jobs')



# ─────────────────────────────────────────────────────────────────────────────
# Admin action: Verify / unverify a user (toggles Profile.is_verify)
# ─────────────────────────────────────────────────────────────────────────────

@staff_member_required
@require_POST
def admin_verify_user(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile = target.profile
    profile.is_verify = not profile.is_verify
    profile.save(update_fields=['is_verify'])
    state = 'verified' if profile.is_verify else 'unverified'
    messages.success(request, f'User "{target.username}" is now {state}.')
    return redirect('/admin-dashboard/#users')
    
    
# ─────────────────────────────────────────────────────────────────────────────
# Seller: Edit a marketplace product (AJAX / multipart POST)
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def edit_product(request, product_id):
    """
    Owner-only endpoint to update a marketplace listing.
    Accepts multipart/form-data so the seller can add new images.
    Returns JSON so the JS modal can update the page inline.
    """
    from django.http import JsonResponse
    from urllib.parse import urlparse as _urlparse

    product = get_object_or_404(Market, product_id=product_id)

    # Ownership check
    if request.user != product.product_owner:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    # ── Allowlists ──────────────────────────────────────────────────────────
    from social.models import Market as _MarketModel
    _VALID_CATEGORIES   = _MarketModel.VALID_CATEGORIES
    _VALID_CONDITIONS   = {'New', 'Used', 'Used-Fair'}
    _VALID_AVAILABILITY = {'Single Item', 'In Stock'}

    product_name         = request.POST.get('product_name', '').strip()
    product_price        = request.POST.get('product_price', '').strip()
    product_location     = request.POST.get('location', '').strip()
    product_description  = request.POST.get('description', '').strip()
    product_availability = request.POST.get('availability', 'Single Item')
    product_category     = request.POST.get('category', '').strip()
    product_condition    = request.POST.get('product_condition', 'New')
    whatsapp_number      = request.POST.get('whatsapp_number', '').strip()

    # Clamp enum fields
    if product_availability not in _VALID_AVAILABILITY:
        product_availability = 'Single Item'
    if product_condition not in _VALID_CONDITIONS:
        product_condition = 'New'

    # ── Validation ──────────────────────────────────────────────────────────
    errors = {}
    if not product_name:
        errors['product_name'] = 'Ad title is required.'
    if not product_price:
        errors['product_price'] = 'Price is required.'
    else:
        try:
            price_val = int(float(product_price))
            if price_val < 0:
                errors['product_price'] = 'Price cannot be negative.'
            elif price_val > 1_000_000_000:
                errors['product_price'] = 'Price is too high.'
        except (ValueError, TypeError):
            errors['product_price'] = 'Enter a valid price.'

    if not product_category or product_category not in _VALID_CATEGORIES:
        errors['product_category'] = 'Please select a valid category.'
    if not product_description:
        errors['product_description'] = 'Description is required.'
    if not whatsapp_number:
        errors['whatsapp_number'] = 'WhatsApp number is required.'

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    # ── Sanitise free-text ───────────────────────────────────────────────────
    try:
        from social.models import sanitize_text as _sanitize
        product_name        = _sanitize(product_name, 'product_name')
        product_description = _sanitize(product_description, 'product_description')
        product_location    = _sanitize(product_location)
    except Exception:
        pass  # sanitize_text is a best-effort helper; never block a save on its failure

    # ── Apply changes ────────────────────────────────────────────────────────
    product.product_name         = product_name
    product.product_price        = int(float(product_price))
    product.product_location     = product_location
    product.product_description  = product_description
    product.product_availability = product_availability
    product.product_category     = product_category
    product.product_condition    = product_condition
    product.whatsapp_number      = whatsapp_number
    product.save()

    # ── Delete images that the seller removed in the modal ───────────────────
    delete_ids_raw = request.POST.getlist('delete_image_ids')
    if delete_ids_raw:
        for raw_id in delete_ids_raw:
            try:
                img_obj = MarketImage.objects.get(id=int(raw_id), product=product)
                img_obj.delete()
            except (MarketImage.DoesNotExist, ValueError, TypeError):
                pass  # already gone or bad id – silently skip

    # ── Add new images ────────────────────────────────────────────────────────
    new_images = request.FILES.getlist('new_images')
    current_count = product.images.count()
    slots_left = max(0, 5 - current_count)
    for img_file in new_images[:slots_left]:
        MarketImage.objects.create(product=product, product_image=img_file)

    return JsonResponse({
        'success':             True,
        'product_name':        product.product_name,
        'product_price':       product.product_price,
        'product_description': product.product_description,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Seller: Delete a marketplace product (AJAX POST)
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def delete_product(request, product_id):
    """
    Owner-only endpoint to permanently delete a marketplace listing.
    Returns JSON so the modal JS can redirect after success.
    """
    from django.http import JsonResponse

    product = get_object_or_404(Market, product_id=product_id)

    if request.user != product.product_owner:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    try:
        product.delete()
        return JsonResponse({'success': True})
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            'delete_product failed for user %s product %s', request.user.id, product_id
        )
        return JsonResponse({'success': False, 'error': 'Something went wrong. Please try again.'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Custom error handlers — must be registered in root urls.py as:
#   handler404 = 'social.views.handler404'
#   handler500 = 'social.views.handler500'
# These only activate when DEBUG = False.
# ─────────────────────────────────────────────────────────────────────────────

def handler404(request, exception=None):
    return render(request, '404.html', status=404)


def handler500(request):
    return render(request, '500.html', status=500)

# =============================================================================
# BUSINESS PAGE VIEWS
# Products/listings use the existing Market + MarketImage models.
# =============================================================================

_HOURS_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _parse_business_hours_from_post(post_data):
    """
    Build a sanitized business_hours dict from per-day POST fields:
    hours_<day>_open, hours_<day>_close, hours_<day>_closed ('on' checkbox).
    Invalid or incomplete rows are simply marked closed rather than raising.
    """
    from social.models import BusinessPage
    hours = {}
    for day in BusinessPage.DAY_ORDER:
        closed = post_data.get(f'hours_{day}_closed') == 'on'
        open_v = post_data.get(f'hours_{day}_open', '').strip()
        close_v = post_data.get(f'hours_{day}_close', '').strip()
        if closed or not open_v or not close_v or not _HOURS_TIME_RE.match(open_v) or not _HOURS_TIME_RE.match(close_v):
            hours[day] = {'open': '', 'close': '', 'closed': True}
        else:
            hours[day] = {'open': open_v, 'close': close_v, 'closed': False}
    return hours


@login_required(login_url='/')
def business_page_create(request):
    from social.models import BusinessPage
    if BusinessPage.objects.filter(owner=request.user).count() >= 3:
        messages.error(request, 'You can create up to 3 business pages.')
        return redirect('business_pages_mine')

    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        category    = request.POST.get('category', 'others').strip()
        page_type   = request.POST.get('page_type', BusinessPage.PAGE_TYPE_BUSINESS).strip()
        tagline     = request.POST.get('tagline', '').strip()
        description = request.POST.get('description', '').strip()
        location    = request.POST.get('location', '').strip()
        website     = request.POST.get('website', '').strip()
        whatsapp    = request.POST.get('whatsapp', '').strip()
        phone       = request.POST.get('phone', '').strip()
        email_val   = request.POST.get('email', '').strip()
        instagram   = request.POST.get('instagram', '').strip()
        youtube     = request.POST.get('youtube', '').strip()
        facebook    = request.POST.get('facebook', '').strip()
        twitter     = request.POST.get('twitter', '').strip()
        tiktok      = request.POST.get('tiktok', '').strip()

        errors = {}
        if not name:
            errors['name'] = 'Business name is required.'
        elif len(name) > 150:
            errors['name'] = 'Name must be 150 characters or fewer.'
        if category not in {c[0] for c in BusinessPage.CATEGORY_CHOICES}:
            category = 'others'
        if page_type not in dict(BusinessPage.PAGE_TYPE_CHOICES):
            page_type = BusinessPage.PAGE_TYPE_BUSINESS

        # Products are opt-in — "sells_products" checkbox on the form.
        # Falls back to the page type's sensible default when the field is
        # simply missing (e.g. JS-disabled client), but an explicit "0"
        # from the toggle always wins.
        if 'sells_products' in request.POST:
            sells_products = request.POST.get('sells_products') in ('1', 'true', 'on')
        else:
            sells_products = page_type in BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT

        # Optional sections — checkboxes named "sections". Falls back to the
        # page type's defaults when the owner hasn't touched any checkboxes.
        posted_sections = [s for s in request.POST.getlist('sections') if s in BusinessPage.VALID_OPTIONAL_SECTIONS]
        enabled_sections = posted_sections if posted_sections else BusinessPage.default_sections_for(page_type)

        # Pre-sanitize URL fields BEFORE they hit BusinessPage.full_clean()'s
        # built-in field validators. full_clean() runs clean_fields() (strict
        # Django URLField/EmailField validation on the RAW value) before it
        # runs our custom clean() method, which is where https:// normally
        # gets prepended. Without this, "yourbusiness.com" (no scheme) fails
        # validation before clean() ever has a chance to fix it up, save()
        # raises, and the page silently fails to create.
        for _field_name, _val in (('website', website), ('youtube', youtube), ('facebook', facebook)):
            if _val:
                try:
                    fixed = validate_url(_val)
                except _ModelValidationError:
                    errors[_field_name] = 'Please enter a valid URL.'
                    fixed = ''
                if _field_name == 'website':
                    website = fixed
                elif _field_name == 'youtube':
                    youtube = fixed
                else:
                    facebook = fixed

        _create_context_extra = {
            'categories':          BusinessPage.CATEGORY_CHOICES,
            'day_choices':         BusinessPage.DAY_CHOICES,
            'page_type_choices':   BusinessPage.PAGE_TYPE_CHOICES,
            'section_choices':     BusinessPage.OPTIONAL_SECTION_CHOICES,
            'page_type_defaults':  BusinessPage.PAGE_TYPE_SECTION_DEFAULTS,
            'page_types_selling':  list(BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT),
            'page_type_defaults_json': _json.dumps(BusinessPage.PAGE_TYPE_SECTION_DEFAULTS),
            'page_types_selling_json': _json.dumps(list(BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT)),
        }

        if errors:
            return render(request, 'business_page_create.html', {
                'errors': errors, 'form_data': request.POST,
                **_create_context_extra,
            })

        business_hours = _parse_business_hours_from_post(request.POST)

        page = BusinessPage(
            owner=request.user, name=name, category=category, page_type=page_type,
            sells_products=sells_products, enabled_sections=enabled_sections,
            tagline=tagline, description=description, location=location,
            website=website, whatsapp=whatsapp, phone=phone, email=email_val,
            instagram=instagram, youtube=youtube, facebook=facebook,
            twitter=twitter, tiktok=tiktok, business_hours=business_hours,
        )
        if request.FILES.get('logo'):        page.logo        = request.FILES['logo']
        if request.FILES.get('cover_photo'): page.cover_photo = request.FILES['cover_photo']

        try:
            page.save()
        except _ModelValidationError as exc:
            # full_clean() failed on something not caught above (e.g. email
            # format). message_dict maps field -> [messages]; fall back to a
            # flat list if Django didn't attach it to specific fields.
            field_errors = getattr(exc, 'message_dict', None) or {'__all__': exc.messages}
            for field, msgs in field_errors.items():
                errors[field if field != '__all__' else 'name'] = ' '.join(msgs)
            messages.error(request, 'Please fix the highlighted fields and try again.')
            return render(request, 'business_page_create.html', {
                'errors': errors, 'form_data': request.POST,
                **_create_context_extra,
            })
        except Exception as exc:
            messages.error(request, f'Could not create page: {exc}')
            return render(request, 'business_page_create.html', {
                'errors': {}, 'form_data': request.POST,
                **_create_context_extra,
            })

        messages.success(request, f'"{page.name}" is live! 🎉')
        next_intent = request.POST.get('next_intent', '').strip()
        redirect_url = reverse('business_page_detail', kwargs={'slug': page.slug})
        if next_intent in ('open_post', 'open_product'):
            redirect_url += f'?{next_intent}=1'
        return redirect(redirect_url)

    return render(request, 'business_page_create.html', {
        'categories':         BusinessPage.CATEGORY_CHOICES,
        'day_choices':        BusinessPage.DAY_CHOICES,
        'page_type_choices':  BusinessPage.PAGE_TYPE_CHOICES,
        'section_choices':    BusinessPage.OPTIONAL_SECTION_CHOICES,
        'page_type_defaults': BusinessPage.PAGE_TYPE_SECTION_DEFAULTS,
        'page_types_selling': list(BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT),
        'page_type_defaults_json': _json.dumps(BusinessPage.PAGE_TYPE_SECTION_DEFAULTS),
        'page_types_selling_json': _json.dumps(list(BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT)),
    })


@login_required(login_url='/')
def business_page_detail(request, slug):
    """
    Public page view.
    Listings are Market objects tagged with this page via Market.business_page FK.
    Clicking a product goes to the existing product_detail view.
    """
    from social.models import BusinessPage
    page        = get_object_or_404(BusinessPage, slug=slug, is_active=True)
    listings    = Market.objects.filter(business_page=page).order_by('-posted_on').prefetch_related('images')
    is_owner    = request.user == page.owner
    is_follower = page.followers.filter(pk=request.user.pk).exists()

    # Jobs tagged with this page via JobVacancy.business_page FK — owner sees
    # closed listings too, everyone else only sees open ones.
    jobs = JobVacancy.objects.filter(business_page=page)
    if not is_owner:
        jobs = jobs.filter(is_open=True)
    jobs = jobs.order_by('-created_at')

    # ── Optional professional-page sections ─────────────────────────────────
    services = BusinessService.objects.filter(business_page=page, is_active=True).order_by('order', '-created_at') \
        if (page.show_services or is_owner) else BusinessService.objects.none()
    portfolio_items = BusinessPortfolioItem.objects.filter(business_page=page, kind=BusinessPortfolioItem.KIND_PORTFOLIO).order_by('order', '-created_at').prefetch_related('extra_images') \
        if (page.show_portfolio or is_owner) else BusinessPortfolioItem.objects.none()
    project_items = BusinessPortfolioItem.objects.filter(business_page=page, kind=BusinessPortfolioItem.KIND_PROJECT).order_by('order', '-created_at').prefetch_related('extra_images') \
        if (page.show_projects or is_owner) else BusinessPortfolioItem.objects.none()
    achievements = BusinessAchievement.objects.filter(business_page=page).order_by('order', '-date_achieved', '-created_at') \
        if (page.show_achievements or is_owner) else BusinessAchievement.objects.none()

    # ── Reviews & Ratings ────────────────────────────────────────────────
    reviews = (
        BusinessReview.objects.filter(business_page=page)
        .select_related('user', 'user__profile')
        .order_by('-created_at')
    )
    viewer_review = None
    if request.user.is_authenticated:
        viewer_review = reviews.filter(user=request.user).first()

    posts = (
        BusinessPost.objects.filter(business_page=page)
        .prefetch_related('images', 'poll__options__votes', 'vibes', 'comments')
        .order_by('-is_pinned', '-created_at')
    )
    # Attach each poll's total vote count + the viewer's own selected option ids,
    # plus the viewer's own reaction on the post — so the template can render
    # everything without extra queries per post.
    for _post in posts:
        if _post.post_type == BusinessPost.TYPE_POLL and hasattr(_post, 'poll'):
            _poll = _post.poll
            _total = sum(o.vote_count for o in _poll.options.all())
            _poll.viewer_total_votes = _total
            _poll.viewer_voted_ids = _poll.voted_option_ids(request.user)
            for _opt in _poll.options.all():
                _opt.viewer_pct = _opt.vote_pct(_total)
        _post.viewer_vibe = None
        _post.viewer_vibe_emoji = ''
        if request.user.is_authenticated:
            _mine = next((v for v in _post.vibes.all() if v.user_id == request.user.pk), None)
            if _mine:
                _post.viewer_vibe = _mine.vibe_type
                _post.viewer_vibe_emoji = BusinessPostVibe.VIBE_EMOJIS.get(_mine.vibe_type, '')

    wishlist_ids = set(
        Wishlist.objects.filter(user=request.user, product__business_page=page)
        .values_list('product_id', flat=True)
    ) if request.user.is_authenticated else set()

    # Products the user has already saved to their wishlist shouldn't be
    # shown again in the page's listing grid — but the owner should still
    # see their own full catalog when managing the page.
    if request.user.is_authenticated and not is_owner and wishlist_ids:
        listings = listings.exclude(product_id__in=wishlist_ids)

    # ── Logged-in viewer's own business page — for the right-sidebar
    # "My Listings" shortcut (always about request.user, not the page
    # being viewed). Mirrors the same widget on home.html / profile.html.
    viewer_primary_business_page = None
    if request.user.is_authenticated:
        viewer_primary_business_page = (
            BusinessPage.objects.filter(owner=request.user, is_active=True)
            .order_by('-created_at')
            .first()
        )

    return render(request, 'business_page_detail.html', {
        'page':              page,
        'listings':          listings,
        'jobs':              jobs,
        'job_count':         jobs.count(),
        'posts':             posts,
        'post_count':        posts.count(),
        'post_type_choices': BusinessPost.POST_TYPE_CHOICES,
        'post_category_choices': BusinessPost.POST_CATEGORY_CHOICES,
        'services':          services,
        'service_count':     services.count(),
        'portfolio_items':   portfolio_items,
        'portfolio_count':   portfolio_items.count(),
        'project_items':     project_items,
        'project_count':     project_items.count(),
        'achievements':      achievements,
        'achievement_count': achievements.count(),
        'reviews':           reviews,
        'review_list_count': reviews.count(),
        'viewer_review':     viewer_review,
        'review_rating_choices': BusinessReview.RATING_CHOICES,
        'vibe_choices': [
            {'type': t, 'emoji': BusinessPostVibe.VIBE_EMOJIS[t], 'label': label.split(' ', 1)[-1]}
            for t, label in BusinessPostVibe.VIBE_CHOICES
        ],
        'is_owner':          is_owner,
        'is_follower':       is_follower,
        'follower_count':    page.follower_count,
        'listing_count':     listings.count(),
        'market_categories': Market.CATEGORY_CHOICES,
        'job_categories':    JobVacancy.CATEGORY_CHOICES,
        'wishlist_ids':      wishlist_ids,
        'is_open_now':       page.is_open_now,
        'today_hours':       page.today_hours,
        'hours_display':     page.hours_display,
        'average_rating':    page.overall_average_rating,
        'review_count':      page.overall_review_count,
        'has_verified_contact': page.has_verified_contact,
        'completed_work_count': page.completed_work_count,
        'viewer_primary_business_page': viewer_primary_business_page,
    })


@login_required(login_url='/')
@require_POST
def business_page_follow(request, slug):
    from social.models import BusinessPage
    page = get_object_or_404(BusinessPage, slug=slug, is_active=True)
    if request.user == page.owner:
        return JsonResponse({'error': 'You cannot follow your own page.'}, status=400)
    if page.followers.filter(pk=request.user.pk).exists():
        page.followers.remove(request.user)
        following = False
    else:
        page.followers.add(request.user)
        following = True
        # ── Notify the page owner that someone joined the page ──────────────
        try:
            BusinessNotification.objects.create(
                notif_type=BusinessNotification.NEW_FOLLOWER,
                business_page=page,
                actor=request.user,
                to_user=page.owner,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to create new_follower notification for page %s', page.slug
            )
    return JsonResponse({'following': following, 'follower_count': page.follower_count})


# =============================================================================
# Business page updates/feed — image, video, text, poll posts
# =============================================================================

def _serialize_professional_post(post, viewer=None):
    """Serializes either a BusinessPost or a ProfilePost — the two share the
    same post_type/post_category values, so this stays owner-agnostic."""
    data = {
        'post_id':    str(post.post_id),
        'post_type':  post.post_type,
        'post_category': post.post_category,
        'category_label': post.category_label,
        'caption':    post.caption,
        'is_pinned':  post.is_pinned,
        'time_posted': post.time_posted,
        'images':     [],
        'video_url':  '',
        'video_duration': post.video_duration_display,
        'poll':       None,
        'vibe_count':    post.vibe_count,
        'comment_count': post.comment_count,
    }
    if post.post_type == 'image':
        data['images'] = [img.get_image_url for img in post.images.all()]
    elif post.post_type == 'video':
        data['video_url'] = post.get_video_url
    elif post.post_type == 'poll' and hasattr(post, 'poll'):
        poll = post.poll
        total = sum(o.vote_count for o in poll.options.all())
        voted_ids = {str(i) for i in poll.voted_option_ids(viewer)} if viewer else set()
        data['poll'] = {
            'poll_id':        str(poll.poll_id),
            'question':       poll.question,
            'allow_multiple': poll.allow_multiple,
            'is_closed':      poll.is_closed,
            'total_votes':    total,
            'options': [
                {
                    'option_id':  str(opt.option_id),
                    'text':       opt.text,
                    'vote_count': opt.vote_count,
                    'pct':        opt.vote_pct(total),
                    'voted':      str(opt.option_id) in voted_ids,
                }
                for opt in poll.options.all()
            ],
        }
    return data


@login_required(login_url='/')
@require_POST
def business_post_create(request, slug):
    """AJAX — owner posts an image / video / text / poll update to their page."""
    page = get_object_or_404(BusinessPage, slug=slug)
    if page.owner != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised for that business page.'}, status=403)

    post_type = request.POST.get('post_type', '').strip()
    caption   = request.POST.get('caption', '').strip()
    post_category = request.POST.get('post_category', BusinessPost.CATEGORY_UPDATE).strip()
    if post_category not in dict(BusinessPost.POST_CATEGORY_CHOICES):
        post_category = BusinessPost.CATEGORY_UPDATE

    if post_type not in dict(BusinessPost.POST_TYPE_CHOICES):
        return JsonResponse({'success': False, 'error': 'Please choose a valid post type.'}, status=400)

    if post_type == BusinessPost.TYPE_TEXT and not caption:
        return JsonResponse({'success': False, 'error': 'Please write something to post.'}, status=400)

    if post_type == BusinessPost.TYPE_IMAGE:
        images = request.FILES.getlist('images')
        if not images:
            return JsonResponse({'success': False, 'error': 'Please attach at least one image.'}, status=400)
        if len(images) > 10:
            return JsonResponse({'success': False, 'error': 'You can attach up to 10 images per post.'}, status=400)
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        for img in images:
            if img.content_type not in allowed_types:
                return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
            if img.size > 10 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'Each image must be under 10 MB.'}, status=400)

    elif post_type == BusinessPost.TYPE_VIDEO:
        video = request.FILES.get('video')
        if not video:
            return JsonResponse({'success': False, 'error': 'Please attach a video.'}, status=400)
        allowed_video_types = {'video/mp4', 'video/quicktime', 'video/webm', 'video/x-msvideo'}
        if video.content_type not in allowed_video_types:
            return JsonResponse({'success': False, 'error': 'Only MP4, MOV, WebM or AVI videos are allowed.'}, status=400)
        if video.size > 100 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Video must be under 100 MB.'}, status=400)
        raw_duration = request.POST.get('video_duration_seconds', '').strip()
        duration = None
        if raw_duration:
            try:
                duration = int(float(raw_duration))
            except ValueError:
                duration = None
        if duration is not None and not (BusinessPost.MIN_VIDEO_SECONDS <= duration <= BusinessPost.MAX_VIDEO_SECONDS):
            return JsonResponse({
                'success': False,
                'error': f'Videos should be {BusinessPost.MIN_VIDEO_SECONDS}\u201390 seconds long.'
            }, status=400)

    elif post_type == BusinessPost.TYPE_POLL:
        question = request.POST.get('poll_question', '').strip()
        option_texts = [o.strip() for o in request.POST.getlist('poll_options') if o.strip()]
        if not question:
            return JsonResponse({'success': False, 'error': 'Please give your poll a question.'}, status=400)
        if len(option_texts) < 2:
            return JsonResponse({'success': False, 'error': 'Polls need at least 2 options.'}, status=400)
        if len(option_texts) > 6:
            return JsonResponse({'success': False, 'error': 'Polls can have up to 6 options.'}, status=400)

    try:
        post = BusinessPost(business_page=page, post_type=post_type, post_category=post_category, caption=caption)

        if post_type == BusinessPost.TYPE_VIDEO:
            post.video = video
            if duration is not None:
                post.video_duration_seconds = duration

        post.save()

        if post_type == BusinessPost.TYPE_IMAGE:
            for idx, img in enumerate(images):
                BusinessPostImage.objects.create(post=post, image=img, order=idx)

        elif post_type == BusinessPost.TYPE_POLL:
            allow_multiple = request.POST.get('allow_multiple') in ('1', 'true', 'on')
            closes_at = None
            raw_closes = request.POST.get('closes_at', '').strip()
            if raw_closes:
                parsed = django_parse_datetime(raw_closes)
                if parsed:
                    closes_at = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
            poll = BusinessPostPoll.objects.create(
                post=post, question=question, allow_multiple=allow_multiple, closes_at=closes_at,
            )
            for idx, text in enumerate(option_texts):
                BusinessPostPollOption.objects.create(poll=poll, text=text, order=idx)

    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    post = (
        BusinessPost.objects.filter(pk=post.pk)
        .prefetch_related('images', 'poll__options')
        .first()
    )
    return JsonResponse({
        'success': True,
        'post': _serialize_professional_post(post, viewer=request.user),
        'post_count': page.post_count,
    })


@login_required(login_url='/')
@require_POST
def business_post_delete(request, post_id):
    """AJAX — delete a BusinessPost (page owner or profile owner only)."""
    post = get_object_or_404(BusinessPost, pk=post_id)
    if post.owner_user != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    if not settings.USE_CLOUDINARY:
        for img in post.images.all():
            if img.image:
                img.image.delete(save=False)
        if post.video:
            post.video.delete(save=False)
    else:
        try:
            import cloudinary.uploader as _cu
            for img in post.images.all():
                if img.image:
                    _cu.destroy(str(img.image))
            if post.video:
                _cu.destroy(str(post.video), resource_type='video')
        except Exception:
            pass

    post.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def business_post_poll_vote(request, post_id):
    """AJAX — cast (or change) a vote on a BusinessPost poll."""
    post = get_object_or_404(BusinessPost.objects.select_related('poll'), pk=post_id)
    if post.post_type != BusinessPost.TYPE_POLL or not hasattr(post, 'poll'):
        return JsonResponse({'success': False, 'error': 'This post is not a poll.'}, status=400)

    poll = post.poll
    if poll.is_closed:
        return JsonResponse({'success': False, 'error': 'This poll is closed.'}, status=400)

    option_ids = request.POST.getlist('option_ids')
    if not option_ids:
        return JsonResponse({'success': False, 'error': 'Please select an option.'}, status=400)
    if not poll.allow_multiple and len(option_ids) > 1:
        return JsonResponse({'success': False, 'error': 'This poll only allows one choice.'}, status=400)

    options = list(poll.options.filter(option_id__in=option_ids))
    if len(options) != len(set(option_ids)):
        return JsonResponse({'success': False, 'error': 'Invalid option selected.'}, status=400)

    # Voting again replaces the viewer's previous choice(s) on this poll.
    BusinessPostPollVote.objects.filter(option__poll=poll, user=request.user).delete()
    for opt in options:
        BusinessPostPollVote.objects.create(option=opt, user=request.user)

    fresh_options = poll.options.all()
    total = sum(o.vote_count for o in fresh_options)
    return JsonResponse({
        'success': True,
        'poll': {
            'total_votes': total,
            'options': [
                {'option_id': str(o.option_id), 'vote_count': o.vote_count, 'pct': o.vote_pct(total)}
                for o in fresh_options
            ],
        },
    })


@login_required(login_url='/')
def business_page_edit(request, slug):
    from social.models import BusinessPage
    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user)

    if request.method == 'POST':
        page.name        = request.POST.get('name', page.name).strip()
        page.category    = request.POST.get('category', page.category).strip()
        posted_page_type = request.POST.get('page_type', page.page_type).strip()
        if posted_page_type in dict(BusinessPage.PAGE_TYPE_CHOICES):
            page.page_type = posted_page_type
        if 'sells_products' in request.POST:
            page.sells_products = request.POST.get('sells_products') in ('1', 'true', 'on')
        # The edit form always renders the sections checkbox group, so an
        # empty list here means the owner deliberately unchecked everything.
        page.enabled_sections = [s for s in request.POST.getlist('sections') if s in BusinessPage.VALID_OPTIONAL_SECTIONS]
        page.tagline     = request.POST.get('tagline', '').strip()
        page.description = request.POST.get('description', '').strip()
        page.location    = request.POST.get('location', '').strip()
        page.website     = request.POST.get('website', '').strip()
        page.whatsapp    = request.POST.get('whatsapp', '').strip()
        page.phone       = request.POST.get('phone', '').strip()
        page.email       = request.POST.get('email', '').strip()
        page.instagram   = request.POST.get('instagram', '').strip()
        page.youtube     = request.POST.get('youtube', '').strip()
        page.facebook    = request.POST.get('facebook', '').strip()
        page.twitter     = request.POST.get('twitter', '').strip()
        page.tiktok      = request.POST.get('tiktok', '').strip()
        page.business_hours = _parse_business_hours_from_post(request.POST)
        if request.FILES.get('logo'):        page.logo        = request.FILES['logo']
        if request.FILES.get('cover_photo'): page.cover_photo = request.FILES['cover_photo']
        try:
            page.save()
            messages.success(request, 'Page updated.')
        except Exception as exc:
            messages.error(request, f'Update failed: {exc}')
        return redirect('business_page_detail', slug=page.slug)

    return render(request, 'business_page_edit.html', {
        'page': page, 'categories': BusinessPage.CATEGORY_CHOICES,
        'day_choices': BusinessPage.DAY_CHOICES,
        'hours_display': page.hours_display,
        'page_type_choices': BusinessPage.PAGE_TYPE_CHOICES,
        'section_choices': BusinessPage.OPTIONAL_SECTION_CHOICES,
        'page_type_defaults_json': _json.dumps(BusinessPage.PAGE_TYPE_SECTION_DEFAULTS),
        'page_types_selling_json': _json.dumps(list(BusinessPage.PAGE_TYPES_SELLING_BY_DEFAULT)),
    })


@login_required(login_url='/')
def business_pages_mine(request):
    from social.models import BusinessPage
    pages = BusinessPage.objects.filter(owner=request.user).order_by('-created_at')
    return render(request, 'business_pages_mine.html', {'pages': pages})


@login_required(login_url='/')
def business_pages_list(request):
    from social.models import BusinessPage
    category = request.GET.get('category', '').strip()
    qs = BusinessPage.objects.filter(is_active=True).order_by('-created_at')
    if category:
        qs = qs.filter(category=category)
    paginator = Paginator(qs, 24)
    page_obj  = paginator.get_page(request.GET.get('page'))
    return render(request, 'business_pages_list.html', {
        'pages':      page_obj,
        'categories': BusinessPage.CATEGORY_CHOICES,
        'active_cat': category,
    })


@login_required(login_url='/')
@require_POST
def business_product_upload(request, slug):
    """
    Owner posts a new Market listing tagged to their business page.
    Uses the existing Market + MarketImage models — no separate product model.
    Returns JSON for inline page update; product links to product_detail view.
    """
    from social.models import BusinessPage

    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user, is_active=True)

    if not page.sells_products:
        return JsonResponse({
            'success': False,
            'errors': {'__all__': 'Products are turned off for this page. Enable "Sell Products" in Edit Page to add listings.'},
        }, status=403)

    # ── Rate limit: max 10 listings per hour (reuse market rate-limit key) ──
    _rl_key  = f'ad_post:{request.user.id}'
    _rl_hits = cache.get(_rl_key, 0)
    if _rl_hits >= 10:
        return JsonResponse({'success': False, 'errors': {'__all__': 'Too many listings posted. Please wait.'}}, status=429)
    cache.set(_rl_key, _rl_hits + 1, timeout=3600)

    # ── Field extraction ──────────────────────────────────────────────────────
    name         = request.POST.get('product_name', '').strip()
    price_raw    = request.POST.get('product_price', '').strip()
    description  = request.POST.get('description', '').strip()
    location     = request.POST.get('location', page.location or 'Kishi, Oyo State').strip()
    category     = request.POST.get('category', 'others').strip()
    condition    = request.POST.get('product_condition', 'New').strip()
    availability = request.POST.get('availability', 'Single Item').strip()
    whatsapp     = request.POST.get('whatsapp_number', page.whatsapp or '').strip()
    instagram    = request.POST.get('instagram_handle', '').strip()
    twitter      = request.POST.get('twitter_handle', '').strip()

    # ── Allowlists ────────────────────────────────────────────────────────────
    _VALID_CATEGORIES   = Market.VALID_CATEGORIES
    _VALID_CONDITIONS   = {'New', 'Used', 'Used-Fair'}
    _VALID_AVAILABILITY = {'Single Item', 'In Stock'}
    if category     not in _VALID_CATEGORIES:   category     = 'others'
    if condition    not in _VALID_CONDITIONS:   condition    = 'New'
    if availability not in _VALID_AVAILABILITY: availability = 'Single Item'

    # ── Validation ────────────────────────────────────────────────────────────
    errors = {}
    if not name:
        errors['product_name'] = 'Product name is required.'
    if not price_raw:
        errors['product_price'] = 'Price is required.'
    else:
        try:
            price_val = int(float(price_raw))
            if price_val < 0:
                errors['product_price'] = 'Price cannot be negative.'
        except (ValueError, TypeError):
            errors['product_price'] = 'Enter a valid price.'
    if not description:
        errors['description'] = 'Description is required.'
    if not whatsapp:
        errors['whatsapp_number'] = 'WhatsApp number is required.'
    if not request.FILES.getlist('images'):
        errors['images'] = 'At least one image is required.'
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    price_val = int(float(price_raw))

    # ── Create Market listing tagged to this page ─────────────────────────────
    from social.models import sanitize_text as _sanitize
    try:
        product = Market.objects.create(
            product_owner=request.user,
            product_name=_sanitize(name, 'product_name'),
            product_price=price_val,
            product_location=_sanitize(location),
            product_description=_sanitize(description, 'product_description'),
            product_availability=availability,
            product_category=category,
            product_condition=condition,
            whatsapp_number=whatsapp,
            instagram_handle=instagram,
            twitter_handle=twitter,
            business_page=page,
        )
        for img_file in request.FILES.getlist('images')[:5]:
            MarketImage.objects.create(product=product, product_image=img_file)

        # ── Notify every follower of this page about the new product ───────────
        try:
            follower_ids = list(
                page.followers.exclude(pk=request.user.pk).values_list('pk', flat=True)
            )
            BusinessNotification.objects.bulk_create([
                BusinessNotification(
                    notif_type=BusinessNotification.NEW_PRODUCT,
                    business_page=page,
                    actor=request.user,
                    to_user_id=follower_id,
                    product=product,
                )
                for follower_id in follower_ids
            ])
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to notify followers of new product for page %s', page.slug
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('business_product_upload failed for user %s', request.user.id)
        return JsonResponse({'success': False, 'errors': {'__all__': 'Something went wrong. Please try again.'}}, status=500)

    first_img = product.images.first()
    img_url   = first_img.product_image.url if first_img else 'https://placehold.co/400x400?text=No+Image'

    return JsonResponse({
        'success':    True,
        'product_id': str(product.product_id),
        'name':       product.product_name,
        'price':      product.product_price,
        'image_url':  img_url,
        'detail_url': f'/product/{product.product_id}/',
        'message':    'Listing uploaded successfully! 🔥',
    })


@login_required(login_url='/')
@require_POST
def business_job_upload(request, slug):
    """
    Owner posts a new JobVacancy tagged to their business page — the
    'post a job vacancy from your Page' flow, mirroring Facebook Jobs.
    Uses the existing JobVacancy model via its business_page FK.
    """
    from social.models import BusinessPage

    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user, is_active=True)

    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before posting jobs. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'errors': {'__all__': msg}}, status=403)

    # ── Rate limit: max 10 job posts per hour, per user ────────────────────────
    _rl_key  = f'job_post:{request.user.id}'
    _rl_hits = cache.get(_rl_key, 0)
    if _rl_hits >= 10:
        return JsonResponse({'success': False, 'errors': {'__all__': 'Too many jobs posted. Please wait.'}}, status=429)
    cache.set(_rl_key, _rl_hits + 1, timeout=3600)

    # ── Field extraction ────────────────────────────────────────────────────────
    title           = html_escape(request.POST.get('title', '').strip())
    category        = request.POST.get('category', '').strip()
    work_mode       = request.POST.get('work_mode', '').strip() or JobVacancy.WORK_ONSITE
    # Posted from a business page, so it defaults to "Company / School" —
    # still overridable (e.g. a school page posting on behalf of government).
    advertiser_type = request.POST.get('advertiser_type', '').strip() or JobVacancy.ADV_COMPANY_SCHOOL
    company         = html_escape(request.POST.get('company', page.name).strip() or page.name)
    location        = html_escape(request.POST.get('location', page.location or '').strip())
    description     = html_escape(request.POST.get('description', '').strip())
    requirements    = html_escape(request.POST.get('requirements', '').strip())
    contact_info    = html_escape(request.POST.get('contact_info', page.whatsapp or '').strip())
    salary_range    = html_escape(request.POST.get('salary_range', '').strip())
    cover_image     = request.FILES.get('cover_image')

    apply_link, link_error = _clean_apply_link(request.POST.get('apply_link', ''))

    # ── Validation ───────────────────────────────────────────────────────────────
    errors = {}
    if not title:
        errors['title'] = 'Job title is required.'
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        errors['category'] = 'Please choose a valid category.'
    if work_mode not in dict(JobVacancy.WORK_MODE_CHOICES):
        errors['work_mode'] = 'Please choose a valid work mode.'
    if advertiser_type not in dict(JobVacancy.ADVERTISER_CHOICES):
        errors['advertiser_type'] = 'Please choose a valid advertiser type.'
    if not description:
        errors['description'] = 'Description is required.'
    if link_error:
        errors['apply_link'] = link_error
    if cover_image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if cover_image.content_type not in allowed_types:
            errors['cover_image'] = 'Only JPEG, PNG, WebP or GIF images are allowed.'
        elif cover_image.size > 10 * 1024 * 1024:
            errors['cover_image'] = 'Image must be under 10 MB.'
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    try:
        job = JobVacancy.objects.create(
            posted_by       = request.user,
            business_page   = page,
            title           = title,
            category        = category,
            work_mode       = work_mode,
            advertiser_type = advertiser_type,
            company         = company,
            location        = location,
            description     = description,
            requirements    = requirements,
            contact_info    = contact_info,
            apply_link      = apply_link,
            salary_range    = salary_range,
            cover_image     = cover_image if cover_image else None,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception('business_job_upload failed for user %s', request.user.id)
        return JsonResponse({'success': False, 'errors': {'__all__': 'Something went wrong. Please try again.'}}, status=500)

    return JsonResponse({
        'success':    True,
        'job_id':     str(job.id),
        'title':      job.title,
        'category':   job.category,
        'work_mode':  job.work_mode,
        'cover_url':  job.cover_image.url if job.cover_image else '',
        'detail_url': f"/jobs/#khj-card-{job.id}",
        'message':    'Job vacancy posted successfully! 💼',
    })


# ─────────────────────────────────────────────────────────────────────────────
# Optional professional-page sections — Services / Portfolio & Projects /
# Achievements. Simple owner-only create + delete, mirroring the pattern
# used by business_post_create / business_post_delete above.
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_POST
def business_service_create(request, slug):
    """Owner adds a Service to their professional page."""
    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user, is_active=True)

    title      = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    price_text = request.POST.get('price_text', '').strip()
    image      = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please give the service a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)
    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        service = BusinessService.objects.create(
            business_page=page, title=title, description=description,
            price_text=price_text, image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'service': {
            'service_id':  str(service.service_id),
            'title':       service.title,
            'description': service.description,
            'price_text':  service.price_text,
            'image_url':   service.get_image_url,
        },
        'service_count': page.service_count,
        'message': 'Service added! 🛠️',
    })


@login_required(login_url='/')
@require_POST
def business_service_delete(request, service_id):
    service = get_object_or_404(BusinessService, service_id=service_id, business_page__owner=request.user)
    service.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def business_portfolio_create(request, slug):
    """Owner adds a Portfolio piece or a Project to their professional page."""
    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user, is_active=True)

    kind        = request.POST.get('kind', BusinessPortfolioItem.KIND_PORTFOLIO).strip()
    title       = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    link_url    = request.POST.get('link_url', '').strip()
    is_ongoing  = request.POST.get('is_ongoing') in ('1', 'true', 'on')
    image       = request.FILES.get('image')
    # Additional gallery photos — a completed project/portfolio piece can
    # showcase several images beyond the single cover `image`.
    extra_images = request.FILES.getlist('images')[:9]

    if kind not in dict(BusinessPortfolioItem.KIND_CHOICES):
        kind = BusinessPortfolioItem.KIND_PORTFOLIO
    if not title:
        return JsonResponse({'success': False, 'error': 'Please give it a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)

    allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    for _img in ([image] if image else []) + extra_images:
        if _img.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if _img.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Each image must be under 10 MB.'}, status=400)

    try:
        item = BusinessPortfolioItem.objects.create(
            business_page=page, kind=kind, title=title, description=description,
            link_url=link_url, is_ongoing=is_ongoing if kind == BusinessPortfolioItem.KIND_PROJECT else False,
            image=image if image else None,
        )
        for _order, _img in enumerate(extra_images):
            BusinessPortfolioImage.objects.create(item=item, image=_img, order=_order)
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'item': {
            'item_id':      str(item.item_id),
            'kind':         item.kind,
            'title':        item.title,
            'description':  item.description,
            'link_url':     item.link_url,
            'is_ongoing':   item.is_ongoing,
            'image_url':    item.get_image_url,
            'gallery':      item.gallery_urls,
        },
        'portfolio_count': page.portfolio_count,
        'project_count':   page.project_count,
        'message': 'Added to your page! ✨',
    })


@login_required(login_url='/')
@require_POST
def business_portfolio_delete(request, item_id):
    item = get_object_or_404(BusinessPortfolioItem, item_id=item_id, business_page__owner=request.user)
    item.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def business_achievement_create(request, slug):
    """Owner adds an Achievement (award, certification, milestone) to their page."""
    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user, is_active=True)

    title         = request.POST.get('title', '').strip()
    issuer        = request.POST.get('issuer', '').strip()
    description   = request.POST.get('description', '').strip()
    date_raw      = request.POST.get('date_achieved', '').strip()
    image         = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please give the achievement a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)

    date_achieved = None
    if date_raw:
        try:
            date_achieved = datetime.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid date.'}, status=400)

    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        achievement = BusinessAchievement.objects.create(
            business_page=page, title=title, issuer=issuer, description=description,
            date_achieved=date_achieved, image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'achievement': {
            'achievement_id': str(achievement.achievement_id),
            'title':          achievement.title,
            'issuer':         achievement.issuer,
            'description':    achievement.description,
            'date_achieved':  achievement.date_achieved.isoformat() if achievement.date_achieved else '',
            'image_url':      achievement.get_image_url,
        },
        'achievement_count': page.achievement_count,
        'message': 'Achievement added! 🏆',
    })


@login_required(login_url='/')
@require_POST
def business_achievement_delete(request, achievement_id):
    achievement = get_object_or_404(BusinessAchievement, achievement_id=achievement_id, business_page__owner=request.user)
    achievement.delete()
    return JsonResponse({'success': True})


# ─────────────────────────────────────────────────────────────────────────────
# Business Page — Reviews & Ratings. Customers rate/review the page itself
# (separate from ProductReview, which is scoped to a single Market listing);
# the page owner can post one public reply per review.
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_POST
def business_review_create(request, slug):
    """Logged-in customer rates/reviews a business page. One review per
    (page, user) — posting again edits the existing review in place."""
    page = get_object_or_404(BusinessPage, slug=slug, is_active=True)

    if page.owner == request.user:
        return JsonResponse({'success': False, 'error': 'You cannot review your own business page.'}, status=400)

    rating_raw = request.POST.get('rating', '').strip()
    comment    = request.POST.get('comment', '').strip()

    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Please choose a star rating.'}, status=400)
    if rating not in dict(BusinessReview.RATING_CHOICES):
        return JsonResponse({'success': False, 'error': 'Rating must be between 1 and 5.'}, status=400)
    if len(comment) > 2000:
        return JsonResponse({'success': False, 'error': 'Review must be 2000 characters or fewer.'}, status=400)

    try:
        review, created = BusinessReview.objects.get_or_create(
            business_page=page, user=request.user,
            defaults={'rating': rating, 'comment': comment},
        )
        if not created:
            review.rating    = rating
            review.comment   = comment
            review.is_edited = True
            review.save()
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'review': {
            'review_id':   str(review.review_id),
            'rating':      review.rating,
            'comment':     review.comment,
            'is_edited':   review.is_edited,
            'reviewer_name': request.user.profile.full_name or request.user.username,
            'reviewer_pic':  request.user.profile.picture.url if request.user.profile.picture else '',
        },
        'average_rating': page.overall_average_rating,
        'review_count':   page.overall_review_count,
        'message': 'Thanks for your review! ⭐',
    })


@login_required(login_url='/')
@require_POST
def business_review_reply(request, review_id):
    """Page owner posts (or edits) a single public reply to a review."""
    review = get_object_or_404(BusinessReview, review_id=review_id, business_page__owner=request.user)
    reply = request.POST.get('reply', '').strip()
    if not reply:
        return JsonResponse({'success': False, 'error': 'Write a reply first.'}, status=400)
    if len(reply) > 2000:
        return JsonResponse({'success': False, 'error': 'Reply must be 2000 characters or fewer.'}, status=400)

    review.owner_reply = reply
    review.owner_reply_at = timezone.now()
    try:
        review.save()
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'owner_reply': review.owner_reply,
        'owner_reply_at': review.owner_reply_at.isoformat(),
        'message': 'Reply posted.',
    })


@login_required(login_url='/')
@require_POST
def business_review_delete(request, review_id):
    """A reviewer can remove their own review; the page owner can remove any
    review left on their page."""
    review = get_object_or_404(BusinessReview, review_id=review_id)
    if review.user != request.user and review.business_page.owner != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)
    page = review.business_page
    review.delete()
    return JsonResponse({
        'success': True,
        'average_rating': page.overall_average_rating,
        'review_count':   page.overall_review_count,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Profile — professional sections (Services, Portfolio, Projects,
# Achievements, Posts, Products) owned directly by the user's Profile.
# Mirrors the business_* equivalents above, but targets request.user.profile
# instead of a BusinessPage — this is what lets any user manage professional
# content straight from their own profile, with no BusinessPage required.
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_POST
def profile_service_create(request):
    """Owner adds a Service directly to their own profile."""
    profile = request.user.profile
    if not profile.show_services:
        return JsonResponse({'success': False, 'error': 'Turn on the Services section first (Manage sections).'}, status=403)

    title       = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    price_text  = request.POST.get('price_text', '').strip()
    image       = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please give the service a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)
    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        service = ProfileService.objects.create(
            profile=profile, title=title, description=description,
            price_text=price_text, image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'service': {
            'service_id':  str(service.service_id),
            'title':       service.title,
            'description': service.description,
            'price_text':  service.price_text,
            'image_url':   service.get_image_url,
        },
        'service_count': profile.service_count,
        'message': 'Service added! 🛠️',
    })


@login_required(login_url='/')
@require_POST
def profile_service_delete(request, service_id):
    service = get_object_or_404(ProfileService, service_id=service_id, profile__user=request.user)
    service.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_portfolio_create(request):
    """Owner adds a Portfolio piece or a Project directly to their own profile."""
    profile = request.user.profile

    kind        = request.POST.get('kind', ProfilePortfolioItem.KIND_PORTFOLIO).strip()
    if kind not in dict(ProfilePortfolioItem.KIND_CHOICES):
        kind = ProfilePortfolioItem.KIND_PORTFOLIO
    section_needed = 'portfolio' if kind == ProfilePortfolioItem.KIND_PORTFOLIO else 'projects'
    if section_needed not in (profile.enabled_sections or []):
        return JsonResponse({'success': False, 'error': 'Turn on that section first (Manage sections).'}, status=403)

    title       = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    link_url    = request.POST.get('link_url', '').strip()
    is_ongoing  = request.POST.get('is_ongoing') in ('1', 'true', 'on')
    image       = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please give it a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)
    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        item = ProfilePortfolioItem.objects.create(
            profile=profile, kind=kind, title=title, description=description,
            link_url=link_url, is_ongoing=is_ongoing if kind == ProfilePortfolioItem.KIND_PROJECT else False,
            image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'item': {
            'item_id':      str(item.item_id),
            'kind':         item.kind,
            'title':        item.title,
            'description':  item.description,
            'link_url':     item.link_url,
            'is_ongoing':   item.is_ongoing,
            'image_url':    item.get_image_url,
        },
        'portfolio_count': profile.portfolio_count,
        'project_count':   profile.project_count,
        'message': 'Added to your profile! ✨',
    })


@login_required(login_url='/')
@require_POST
def profile_portfolio_delete(request, item_id):
    item = get_object_or_404(ProfilePortfolioItem, item_id=item_id, profile__user=request.user)
    item.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_experience_create(request):
    """Owner adds a work-experience entry (role @ company) to their profile,
    LinkedIn-style, with an optional company logo image."""
    profile = request.user.profile
    if not profile.show_experience:
        return JsonResponse({'success': False, 'error': 'Turn on the Experience section first (Manage sections).'}, status=403)

    title           = request.POST.get('title', '').strip()
    company_name    = request.POST.get('company_name', '').strip()
    employment_type = request.POST.get('employment_type', '').strip()
    location        = request.POST.get('location', '').strip()
    description     = request.POST.get('description', '').strip()
    is_current      = request.POST.get('is_current') in ('1', 'true', 'on')
    start_raw       = request.POST.get('start_date', '').strip()
    end_raw         = request.POST.get('end_date', '').strip()
    image           = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please add a title / role.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)
    if not company_name:
        return JsonResponse({'success': False, 'error': 'Please add a company name.'}, status=400)
    if employment_type and employment_type not in dict(ProfileExperience.EMPLOYMENT_TYPE_CHOICES):
        employment_type = ''

    start_date = None
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid start date.'}, status=400)

    end_date = None
    if not is_current and end_raw:
        try:
            end_date = datetime.strptime(end_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid end date.'}, status=400)

    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        exp = ProfileExperience.objects.create(
            profile=profile, title=title, company_name=company_name,
            employment_type=employment_type, location=location, description=description,
            start_date=start_date, end_date=end_date, is_current=is_current,
            image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'experience': {
            'experience_id':   str(exp.experience_id),
            'title':           exp.title,
            'company_name':    exp.company_name,
            'employment_type': exp.get_employment_type_display() if exp.employment_type else '',
            'location':        exp.location,
            'description':     exp.description,
            'duration_label':  exp.duration_label,
            'image_url':       exp.get_image_url,
        },
        'experience_count': profile.experience_count,
        'message': 'Experience added! 💼',
    })


@login_required(login_url='/')
@require_POST
def profile_experience_delete(request, experience_id):
    exp = get_object_or_404(ProfileExperience, experience_id=experience_id, profile__user=request.user)
    exp.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_education_create(request):
    """Owner adds an education entry (school / degree) to their profile,
    LinkedIn-style, with an optional institution logo image."""
    profile = request.user.profile
    if not profile.show_education:
        return JsonResponse({'success': False, 'error': 'Turn on the Education section first (Manage sections).'}, status=403)

    school_name    = request.POST.get('school_name', '').strip()
    degree         = request.POST.get('degree', '').strip()
    field_of_study = request.POST.get('field_of_study', '').strip()
    grade          = request.POST.get('grade', '').strip()
    description    = request.POST.get('description', '').strip()
    is_current     = request.POST.get('is_current') in ('1', 'true', 'on')
    start_raw      = request.POST.get('start_date', '').strip()
    end_raw        = request.POST.get('end_date', '').strip()
    image          = request.FILES.get('image')

    if not school_name:
        return JsonResponse({'success': False, 'error': 'Please add a school / institution name.'}, status=400)
    if len(school_name) > 150:
        return JsonResponse({'success': False, 'error': 'School name must be 150 characters or fewer.'}, status=400)

    start_date = None
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid start date.'}, status=400)

    end_date = None
    if not is_current and end_raw:
        try:
            end_date = datetime.strptime(end_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid end date.'}, status=400)

    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        edu = ProfileEducation.objects.create(
            profile=profile, school_name=school_name, degree=degree,
            field_of_study=field_of_study, grade=grade, description=description,
            start_date=start_date, end_date=end_date, is_current=is_current,
            image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'education': {
            'education_id':   str(edu.education_id),
            'school_name':    edu.school_name,
            'degree':         edu.degree,
            'field_of_study': edu.field_of_study,
            'grade':          edu.grade,
            'description':    edu.description,
            'duration_label': edu.duration_label,
            'image_url':      edu.get_image_url,
        },
        'education_count': profile.education_count,
        'message': 'Education added! 🎓',
    })


@login_required(login_url='/')
@require_POST
def profile_education_delete(request, education_id):
    edu = get_object_or_404(ProfileEducation, education_id=education_id, profile__user=request.user)
    edu.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_achievement_create(request):
    """Owner adds an Achievement (award, certification, milestone) to their profile."""
    profile = request.user.profile
    if not profile.show_achievements:
        return JsonResponse({'success': False, 'error': 'Turn on the Achievements section first (Manage sections).'}, status=403)

    title         = request.POST.get('title', '').strip()
    issuer        = request.POST.get('issuer', '').strip()
    description   = request.POST.get('description', '').strip()
    date_raw      = request.POST.get('date_achieved', '').strip()
    image         = request.FILES.get('image')

    if not title:
        return JsonResponse({'success': False, 'error': 'Please give the achievement a title.'}, status=400)
    if len(title) > 150:
        return JsonResponse({'success': False, 'error': 'Title must be 150 characters or fewer.'}, status=400)

    date_achieved = None
    if date_raw:
        try:
            date_achieved = datetime.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Enter a valid date.'}, status=400)

    if image:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if image.content_type not in allowed_types:
            return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
        if image.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Image must be under 10 MB.'}, status=400)

    try:
        achievement = ProfileAchievement.objects.create(
            profile=profile, title=title, issuer=issuer, description=description,
            date_achieved=date_achieved, image=image if image else None,
        )
    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    return JsonResponse({
        'success': True,
        'achievement': {
            'achievement_id': str(achievement.achievement_id),
            'title':          achievement.title,
            'issuer':         achievement.issuer,
            'description':    achievement.description,
            'date_achieved':  achievement.date_achieved.isoformat() if achievement.date_achieved else '',
            'image_url':      achievement.get_image_url,
        },
        'achievement_count': profile.achievement_count,
        'message': 'Achievement added! 🏆',
    })


@login_required(login_url='/')
@require_POST
def profile_achievement_delete(request, achievement_id):
    achievement = get_object_or_404(ProfileAchievement, achievement_id=achievement_id, profile__user=request.user)
    achievement.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_post_create(request):
    """AJAX — owner posts an image / video / text / poll update straight to their profile."""
    profile = request.user.profile
    if not profile.is_professional:
        return JsonResponse({'success': False, 'error': 'Set your profession / member type first.'}, status=403)

    post_type = request.POST.get('post_type', '').strip()
    caption   = request.POST.get('caption', '').strip()
    post_category = request.POST.get('post_category', ProfilePost.CATEGORY_UPDATE).strip()
    if post_category not in dict(ProfilePost.POST_CATEGORY_CHOICES):
        post_category = ProfilePost.CATEGORY_UPDATE

    if post_type not in dict(ProfilePost.POST_TYPE_CHOICES):
        return JsonResponse({'success': False, 'error': 'Please choose a valid post type.'}, status=400)

    if post_type == ProfilePost.TYPE_TEXT and not caption:
        return JsonResponse({'success': False, 'error': 'Please write something to post.'}, status=400)

    images, video, duration = [], None, None
    option_texts, question, allow_multiple, closes_at = [], '', False, None

    if post_type == ProfilePost.TYPE_IMAGE:
        images = request.FILES.getlist('images')
        if not images:
            return JsonResponse({'success': False, 'error': 'Please attach at least one image.'}, status=400)
        if len(images) > 10:
            return JsonResponse({'success': False, 'error': 'You can attach up to 10 images per post.'}, status=400)
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        for img in images:
            if img.content_type not in allowed_types:
                return JsonResponse({'success': False, 'error': 'Only JPEG, PNG, WebP or GIF images are allowed.'}, status=400)
            if img.size > 10 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'Each image must be under 10 MB.'}, status=400)

    elif post_type == ProfilePost.TYPE_VIDEO:
        video = request.FILES.get('video')
        if not video:
            return JsonResponse({'success': False, 'error': 'Please attach a video.'}, status=400)
        allowed_video_types = {'video/mp4', 'video/quicktime', 'video/webm', 'video/x-msvideo'}
        if video.content_type not in allowed_video_types:
            return JsonResponse({'success': False, 'error': 'Only MP4, MOV, WebM or AVI videos are allowed.'}, status=400)
        if video.size > 100 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Video must be under 100 MB.'}, status=400)
        raw_duration = request.POST.get('video_duration_seconds', '').strip()
        if raw_duration:
            try:
                duration = int(float(raw_duration))
            except ValueError:
                duration = None
        if duration is not None and not (ProfilePost.MIN_VIDEO_SECONDS <= duration <= ProfilePost.MAX_VIDEO_SECONDS):
            return JsonResponse({
                'success': False,
                'error': f'Videos should be {ProfilePost.MIN_VIDEO_SECONDS}\u201390 seconds long.'
            }, status=400)

    elif post_type == ProfilePost.TYPE_POLL:
        question = request.POST.get('poll_question', '').strip()
        option_texts = [o.strip() for o in request.POST.getlist('poll_options') if o.strip()]
        if not question:
            return JsonResponse({'success': False, 'error': 'Please give your poll a question.'}, status=400)
        if len(option_texts) < 2:
            return JsonResponse({'success': False, 'error': 'Polls need at least 2 options.'}, status=400)
        if len(option_texts) > 6:
            return JsonResponse({'success': False, 'error': 'Polls can have up to 6 options.'}, status=400)
        allow_multiple = request.POST.get('allow_multiple') in ('1', 'true', 'on')
        raw_closes = request.POST.get('closes_at', '').strip()
        if raw_closes:
            parsed = django_parse_datetime(raw_closes)
            if parsed:
                closes_at = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

    try:
        post = ProfilePost(profile=profile, post_type=post_type, post_category=post_category, caption=caption)

        if post_type == ProfilePost.TYPE_VIDEO:
            post.video = video
            if duration is not None:
                post.video_duration_seconds = duration

        post.save()

        if post_type == ProfilePost.TYPE_IMAGE:
            for idx, img in enumerate(images):
                ProfilePostImage.objects.create(post=post, image=img, order=idx)

        elif post_type == ProfilePost.TYPE_POLL:
            poll = ProfilePostPoll.objects.create(
                post=post, question=question, allow_multiple=allow_multiple, closes_at=closes_at,
            )
            for idx, text in enumerate(option_texts):
                ProfilePostPollOption.objects.create(poll=poll, text=text, order=idx)

    except _ModelValidationError as e:
        return JsonResponse({'success': False, 'error': '; '.join(_flatten_validation_error(e))}, status=400)

    post = (
        ProfilePost.objects.filter(pk=post.pk)
        .prefetch_related('images', 'poll__options')
        .first()
    )
    return JsonResponse({
        'success': True,
        'post': _serialize_professional_post(post, viewer=request.user),
        'post_count': profile.post_count,
    })


@login_required(login_url='/')
@require_POST
def profile_post_delete(request, post_id):
    """AJAX — delete a ProfilePost (profile owner only)."""
    post = get_object_or_404(ProfilePost, pk=post_id, profile__user=request.user)

    if not settings.USE_CLOUDINARY:
        for img in post.images.all():
            if img.image:
                img.image.delete(save=False)
        if post.video:
            post.video.delete(save=False)
    else:
        try:
            import cloudinary.uploader as _cu
            for img in post.images.all():
                if img.image:
                    _cu.destroy(str(img.image))
            if post.video:
                _cu.destroy(str(post.video), resource_type='video')
        except Exception:
            pass

    post.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
@require_POST
def profile_post_poll_vote(request, post_id):
    """AJAX — cast (or change) a vote on a ProfilePost poll."""
    post = get_object_or_404(ProfilePost.objects.select_related('poll'), pk=post_id)
    if post.post_type != ProfilePost.TYPE_POLL or not hasattr(post, 'poll'):
        return JsonResponse({'success': False, 'error': 'This post is not a poll.'}, status=400)

    poll = post.poll
    if poll.is_closed:
        return JsonResponse({'success': False, 'error': 'This poll is closed.'}, status=400)

    option_ids = request.POST.getlist('option_ids')
    if not option_ids:
        return JsonResponse({'success': False, 'error': 'Please select an option.'}, status=400)
    if not poll.allow_multiple and len(option_ids) > 1:
        return JsonResponse({'success': False, 'error': 'This poll only allows one choice.'}, status=400)

    options = list(poll.options.filter(option_id__in=option_ids))
    if len(options) != len(set(option_ids)):
        return JsonResponse({'success': False, 'error': 'Invalid option selected.'}, status=400)

    # Voting again replaces the viewer's previous choice(s) on this poll.
    ProfilePostPollVote.objects.filter(option__poll=poll, user=request.user).delete()
    for opt in options:
        ProfilePostPollVote.objects.create(option=opt, user=request.user)

    fresh_options = poll.options.all()
    total = sum(o.vote_count for o in fresh_options)
    return JsonResponse({
        'success': True,
        'poll': {
            'total_votes': total,
            'options': [
                {'option_id': str(o.option_id), 'vote_count': o.vote_count, 'pct': o.vote_pct(total)}
                for o in fresh_options
            ],
        },
    })


@login_required(login_url='/')
def profile_post_vibe(request, post_id):
    post = get_object_or_404(ProfilePost, pk=post_id)
    if request.method == 'GET':
        return _card_vibe_get(request, post, ProfilePostVibe, 'post')

    response = _card_vibe_toggle(request, post, ProfilePostVibe, 'post')

    if response.status_code == 200 and post.profile.user != request.user:
        try:
            data = json.loads(response.content)
            user_vibe = data.get('user_vibe')
            if user_vibe:
                # One reaction notification per (post, actor) — re-vibing
                # (or switching vibe types) refreshes it instead of spamming
                # a new row for every tap.
                notif, created = ProfilePostNotification.objects.get_or_create(
                    notif_type=ProfilePostNotification.NEW_VIBE,
                    post=post,
                    actor=request.user,
                    defaults={'to_user': post.profile.user, 'vibe_type': user_vibe},
                )
                if not created:
                    notif.vibe_type  = user_vibe
                    notif.is_read    = False
                    notif.created_at = timezone.now()
                    notif.save(update_fields=['vibe_type', 'is_read', 'created_at'])
            else:
                # Un-reacting removes the notification entirely.
                ProfilePostNotification.objects.filter(
                    notif_type=ProfilePostNotification.NEW_VIBE,
                    post=post,
                    actor=request.user,
                ).delete()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to sync vibe notification for post %s', post.pk
            )

    return response


@login_required(login_url='/')
def profile_post_comments(request, post_id):
    post = get_object_or_404(ProfilePost, pk=post_id)
    if request.method == 'POST':
        response = _card_comments_post(request, post, ProfilePostComment, 'post')
        if response.status_code == 200 and post.profile.user != request.user:
            try:
                comment = ProfilePostComment.objects.filter(post=post, author=request.user).latest('created_at')
                ProfilePostNotification.objects.create(
                    notif_type=ProfilePostNotification.NEW_COMMENT,
                    post=post,
                    actor=request.user,
                    to_user=post.profile.user,
                    comment=comment,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Failed to create comment notification for post %s', post.pk
                )
        return response
    return _card_comments_get(request, post, ProfilePostComment, 'post')


@login_required(login_url='/')
@require_POST
def profile_product_upload(request):
    """
    Owner posts a new Market listing straight from their profile — no
    BusinessPage required. Uses the same Market + MarketImage models as
    business_product_upload, just without a business_page attached.
    """
    profile = request.user.profile
    if not profile.sells_products:
        return JsonResponse({
            'success': False,
            'errors': {'__all__': 'Products are turned off for your profile. Enable "Sell Products" in Manage sections to add listings.'},
        }, status=403)

    _rl_key  = f'ad_post:{request.user.id}'
    _rl_hits = cache.get(_rl_key, 0)
    if _rl_hits >= 10:
        return JsonResponse({'success': False, 'errors': {'__all__': 'Too many listings posted. Please wait.'}}, status=429)

    name         = request.POST.get('product_name', '').strip()
    price_raw    = request.POST.get('product_price', '').strip()
    description  = request.POST.get('description', '').strip()
    location     = request.POST.get('location', profile.location or 'Kishi, Oyo State').strip()
    category     = request.POST.get('category', 'others').strip()
    condition    = request.POST.get('product_condition', 'New').strip()
    availability = request.POST.get('availability', 'Single Item').strip()
    whatsapp     = request.POST.get('whatsapp_number', profile.phone or '').strip()
    instagram    = request.POST.get('instagram_handle', '').strip()
    twitter      = request.POST.get('twitter_handle', '').strip()

    _VALID_CATEGORIES   = Market.VALID_CATEGORIES
    _VALID_CONDITIONS   = {'New', 'Used', 'Used-Fair'}
    _VALID_AVAILABILITY = {'Single Item', 'In Stock'}
    if category     not in _VALID_CATEGORIES:   category     = 'others'
    if condition    not in _VALID_CONDITIONS:   condition    = 'New'
    if availability not in _VALID_AVAILABILITY: availability = 'Single Item'

    errors = {}
    if not name:
        errors['product_name'] = 'Product name is required.'
    if not price_raw:
        errors['product_price'] = 'Price is required.'
    else:
        try:
            price_val = int(float(price_raw))
            if price_val < 0:
                errors['product_price'] = 'Price cannot be negative.'
        except (ValueError, TypeError):
            errors['product_price'] = 'Enter a valid price.'
    if not description:
        errors['description'] = 'Description is required.'
    if not whatsapp:
        errors['whatsapp_number'] = 'WhatsApp number is required.'
    if not request.FILES.getlist('images'):
        errors['images'] = 'At least one image is required.'
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    cache.set(_rl_key, _rl_hits + 1, timeout=3600)

    price_val = int(float(price_raw))

    from social.models import sanitize_text as _sanitize
    try:
        product = Market.objects.create(
            product_owner=request.user,
            product_name=_sanitize(name, 'product_name'),
            product_price=price_val,
            product_location=_sanitize(location),
            product_description=_sanitize(description, 'product_description'),
            product_availability=availability,
            product_category=category,
            product_condition=condition,
            whatsapp_number=whatsapp,
            instagram_handle=instagram,
            twitter_handle=twitter,
            business_page=None,
        )
        for img_file in request.FILES.getlist('images')[:5]:
            MarketImage.objects.create(product=product, product_image=img_file)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('profile_product_upload failed for user %s', request.user.id)
        return JsonResponse({'success': False, 'errors': {'__all__': 'Something went wrong. Please try again.'}}, status=500)

    first_img = product.images.first()
    img_url   = first_img.product_image.url if first_img else 'https://placehold.co/400x400?text=No+Image'

    return JsonResponse({
        'success':    True,
        'product_id': str(product.product_id),
        'name':       product.product_name,
        'price':      product.product_price,
        'image_url':  img_url,
        'detail_url': f'/product/{product.product_id}/',
        'message':    'Listing uploaded successfully! 🔥',
    })


@login_required(login_url='/')
@require_POST
def profile_sections_update(request):
    """AJAX — owner turns professional sections (Services, Portfolio,
    Projects, Achievements, Jobs) and "sells products" on/off for their
    own profile, independent of the main profile-edit form."""
    profile = request.user.profile
    profile.enabled_sections = [
        s for s in request.POST.getlist('sections')
        if s in Profile.VALID_PROFESSIONAL_SECTIONS
    ]
    profile.sells_products = request.POST.get('sells_products') in ('1', 'true', 'on')
    profile.save()
    return JsonResponse({
        'success': True,
        'enabled_sections': profile.enabled_sections,
        'sells_products': profile.sells_products,
    })
