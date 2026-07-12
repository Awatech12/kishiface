import os
import re
import uuid as uuid_module
import socket

from html import escape as html_escape, unescape as html_unescape
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from .models import FollowNotification
from django.template.loader import render_to_string
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, UserReport, BlockedUser, ChannelUserLastSeen, Message, ChannelMessage, Channel, Market, MarketImage, SearchHistory, SocialEvent, JobVacancy, JobVibe, JobComment, EventVibe, EventComment, BusinessPage, Wishlist
from django.db.models import Q
from django.db.models import Count, Max, Min
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time, json, logging, re, requests, ipaddress
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote as url_quote
from django.http import JsonResponse, Http404
from django.conf import settings
from django.utils import timezone
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
            return redirect(_safe_next(request, '/market'))
        else:
            messages.error(request, 'Invalid username or password. Please try again.')
            return redirect('/')

    # ── GET — pull real listings for the marketing marquee ─────────────────────
    _marquee_products = list(
        Market.objects
        .order_by('-is_promoted', '-posted_on')[:24]
    )

    if _marquee_products:
        marquee_flat = _marquee_products[:12]  # for the mobile horizontal strip

        # Split into (up to) 3 columns for the desktop scrolling marquee.
        _col_size = max(1, -(-len(_marquee_products) // 3))  # ceil division
        marquee_columns = [
            _marquee_products[i:i + _col_size]
            for i in range(0, len(_marquee_products), _col_size)
        ][:3]
        # Duplicate each column's items so the CSS scroll loop is seamless.
        marquee_columns = [col + col for col in marquee_columns if col]
    else:
        # Fresh install with no listings yet — fall back to category previews.
        _fallback_categories = [
            {'category_icon': Market.CATEGORY_ICONS[key], 'category_label': label}
            for key, label in Market.CATEGORY_CHOICES
        ]
        marquee_flat = _fallback_categories[:12]

        _col_size = max(1, -(-len(_fallback_categories) // 3))
        marquee_columns = [
            _fallback_categories[i:i + _col_size]
            for i in range(0, len(_fallback_categories), _col_size)
        ][:3]
        marquee_columns = [col + col for col in marquee_columns if col]

    stats = {
        'active_users':    _format_count(User.objects.filter(is_active=True).count()),
        'business_pages':  _format_count(BusinessPage.objects.count()),
        'listings':        _format_count(Market.objects.count()),
        'communities':     _format_count(Channel.objects.count()),
    }

    return render(request, 'index.html', {
        'marquee_columns':     marquee_columns,
        'marquee_flat':        marquee_flat,
        'stats':               stats,
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
# Feed page builder — market / job / event / suggestion cards only.
# Post fetching, scoring, and media pipelines have been removed because
# feed_posts_partial.html does not render post items.
# ─────────────────────────────────────────────────────────────────────────────

def _get_feed_page(user, following_ids, cursor_dt=None, page_size=None,
                   seen_suggestion_ids=None,
                   seen_market_ids=None, seen_job_ids=None, seen_event_ids=None,
                   seen_business_ids=None,
                   market_category=None,
                   **_kwargs):
    """
    Build one page of the feed containing market ads, job cards, event cards,
    and user-suggestion cards.  Post items are not included.

    market_category: optional category key (Market.CATEGORY_CHOICES) to
    restrict market ads to a single category. 'all' or None means no filter.

    Returns (feed_items list, next_cursor None).
    next_cursor is always None because pagination is item-count-driven by the
    injected cards, not post timestamps.
    """
    if page_size is None:
        page_size = FEED_PAGE_SIZE

    following_ids_set = set(following_ids)
    next_cursor = None

    # ── User suggestions ──────────────────────────────────────────────────────
    _seen_sugg_ids = set(int(i) for i in (seen_suggestion_ids or []) if str(i).isdigit())
    user_pool_count = (
        User.objects
        .exclude(id__in=following_ids)
        .exclude(id=user.id)
        .exclude(id__in=_seen_sugg_ids)
        .count()
    )
    suggestion_users = []
    if user_pool_count > 0:
        su_offset = random.randint(0, max(0, user_pool_count - 5))
        suggestion_users = list(
            User.objects
            .exclude(id__in=following_ids)
            .exclude(id=user.id)
            .exclude(id__in=_seen_sugg_ids)
            .select_related('profile')
            .order_by('id')[su_offset: su_offset + 5]
        )

    # ── Business page suggestions ───────────────────────────────────────────────
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
    if business_pool_count > 0:
        sb_offset = random.randint(0, max(0, business_pool_count - 3))
        suggestion_businesses = list(
            business_pool_qs
            .select_related('owner')
            .order_by('page_id')[sb_offset: sb_offset + 3]
        )

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
    if market_category and market_category != 'all' and market_category in Market.VALID_CATEGORIES:
        _market_qs = _market_qs.filter(product_category=market_category)
    _market_count = _market_qs.count()
    _market_fetch_n = page_size if (market_category and market_category != 'all') else 8
    if _market_count > 0:
        _market_offset = random.randint(0, max(0, _market_count - _market_fetch_n))
        _market_pool = list(
            _market_qs
            .select_related('product_owner', 'product_owner__profile')
            .prefetch_related('images')
            [_market_offset: _market_offset + _market_fetch_n]
        )
        random.shuffle(_market_pool)
    _market_injected = 0
    _MAX_MARKET_PER_PAGE = 6
    # ── Job vacancy pool ──────────────────────────────────────────────────────
    import datetime as _dt_feed
    _seen_job_ids = set(str(i) for i in (seen_job_ids or []))
    _job_pool = []
    _job_base_qs = JobVacancy.objects.filter(is_open=True)
    if _seen_job_ids:
        _job_base_qs = _job_base_qs.exclude(id__in=_seen_job_ids)
    _job_count = _job_base_qs.count()
    if _job_count > 0:
        _job_offset = random.randint(0, max(0, _job_count - 4))
        _job_pool = list(
            _job_base_qs
            .select_related('posted_by', 'posted_by__profile')
            [_job_offset: _job_offset + 4]
        )
        random.shuffle(_job_pool)
    _job_injected = 0
    _MAX_JOB_PER_PAGE = 1

    # ── Social event pool ─────────────────────────────────────────────────────
    _today = _dt_feed.date.today()
    _seen_event_ids = set(str(i) for i in (seen_event_ids or []))
    _event_pool = []
    _event_base_qs = SocialEvent.objects.filter(date__gte=_today)
    if _seen_event_ids:
        _event_base_qs = _event_base_qs.exclude(id__in=_seen_event_ids)
    _event_count = _event_base_qs.count()
    if _event_count > 0:
        _event_offset = random.randint(0, max(0, _event_count - 4))
        _event_pool = list(
            _event_base_qs
            .select_related('created_by', 'created_by__profile')
            .order_by('date')
            [_event_offset: _event_offset + 4]
        )
    _event_injected = 0
    _MAX_EVENT_PER_PAGE = 1

    # ── Build feed_items ──────────────────────────────────────────────────────
    # Inject cards at fixed intervals across page_size virtual slots so the
    # partial always has content to render even with no posts.
    _is_market_filtered = bool(market_category and market_category != 'all')
    _max_suggestions_this_page = (1 if len(following_ids_set) < 20 else 0) if not _is_market_filtered else 0
    _suggestion_injected = 0
    _max_business_this_page = 1 if not _is_market_filtered else 0
    _business_injected = 0

    if _is_market_filtered:
        # Category filter is active — fill the page with market cards only,
        # ignoring jobs/events/suggestions so the grid is pure product results.
        _MAX_MARKET_PER_PAGE = page_size
        _job_pool, _event_pool = [], []

    feed_items = []
    for i in range(1, page_size + 1):
        # User suggestion at slot 2
        if (i % 4 == 2
                and suggestion_users
                and _suggestion_injected < _max_suggestions_this_page):
            feed_items.append({'type': 'user_suggestion', 'data': suggestion_users.pop(0)})
            _suggestion_injected += 1

        # Business page suggestion at slot 6 (every 8 slots), distinct from user suggestion slot
        if (i % 8 == 6
                and suggestion_businesses
                and _business_injected < _max_business_this_page):
            feed_items.append({'type': 'business_suggestion', 'data': suggestion_businesses.pop(0)})
            _business_injected += 1

        # Market ad — fills most slots (1,2,3,4,5,6 of every 10) normally,
        # or every slot when a category filter is active.
        _market_slot_match = True if _is_market_filtered else (i % 10 in (1, 2, 3, 4, 5, 6))
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

    return feed_items, next_cursor


# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def home(request):
    profile = Profile.objects.get(user=request.user)
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

    users = list(
        User.objects.exclude(id__in=following_ids)
               .exclude(id=request.user.id)
               .order_by('?')[:3]
    )

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
        'following_ids':              following_ids,
        'sidebar_following_count':    sidebar_following_count,
        'sidebar_follower_count':     sidebar_follower_count,
        'recent_dm_users':            recent_dm_users,
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
    market_category  = request.GET.get('market_category', 'all')

    seen_suggestion_ids = set(seen_users_raw.split(','))   if seen_users_raw   else set()
    seen_market_ids     = set(seen_markets_raw.split(',')) if seen_markets_raw else set()
    seen_job_ids        = set(seen_jobs_raw.split(','))    if seen_jobs_raw    else set()
    seen_event_ids      = set(seen_events_raw.split(','))  if seen_events_raw  else set()
    seen_business_ids   = set(seen_business_raw.split(',')) if seen_business_raw else set()

    feed, next_cursor = _get_feed_page(
        request.user, following_ids,
        seen_suggestion_ids=seen_suggestion_ids,
        seen_market_ids=seen_market_ids,
        seen_job_ids=seen_job_ids,
        seen_event_ids=seen_event_ids,
        seen_business_ids=seen_business_ids,
        market_category=market_category,
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
            })
        return HttpResponse(status=204)

    return render(request, 'snippet/feed_posts_partial.html', {
        'posts_with_ads': feed,
        'next_cursor':    next_cursor,
        'following_ids':  following_ids,
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
            'user_listings': [],
            'user_listings_count': 0,
            'suggested_pages': [],
            'saved_products': [],
            'saved_products_count': 0,
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

    # ── Listings owned by this user (for the "My Listings" grid on the profile) ──
    user_listings_qs = (
        Market.objects.filter(product_owner=user)
        .order_by('-posted_on')
        .prefetch_related('images')
    )
    user_listings_count = user_listings_qs.count()
    user_listings = list(user_listings_qs[:8])

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

    # Wishlist ("likes") counts per listing — queried separately so we don't
    # depend on a specific reverse-relation name from the Wishlist model.
    listing_ids = [listing.product_id for listing in user_listings] + [p.product_id for p in saved_products]
    wishlist_counts = {}
    if listing_ids:
        for row in (Wishlist.objects.filter(product_id__in=listing_ids)
                    .values('product_id').annotate(c=Count('id'))):
            wishlist_counts[row['product_id']] = row['c']
    for listing in user_listings:
        listing.like_count = wishlist_counts.get(listing.product_id, 0)
    for product in saved_products:
        product.like_count = wishlist_counts.get(product.product_id, 0)

    context = {
        'user': user, 'profile': profile,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': False,
        'can_view_details': can_view_details,
        'is_own_profile': is_own_profile,
        'is_following': is_following,
        'sidebar_following_count': sidebar_following_count,
        'sidebar_follower_count':  sidebar_follower_count,
        'business_pages': business_pages,
        'business_page_count': business_page_count,
        'business_page_previews': business_page_previews,
        'wishlist_ids': wishlist_ids,
        'user_listings': user_listings,
        'user_listings_count': user_listings_count,
        'suggested_pages': suggested_pages,
        'saved_products': saved_products,
        'saved_products_count': saved_products_count,
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

            if profile_dirty:
                profile.save()

            if image:
                profile.picture = image
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
                        'website':         profile.website,
                        'privacy_level':   profile.privacy_level,
                        'gender':          profile.gender,
                        'date_of_birth':   profile.date_of_birth.isoformat() if profile.date_of_birth else '',
                        'show_gender':     profile.show_gender,
                        'show_dob':        profile.show_dob,
                        'profession':      profile.profession,
                    },
                    'message': 'Profile updated successfully!'
                })
            else:
                messages.info(request, 'Profile Updated Successfully')
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
    else:
        current_profile.followings.remove(other_profile)
        action = 'unfollowed'
        messages.info(request, 'unFollowing')

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
    return (
        User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(profile__bio__icontains=query)
        )
        .select_related('profile')
        .annotate(follower_count=Count('profile__followers', distinct=True))
        .distinct()
    )


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
        .annotate(follower_count=Count('followers', distinct=True))
        .distinct()
        .order_by('-follower_count')
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

        users_total    = users_qs.count()
        products_total = products_qs.count()
        pages_total    = pages_qs.count()
        jobs_total     = jobs_qs.count()

        users    = users_qs[:_PAGE]
        products = products_qs[:_PAGE]
        pages    = pages_qs[:_PAGE]
        jobs     = jobs_qs[:_PAGE]

        recent_searches = (
            SearchHistory.objects.filter(user=request.user)
            .exclude(query=query).order_by('-created_at')[:8]
        )

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
            'recent_searches':   recent_searches,
            'page_size':         _PAGE,
            'unread_follow_count':        _unread_follow_count,
        })

    # ── Explore (no query) ─────────────────────────────────────────────────────
    _EXPLORE_PAGE = 12
    search_history = (
        SearchHistory.objects.filter(user=request.user).order_by('-created_at')[:20]
    )

    current_profile = request.user.profile
    following_profile_ids = current_profile.followings.values_list('id', flat=True)
    suggested_users = (
        Profile.objects
        .exclude(user=request.user)
        .exclude(id__in=following_profile_ids)
        .annotate(follower_count=Count('followers'))
        .order_by('-follower_count')[:12]
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
        .annotate(follower_count=Count('followers', distinct=True))
        .order_by('-follower_count')[:10]
    )

    # ── Sidebar context ────────────────────────────────────────────────────────
    _unread_follow_count = FollowNotification.objects.filter(to_user=request.user, is_read=False).count()

    return render(request, 'search.html', {
        'search_history':        search_history,
        'suggested_users':       suggested_users,
        'explore_products':      explore_products,
        'explore_has_more':      explore_products_total > _EXPLORE_PAGE,
        'trending_pages':        trending_pages,
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

    users_qs = (
        User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(profile__bio__icontains=query)
        )
        .select_related('profile')
        .annotate(follower_count=Count('profile__followers', distinct=True))
        .distinct()
    )
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

    return render(request, 'snippet/search_products_partial.html', {
        'products': products,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
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

    context = {
        'grouped_messages': grouped_messages,
        'receiver': receiver,
        'product_context': product_context,
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
        else:
            message_text = request.POST.get('message', '')
            reply_to_id = request.POST.get('reply_to')
            product_id_raw = request.POST.get('product_id')
        
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

        msg_obj = Message.objects.create(
            sender=request.user, receiver=receiver,
            conversation=message_text if message_text else '',
            file_type=file_type,
            file=file_upload if file_upload else None,
            reply_to=reply_to,
            link_preview=link_preview,
            linked_product=linked_product_obj,
            linked_product_snapshot=linked_product_snapshot,
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
# Notification Views (removed - only FollowNotification remains)
# ─────────────────────────────────────────────────────────────────────────────



@login_required(login_url='/')
def notification_list(request):
    # Only FollowNotification is used now
    from .models import FollowNotification as _FN
    _FN.objects.filter(to_user=request.user, is_read=False).update(is_read=True)

    if request.GET.get('panel') == '1':
        return render(request, 'snippet/notification_panel_partial.html')

    return render(request, 'notification.html')


def notification_partial(request):
    if request.user.is_authenticated:
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
    else:
        unread_follow_count = 0
    return render(request, 'snippet/notification_count.html', {
        'unread_follow_count': unread_follow_count,
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

    return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)


@login_required
@require_POST
def mark_all_notifications_read(request):
    FollowNotification.objects.filter(
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

    context = {
        'product': product, 'images': images,
        'related_products': related_products, 'seller': seller_profile,
        'all_categories': Market.CATEGORY_CHOICES,
        'business_page': product.business_page,
        'in_wishlist': in_wishlist,
    }
    return render(request, 'product_details.html', context)


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

    return render(request, 'wishlist.html', {
        'products':      page_obj,
        'wishlist_count': len(products),
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
    Supports optional ?type= filter (town | festival | wedding | other).
    """
    event_type = request.GET.get('type', '').strip()

    events = SocialEvent.objects.all().order_by('date', 'time')
    if event_type and event_type in dict(SocialEvent.TYPE_CHOICES):
        events = events.filter(event_type=event_type)

    counts = {
        'town':     SocialEvent.objects.filter(event_type='town').count(),
        'festival': SocialEvent.objects.filter(event_type='festival').count(),
        'wedding':  SocialEvent.objects.filter(event_type='wedding').count(),
        'other':    SocialEvent.objects.filter(event_type='other').count(),
    }

    user_can_post = False
    missing_fields = []
    if request.user.is_authenticated:
        user_can_post, missing_fields = _profile_post_status(request.user)

    return render(request, 'event_calendar.html', {
        'events':        events,
        'event_type':    event_type,
        'counts':        counts,
        'user_can_post': user_can_post,
        'missing_fields': missing_fields,
    })


def _event_parse_and_validate(post_data, files):
    """Shared validation for create/edit. Returns (cleaned_data, error_str)."""
    title       = html_escape(post_data.get('title', '').strip())
    event_type  = post_data.get('event_type', '').strip()
    date_str    = post_data.get('date', '').strip()
    time_str    = post_data.get('time', '').strip()
    location    = html_escape(post_data.get('location', '').strip())
    description = html_escape(post_data.get('description', '').strip())
    cover_image = files.get('cover_image') if files else None

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

    if cover_image:
        _ALLOWED_IMG = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
        if cover_image.content_type not in _ALLOWED_IMG:
            return None, 'Only JPEG, PNG, WebP or GIF images are allowed.'
        if cover_image.size > 10 * 1024 * 1024:
            return None, 'Image must be under 10 MB.'

    return {
        'title': title, 'event_type': event_type, 'date': ev_date,
        'time': time_obj, 'location': location, 'description': description,
        'cover_image': cover_image,
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
        location=data['location'],
        description=data['description'],
        created_by=request.user,
    )
    if data['cover_image']:
        event.cover_image = data['cover_image']
    event.save()

    return JsonResponse({
        'success': True,
        'event': {
            'id':          event.id,
            'title':       event.title,
            'event_type':  event.event_type,
            'date':        event.date.isoformat(),
            'time':        event.time.strftime('%H:%M') if event.time else '',
            'location':    event.location,
            'description': event.description,
            'cover_image': _event_image_url(event),
            'is_owner':    True,
        }
    })


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

    event.title       = data['title']
    event.event_type  = data['event_type']
    event.date        = data['date']
    event.time        = data['time']
    event.location    = data['location']
    event.description = data['description']

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

    return JsonResponse({
        'success': True,
        'event': {
            'id':          event.id,
            'title':       event.title,
            'event_type':  event.event_type,
            'date':        event.date.isoformat(),
            'time':        event.time.strftime('%H:%M') if event.time else '',
            'location':    event.location,
            'description': event.description,
            'cover_image': _event_image_url(event),
        }
    })


@login_required(login_url='/')
@require_POST
def event_calendar_delete(request, event_id):
    """AJAX endpoint — delete a SocialEvent (owner only)."""
    event = get_object_or_404(SocialEvent, id=event_id)
    if event.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Not authorised.'}, status=403)

    if event.cover_image:
        try:
            import cloudinary.uploader as _cu
            _cu.destroy(str(event.cover_image))
        except Exception:
            pass

    event.delete()
    return JsonResponse({'success': True})


# =============================================================================
# JOB VACANCY VIEWS - Updated to work with Cloudinary in both debug/production
# =============================================================================

@login_required(login_url='/')
def job_vacancy(request):
    """
    Job Vacancy listing page.
    Supports optional ?category= filter (gig | fulltime | apprenticeship).
    """
    category = request.GET.get('category', '').strip()

    qs = JobVacancy.objects.filter(is_open=True).select_related('posted_by__profile')
    if category and category in dict(JobVacancy.CATEGORY_CHOICES):
        qs = qs.filter(category=category)

    counts = {
        'gig':            JobVacancy.objects.filter(is_open=True, category='gig').count(),
        'fulltime':       JobVacancy.objects.filter(is_open=True, category='fulltime').count(),
        'apprenticeship': JobVacancy.objects.filter(is_open=True, category='apprenticeship').count(),
        'total':          JobVacancy.objects.filter(is_open=True).count(),
    }

    paginator = Paginator(qs, 12)
    page_obj  = paginator.get_page(request.GET.get('page'))

    user_can_post, missing_fields = _profile_post_status(request.user)

    return render(request, 'job_vacancy.html', {
        'jobs':           page_obj,
        'counts':         counts,
        'category':       category,
        'user_can_post':  user_can_post,
        'missing_fields': missing_fields,
    })


@login_required(login_url='/')
@require_POST
def job_vacancy_create(request):
    """AJAX — create a new JobVacancy."""
    can_post, missing = _profile_post_status(request.user)
    if not can_post:
        msg = 'Please complete your profile before posting jobs. Missing: ' + ', '.join(missing) + '.'
        return JsonResponse({'success': False, 'error': msg, 'error_code': 'incomplete_profile'}, status=403)

    title        = html_escape(request.POST.get('title', '').strip())
    category     = request.POST.get('category', '').strip()
    company      = html_escape(request.POST.get('company', '').strip())
    location     = html_escape(request.POST.get('location', '').strip())
    description  = html_escape(request.POST.get('description', '').strip())
    requirements = html_escape(request.POST.get('requirements', '').strip())
    contact_info = html_escape(request.POST.get('contact_info', '').strip())
    salary_range = html_escape(request.POST.get('salary_range', '').strip())
    cover_image  = request.FILES.get('cover_image')
    page_slug    = request.POST.get('business_page', '').strip()

    if not title:
        return JsonResponse({'success': False, 'error': 'Job title is required.'}, status=400)
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid category.'}, status=400)
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required.'}, status=400)

    # Optional — post this job vacancy under one of the user's own business pages
    business_page = None
    if page_slug:
        business_page = get_object_or_404(BusinessPage, slug=page_slug)
        if business_page.owner != request.user:
            return JsonResponse({'success': False, 'error': 'Not authorised for that business page.'}, status=403)
        if not company:
            company = business_page.name

    job = JobVacancy(
        posted_by     = request.user,
        title         = title,
        category      = category,
        company       = company,
        location      = location,
        description   = description,
        requirements  = requirements,
        contact_info  = contact_info,
        salary_range  = salary_range,
        business_page = business_page,
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
            'id':       str(job.id),
            'title':    job.title,
            'category': job.category,
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

    title        = html_escape(request.POST.get('title', '').strip())
    category     = request.POST.get('category', '').strip()
    company      = html_escape(request.POST.get('company', '').strip())
    location     = html_escape(request.POST.get('location', '').strip())
    description  = html_escape(request.POST.get('description', '').strip())
    requirements = html_escape(request.POST.get('requirements', '').strip())
    contact_info = html_escape(request.POST.get('contact_info', '').strip())
    salary_range = html_escape(request.POST.get('salary_range', '').strip())
    is_open      = request.POST.get('is_open', '1').strip() == '1'
    cover_image  = request.FILES.get('cover_image')
    page_slug    = request.POST.get('business_page', None)

    if not title:
        return JsonResponse({'success': False, 'error': 'Job title is required.'}, status=400)
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        return JsonResponse({'success': False, 'error': 'Invalid category.'}, status=400)
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required.'}, status=400)

    # Optional — reassign the business page this job is posted under (owner only)
    if page_slug is not None:
        if page_slug.strip() == '':
            job.business_page = None
        else:
            business_page = get_object_or_404(BusinessPage, slug=page_slug.strip())
            if business_page.owner != request.user:
                return JsonResponse({'success': False, 'error': 'Not authorised for that business page.'}, status=403)
            job.business_page = business_page

    job.title        = title
    job.category     = category
    job.company      = company
    job.location     = location
    job.description  = description
    job.requirements = requirements
    job.contact_info = contact_info
    job.salary_range = salary_range
    job.is_open      = is_open

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
        return _card_comments_post(request, event, EventComment, 'event')
    return _card_comments_get(request, event, EventComment, 'event')

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

@login_required(login_url='/')
def business_page_create(request):
    from social.models import BusinessPage
    if BusinessPage.objects.filter(owner=request.user).count() >= 3:
        messages.error(request, 'You can create up to 3 business pages.')
        return redirect('business_pages_mine')

    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        category    = request.POST.get('category', 'others').strip()
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

        if errors:
            return render(request, 'business_page_create.html', {
                'errors': errors, 'form_data': request.POST,
                'categories': BusinessPage.CATEGORY_CHOICES,
            })

        page = BusinessPage(
            owner=request.user, name=name, category=category,
            tagline=tagline, description=description, location=location,
            website=website, whatsapp=whatsapp, phone=phone, email=email_val,
            instagram=instagram, youtube=youtube, facebook=facebook,
            twitter=twitter, tiktok=tiktok,
        )
        if request.FILES.get('logo'):        page.logo        = request.FILES['logo']
        if request.FILES.get('cover_photo'): page.cover_photo = request.FILES['cover_photo']

        try:
            page.save()
        except Exception as exc:
            messages.error(request, f'Could not create page: {exc}')
            return render(request, 'business_page_create.html', {
                'errors': {}, 'form_data': request.POST,
                'categories': BusinessPage.CATEGORY_CHOICES,
            })

        messages.success(request, f'"{page.name}" is live! 🎉')
        return redirect('business_page_detail', slug=page.slug)

    return render(request, 'business_page_create.html', {
        'categories': BusinessPage.CATEGORY_CHOICES,
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

    wishlist_ids = set(
        Wishlist.objects.filter(user=request.user, product__business_page=page)
        .values_list('product_id', flat=True)
    ) if request.user.is_authenticated else set()

    # Products the user has already saved to their wishlist shouldn't be
    # shown again in the page's listing grid — but the owner should still
    # see their own full catalog when managing the page.
    if request.user.is_authenticated and not is_owner and wishlist_ids:
        listings = listings.exclude(product_id__in=wishlist_ids)

    return render(request, 'business_page_detail.html', {
        'page':              page,
        'listings':          listings,
        'jobs':              jobs,
        'job_count':         jobs.count(),
        'is_owner':          is_owner,
        'is_follower':       is_follower,
        'follower_count':    page.follower_count,
        'listing_count':     listings.count(),
        'market_categories': Market.CATEGORY_CHOICES,
        'job_categories':    JobVacancy.CATEGORY_CHOICES,
        'wishlist_ids':      wishlist_ids,
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
    return JsonResponse({'following': following, 'follower_count': page.follower_count})


@login_required(login_url='/')
def business_page_edit(request, slug):
    from social.models import BusinessPage
    page = get_object_or_404(BusinessPage, slug=slug, owner=request.user)

    if request.method == 'POST':
        page.name        = request.POST.get('name', page.name).strip()
        page.category    = request.POST.get('category', page.category).strip()
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
            business_page=page,
        )
        for img_file in request.FILES.getlist('images')[:5]:
            MarketImage.objects.create(product=product, product_image=img_file)
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
    title        = html_escape(request.POST.get('title', '').strip())
    category     = request.POST.get('category', '').strip()
    company      = html_escape(request.POST.get('company', page.name).strip() or page.name)
    location     = html_escape(request.POST.get('location', page.location or '').strip())
    description  = html_escape(request.POST.get('description', '').strip())
    requirements = html_escape(request.POST.get('requirements', '').strip())
    contact_info = html_escape(request.POST.get('contact_info', page.whatsapp or '').strip())
    salary_range = html_escape(request.POST.get('salary_range', '').strip())
    cover_image  = request.FILES.get('cover_image')

    # ── Validation ───────────────────────────────────────────────────────────────
    errors = {}
    if not title:
        errors['title'] = 'Job title is required.'
    if category not in dict(JobVacancy.CATEGORY_CHOICES):
        errors['category'] = 'Please choose a valid category.'
    if not description:
        errors['description'] = 'Description is required.'
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
            posted_by     = request.user,
            business_page = page,
            title         = title,
            category      = category,
            company       = company,
            location      = location,
            description   = description,
            requirements  = requirements,
            contact_info  = contact_info,
            salary_range  = salary_range,
            cover_image   = cover_image if cover_image else None,
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
        'cover_url':  job.cover_image.url if job.cover_image else '',
        'detail_url': f"/jobs/#khj-card-{job.id}",
        'message':    'Job vacancy posted successfully! 💼',
    })
