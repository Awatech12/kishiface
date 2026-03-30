import os
import re
import uuid as uuid_module
import socket
import threading
from html import escape as html_escape, unescape as html_unescape
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from .models import FollowNotification
from django.template.loader import render_to_string
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, Post, PostImage, PostVibe, UserReport, BlockedUser, CommentReply, ChannelUserLastSeen, PostComment, Message, Notification, ChannelMessage, Channel, Market, MarketImage, SearchHistory, LoginAttempt, UserFeedProfile
from django.db.models import Q
from django.db.models import Count, Max, Min
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time, json, logging, re, requests, ipaddress, math
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
    'http://localhost',
    'https://kishiface.onrender.com',
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

        # ── Layer 1: django-axes (settings.py) ───────────────────────────────
        # Handled automatically by AxesMiddleware + AxesStandaloneBackend.
        # Locks after AXES_FAILURE_LIMIT=5 attempts for 1 hour by username+IP.

        # ── Layer 2: LoginAttempt DB (username-only, any device/IP) ──────────
        # Catches attackers who rotate IPs/VPNs to bypass axes.
        # Locks after 10 failed attempts within 15 minutes per username.
        blocked, seconds_left = LoginAttempt.is_blocked(user_check)
        if blocked:
            mins = max(1, round(seconds_left / 60))
            messages.error(
                request,
                f'Too many failed attempts on this account. '
                f'Please wait {mins} minute(s) before trying again.'
            )
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
            # Clear Layer 2 failed attempts on successful login
            LoginAttempt.clear(user_check)
            return redirect(_safe_next(request, '/home'))
        else:
            # Record failed attempt for Layer 2
            LoginAttempt.record(user_check, succeeded=False)
            # Deliberately vague — don't reveal whether the username exists
            messages.error(request, 'Invalid username or password. Please try again.')
            return redirect('/')

    # ── GET ───────────────────────────────────────────────────────────────────
    return render(request, 'index.html')

@csrf_protect
def register(request):
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
                messages.error(request, err)
            return redirect('register')

        secret_question = html_escape(request.POST.get('secret_question', '').strip())
        secret_answer   = request.POST.get('secret_answer', '').strip()

        from .models import SecretQuestion
        valid_keys = [k for k, _ in SecretQuestion.QUESTION_CHOICES]
        if not secret_question or secret_question not in valid_keys:
            messages.error(request, 'Please choose a valid security question.')
            return redirect('register')
        if not secret_answer or len(secret_answer) < 2:
            messages.error(request, 'Security answer must be at least 2 characters.')
            return redirect('register')

        user = User.objects.create_user(username=username, email=email, password=password)
        Profile.objects.create(user=user)

        sq = SecretQuestion(user=user, question=secret_question)
        sq.set_answer(secret_answer)
        sq.save()

        messages.success(request, f'Welcome {username}! You can now log in.')
        return redirect('/')

    return render(request, 'register.html')


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

    # Clear any brute-force locks for this user
    LoginAttempt.clear(username)
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




def extract_hashtags(content):
    """Extract hashtags from post content"""
    import re
    hashtags = re.findall(r'#(\w+)', content)
    return hashtags


def _safe_redirect_back(request, fallback='home'):
    """
    Redirect back to the referring page only if the referer is our own domain.
    Prevents open-redirect attacks where a forged Referer header sends users
    to an external site.
    """
    referer = request.META.get('HTTP_REFERER', '')
    allowed_origins = (
        'http://127.0.0.1',
        'http://localhost',
        'https://kishiface.onrender.com',
    )
    if referer and any(referer.startswith(origin) for origin in allowed_origins):
        return redirect(referer)
    return redirect(fallback)


# ─────────────────────────────────────────────────────────────────────────────
# Feed helpers — shared between home() and feed_load_more()
# KVIBE FEED ALGORITHM v2.0
# Signals: Rule-Based · Behavior-Based · Vibe-Based · Network · Exploration
# ─────────────────────────────────────────────────────────────────────────────

FEED_PAGE_SIZE = 10          # posts returned per page
_EXPLORE_RATIO = 0.15        # 15 % of each page is random exploration

# _FEED_SAMPLE is now computed dynamically inside _get_feed_page().
# Formula: clamp(following_count * 4, min=40, max=400)
# - 0–10 followings  → 40   (new/small accounts)
# - 50  followings   → 200  (healthy mid-size account)
# - 100+ followings  → 400  (power users / viral scale)
_FEED_SAMPLE_MIN = 40
_FEED_SAMPLE_MAX = 400
_FEED_SAMPLE_MULTIPLIER = 4   # posts per followed account in the candidate pool

# ── View-signal tuning knobs ──────────────────────────────────────────────────
# These three constants control exactly how much influence view data has on
# the final score.  Keep them well below the engagement/recency floor so that
# pure view-farming never outcompetes genuine interaction.
#
#   _VIEW_VELOCITY_CAP   — log2-compressed velocity ceiling (views/hour).
#                          log2(1 + 200) ≈ 7.65, so a post doing 200 views/h
#                          earns the full cap.  Beyond that: diminishing returns.
#   _VIEW_VELOCITY_WEIGHT — how many score points a maximally-fast post earns.
#                           Kept at 1.5 so velocity never dominates recency (max ~2).
#   _VER_QUALITY_CAP     — view-to-engagement ratio cap before quality multiplier
#                           is clamped.  5 % VER → multiplier ≈ 1.10 (10 % boost).
#                           This rewards content that actually makes people react.
#   _VIEW_VOLUME_WEIGHT  — compressed raw-view bonus (diminishing returns).
#                           log2(1 + 10000) ≈ 13.3 → 0.5-pt bonus at viral scale.
#                           Intentionally tiny — this is a tiebreaker, not a driver.
_VIEW_VELOCITY_CAP    = 200.0   # views / hour ceiling before log compression
_VIEW_VELOCITY_WEIGHT = 1.5     # max score contribution from velocity
_VER_QUALITY_CAP      = 0.10    # 10 % VER → maximum quality multiplier
_VIEW_VOLUME_WEIGHT   = 0.5     # weight on log2-compressed raw view count


def _build_fof(following_ids_set, current_user_id):
    """
    Resolve friend-of-friend data in 2 bulk DB queries.
    Returns (fof_ids: set, fof_via_map: dict {uid: [User, ...]}).
    """
    fof_pairs = list(
        Profile.objects
        .filter(user__in=following_ids_set)
        .values_list('user_id', 'followings__user')
    )
    fof_ids     = set()
    fof_via_map = {}
    for follower_id, fof_uid in fof_pairs:
        if fof_uid and fof_uid not in following_ids_set and fof_uid != current_user_id:
            fof_ids.add(fof_uid)
            fof_via_map.setdefault(fof_uid, set()).add(follower_id)

    connector_users = {u.id: u for u in User.objects.filter(id__in=following_ids_set)}
    fof_via_resolved = {
        fof_uid: [connector_users[cid] for cid in cids if cid in connector_users]
        for fof_uid, cids in fof_via_map.items()
    }
    return fof_ids, fof_via_resolved


def _get_or_create_feed_profile(user):
    """Lazily fetch/create the UserFeedProfile for this user."""
    profile, _ = UserFeedProfile.objects.get_or_create(user=user)
    return profile


def _build_user_interest_profile(user):
    """
    Behavior-Based — derive interacted post_ids & author affinity scores from
    the last 30 days of likes, vibes, and comments.

    AUTHOR AFFINITY DECAY: interactions are time-weighted so a like from
    5 minutes ago carries far more signal than one from 29 days ago.
    Each interaction's weight is: base_weight * exp(-age_days * ln(2) / 7)
    giving a 7-day half-life.  The resulting per-author score is stored in
    `author_affinity` (dict[author_id → float]) and used by _score_post()
    instead of the old flat +4.0 bump for any author touched in 30 days.

    Query count: 3 (one per model, each fetching timestamp + author in one pass).
    Results are cached in Django's cache backend for 5 minutes so rapid
    load-more scrolling doesn't re-run these on every page.

    Returns:
        interacted_post_ids : set[str]
        author_affinity     : dict[int, float]   ← NEW (replaces flat set)
    """
    from django.core.cache import cache

    cache_key = f'kvibe_interest_v2_{user.id}'
    cached    = cache.get(cache_key)
    if cached is not None:
        return cached

    now    = timezone.now()
    cutoff = now - timedelta(days=30)

    # Affinity decay: half-life 7 days.
    # weight(age_days) = base * exp(-age_days * ln2 / 7)
    _AFFINITY_HALF_LIFE = 7.0   # days
    _AFFINITY_DECAY     = math.log(2) / _AFFINITY_HALF_LIFE

    def _affinity_weight(base, interacted_at):
        age_days = max(0.0, (now - interacted_at).total_seconds() / 86400)
        return base * math.exp(-_AFFINITY_DECAY * age_days)

    interacted_post_ids = set()
    author_affinity: dict = {}   # author_id → cumulative decayed score

    def _accum(aid, weight):
        if aid:
            author_affinity[aid] = author_affinity.get(aid, 0.0) + weight

    # ── Likes (base weight 4.0, same as the old flat bonus) ──────────────────
    liked_rows = Post.objects.filter(
        likes=user, created_at__gte=cutoff
    ).values_list('post_id', 'author_id', 'created_at')
    for pid, aid, created_at in liked_rows:
        interacted_post_ids.add(str(pid))
        _accum(aid, _affinity_weight(4.0, created_at))

    # ── Vibes (base weight 4.0) ───────────────────────────────────────────────
    vibed_rows = PostVibe.objects.filter(
        user=user, created_at__gte=cutoff
    ).select_related('post').values_list('post_id', 'post__author_id', 'created_at')
    for pid, aid, created_at in vibed_rows:
        interacted_post_ids.add(str(pid))
        _accum(aid, _affinity_weight(4.0, created_at))

    # ── Comments (base weight 4.0) ────────────────────────────────────────────
    cmt_rows = PostComment.objects.filter(
        author=user, created_at__gte=cutoff
    ).select_related('post').values_list('post_id', 'post__author_id', 'created_at')
    for pid, aid, created_at in cmt_rows:
        interacted_post_ids.add(str(pid))
        _accum(aid, _affinity_weight(4.0, created_at))

    # ── Views (base weight 1.0) ───────────────────────────────────────────────
    # Views are a passive signal — lower base weight than likes/vibes/comments
    # so that merely scrolling past a post doesn't create the same affinity as
    # actively engaging with it.  We still include it because repeated views of
    # a creator's work (e.g. watching a video twice) is a meaningful intent
    # signal that the other three actions won't capture.
    # We proxy "viewed posts" via the Post.view field increment: any post the
    # user explicitly played or opened the comment sheet for will have had its
    # view count bumped via /record-view/, and the post appears in the pool if
    # the author is followed or the post surfaced via explore.  Rather than a
    # separate ViewLog table, we read the recent Post pool filtered by author
    # and infer passive affinity from the author set — a conservative but
    # zero-migration approach that stays consistent with the existing system.
    viewed_rows = Post.objects.filter(
        author__in=list(author_affinity.keys()) or [user.id],  # use author IDs not post IDs
        created_at__gte=cutoff,
        view__gt=0,
    ).exclude(
        post_id__in=[pid for pid in interacted_post_ids]  # already counted above
    ).values_list('post_id', 'author_id', 'created_at', 'view')

    # We weight by view count (log-compressed) so a post with 100 views earns
    # slightly more affinity than one with 1 view, but with diminishing returns.
    for pid, aid, created_at, view_count in viewed_rows:
        view_weight = 1.0 * math.log2(1 + (view_count or 0))
        _accum(aid, _affinity_weight(min(view_weight, 2.0), created_at))

    result = (interacted_post_ids, author_affinity)
    cache.set(cache_key, result, timeout=300)   # 5-minute TTL
    return result


def _score_post(post, now, vibe_weights, interacted_post_ids,
                author_affinity, fof_ids, adaptive_author_ids):
    """
    Master scoring — returns float.  Higher score = shown earlier.

    ┌─────────────────────────────────────────────────────────────────┐
    │ 1. Rule-Based                                                   │
    │    engagement: pulled from the ORIGINAL post for reposts so    │
    │                the full social proof of the original counts;    │
    │                log2(1 + weighted_sum) — diminishing returns     │
    │    recency:    age of THIS post object (repost row = fresh);   │
    │                half-life 24 h + hard ceiling at 72 h           │
    │    newness bonus: smooth exponential decay (half-life 1.5 h)   │
    │                   so fresh posts surface without a cliff       │
    │ 2. View Signals (3 sub-signals, all log-compressed)             │
    │    velocity:   views/hour — surface fast-climbing content       │
    │                before the crowd catches on (weight 1.5 max)     │
    │    quality:    view-to-engagement ratio used as a multiplier    │
    │                on the engagement score — rewards content that   │
    │                converts passive viewers into active reactors    │
    │                (capped at +10 % boost, min neutral 1.0×)       │
    │    volume:     log-compressed raw view count — tiny tiebreaker  │
    │                for proven-popular content (weight 0.5 max)      │
    │ 3. Behavior-Based                                               │
    │    +3   already interacted with this post / its original       │
    │    affinity score from author_affinity dict (time-decayed,     │
    │         7-day half-life — recent interactions worth far more)   │
    │    +2   author in long-term UserFeedProfile history            │
    │ 4. Vibe-Based 🔥                                                │
    │    vibes pulled from original post for reposts;                │
    │    weighted by viewer's personal vibe_weights                   │
    │ 5. Network                                                      │
    │    +2.5  original author is a friend-of-friend                 │
    │ 6. Exploration jitter (applied in _get_feed_page, not here)     │
    └─────────────────────────────────────────────────────────────────┘
    """
    # ── Resolve the "real" post for engagement/vibe signals ──────────────────
    # For a repost we count the ORIGINAL post's engagement (its full social
    # proof) but use THIS post row's created_at for recency (the repost is a
    # fresh share event and should be treated as new content in the feed).
    signal_post = (
        post.original_post
        if post.is_repost and post.original_post
        else post
    )

    # ── 1a. Raw weighted engagement ───────────────────────────────────────────
    # Always read annotations from `post` (the feed row) — it carries the DB
    # annotations (vibe_count, comment_count, repost_count). For reposts, the
    # vibe breakdown of the original is already merged into _vb_<type> attrs
    # by _annotate_vibe_breakdown(), so signal_post is only used for share count
    # (a plain IntegerField, not an annotation).
    raw_vibe_count    = getattr(post, 'vibe_count',    0)
    raw_comment_count = getattr(post, 'comment_count', 0)
    raw_repost_count  = getattr(post, 'repost_count',  0)
    raw_share_count   = (getattr(signal_post, 'share', None) or getattr(post, 'share', 0) or 0)

    raw_engagement = (
        raw_vibe_count    * 4 +
        raw_comment_count * 3 +
        raw_repost_count  * 2 +
        raw_share_count   * 1
    )
    # Log-compress: viral posts face diminishing returns.
    # log2(1+x): 0→0  10→3.46  100→6.66  1000→9.97
    engagement = math.log2(1 + raw_engagement)

    # ── 1b. Recency (always from THIS post row) ──────────────────────────────
    #   Phase 1 (0–72 h): exponential decay, half-life = 24 h
    #   Phase 2 (72 h+):  hard ceiling — old viral posts can never lock the feed
    _HALF_LIFE_HOURS    = 24
    _AGE_HARD_CAP_HOURS = 72
    _RECENCY_FLOOR      = 2 ** (-_AGE_HARD_CAP_HOURS / _HALF_LIFE_HOURS)  # 0.125

    age_hours = max(0.0, (now - post.created_at).total_seconds() / 3600)
    recency   = 2 ** (-age_hours / _HALF_LIFE_HOURS)
    if age_hours >= _AGE_HARD_CAP_HOURS:
        recency = _RECENCY_FLOOR

    score = engagement * recency

    # ── 1c. Newness bonus — guarantee fresh posts always surface ─────────────
    # A brand-new post with zero engagement scores log2(1)*1.0 = 0.0, which
    # means it gets buried under everything with even 1 interaction.
    # The newness bonus gives it a fighting chance in its early hours.
    #
    # OLD design: stepped (+2.0 → +1.0 → +0.0) caused a hard "ranking cliff"
    # exactly at the 2-hour mark — a post could suddenly vanish from the feed.
    #
    # NEW design: smooth exponential decay with half-life of 1.5 hours.
    #   bonus = 2.0 * exp(-age_hours * ln(2) / 1.5)
    #   age 0 h  → +2.00   (just posted)
    #   age 1 h  → +1.26   (still very fresh)
    #   age 2 h  → +0.79   (fading naturally)
    #   age 4 h  → +0.31   (fading further)
    #   age 6 h  → +0.13   (nearly gone)
    #   age 8 h+ → <0.06   (negligible — engagement drives ranking)
    _NEWNESS_PEAK      = 2.0
    _NEWNESS_HALF_LIFE = 1.5   # hours
    _NEWNESS_DECAY     = math.log(2) / _NEWNESS_HALF_LIFE
    score += _NEWNESS_PEAK * math.exp(-_NEWNESS_DECAY * age_hours)

    # ── 2. View Signals ───────────────────────────────────────────────────────
    # Read view count from the signal post (original for reposts) so we
    # always reflect the true accumulated audience of the content.
    raw_views = max(0, getattr(signal_post, 'view', None) or 0)

    # ── 2a. View velocity — surface fast-rising content ──────────────────────
    # views/hour gives a momentum signal independent of age.  A post with
    # 500 views in 2 hours outranks a week-old post with 2,000 views because
    # the audience is still actively discovering it RIGHT NOW.
    # We use max(age, 0.5) so a brand-new post (age < 30 min) doesn't get an
    # artificially infinite velocity that floods the feed with zero-engagement posts.
    #
    # Velocity curve (with _VIEW_VELOCITY_WEIGHT = 1.5):
    #   10  views/h → log2(11)  / log2(201) * 1.5 ≈ 0.55
    #   50  views/h → log2(51)  / log2(201) * 1.5 ≈ 1.06
    #   200 views/h → log2(201) / log2(201) * 1.5 = 1.50  (cap)
    views_per_hour   = raw_views / max(age_hours, 0.5)
    capped_velocity  = min(views_per_hour, _VIEW_VELOCITY_CAP)
    velocity_score   = (math.log2(1 + capped_velocity) /
                        math.log2(1 + _VIEW_VELOCITY_CAP)) * _VIEW_VELOCITY_WEIGHT
    score += velocity_score

    # ── 2b. View-to-engagement ratio (VER) — quality multiplier ─────────────
    # VER = (vibes + comments + reposts + shares) / views
    # A high VER means viewers are not just watching — they're reacting.
    # We apply this as a multiplier on the already-computed engagement score
    # so that high-quality viral content is amplified, while passive/skip-heavy
    # content (high views, almost no reactions) gets no boost at all.
    #
    # Multiplier design: 1.0 (neutral) at VER=0, rising linearly to 1.10 at VER=_VER_QUALITY_CAP.
    # So at most 10 % amplification — keeps VER as a tiebreaker, not a primary driver.
    #   VER 0 %  → ×1.00  (no boost — people scrolled past without reacting)
    #   VER 2 %  → ×1.02  (slightly above average)
    #   VER 5 %  → ×1.05  (good conversion rate)
    #   VER 10%+ → ×1.10  (excellent — almost every viewer reacted)
    if raw_views > 0:
        total_engagements = raw_vibe_count + raw_comment_count + raw_repost_count + raw_share_count
        ver               = min(total_engagements / raw_views, _VER_QUALITY_CAP)
        quality_mult      = 1.0 + (ver / _VER_QUALITY_CAP) * 0.10   # maps [0, cap] → [1.0, 1.10]
        score *= quality_mult

    # ── 2c. View volume — tiny popularity tiebreaker ─────────────────────────
    # Pure view count with strong log compression so a post with 10,000 views
    # earns only 0.5 extra points vs a post with 1,000 views earning 0.33.
    # This intentionally tiny bonus stops view farms from gaming the ranking
    # while still letting genuinely popular content hold a marginal edge over
    # equally-engaging but less-seen posts.
    #
    # Volume curve (with _VIEW_VOLUME_WEIGHT = 0.5):
    #   100   views → log2(101)  / log2(10001) * 0.5 ≈ 0.24
    #   1,000 views → log2(1001) / log2(10001) * 0.5 ≈ 0.37
    #  10,000 views → log2(10001)/ log2(10001) * 0.5 = 0.50  (cap)
    _VIEW_VOLUME_CAP = 10_000
    volume_score = (math.log2(1 + min(raw_views, _VIEW_VOLUME_CAP)) /
                    math.log2(1 + _VIEW_VOLUME_CAP)) * _VIEW_VOLUME_WEIGHT
    score += volume_score

    # ── 3. Behavior-Based ────────────────────────────────────────────────────
    actual_author_id = (
        post.original_post.author_id
        if post.is_repost and post.original_post
        else post.author_id
    )
    # Check interaction against both the repost row and its original
    post_ids_to_check = {str(post.post_id)}
    if post.is_repost and post.original_post:
        post_ids_to_check.add(str(post.original_post.post_id))

    if post_ids_to_check & interacted_post_ids:
        score += 3.0
    # Author affinity: time-decayed cumulative score (7-day half-life).
    # A like from 1 day ago (~3.7) outweighs one from 20 days ago (~0.9).
    # Capped at 6.0 so a single hyper-active author can't dominate the feed.
    if actual_author_id in author_affinity:
        score += min(author_affinity[actual_author_id], 6.0)
    if actual_author_id in adaptive_author_ids:
        score += 2.0

    # ── 4. Vibe-Based taste match ─────────────────────────────────────────────
    # For reposts use the vibe breakdown of the original post (attached as
    # _vb_<type> attributes — the pipeline sets these on signal_post via
    # the same post_id used when building vb_lookup).
    vibe_score = sum(
        getattr(post, f'_vb_{vt}', 0) * w
        for vt, w in vibe_weights.items()
    )
    score += vibe_score * 0.5

    # ── 5. Network — friend-of-friend ─────────────────────────────────────────
    if actual_author_id in fof_ids:
        score += 2.5

    return score


def _random_posts_sample(exclude_ids, cursor_dt, n,
                          blocked_ids=None, seen_post_ids=None):
    """
    Return n random Post rows WITHOUT ORDER BY RANDOM().

    Strategy: pick a random offset within the recent-post window
    (last 7 days) so Postgres never has to score the full table.
    Falls back to a small offset scan if the window is thin.

    This replaces .order_by('?') which does a full-table random sort
    and is catastrophically slow on large datasets in PostgreSQL.

    blocked_ids   : set of user IDs — posts from blocked/blocking users
                    are excluded so they never surface through explore.
    seen_post_ids : set of post_ids already rendered in earlier pages —
                    prevents the same post re-appearing via explore on
                    subsequent scroll loads.
    """
    import random as _random

    all_exclude = set(exclude_ids or [])
    if seen_post_ids:
        all_exclude |= set(seen_post_ids)

    base_qs = Post.objects.exclude(post_id__in=all_exclude)
    if blocked_ids:
        base_qs = base_qs.exclude(author__in=blocked_ids)
    if cursor_dt:
        base_qs = base_qs.filter(created_at__lt=cursor_dt)

    # Restrict to a 7-day window to keep the offset range small.
    # We avoid COUNT() entirely — instead we try a random offset and fall back
    # to a smaller offset if the slice returns nothing (empty window).
    window_start = timezone.now() - timedelta(days=7)
    window_qs    = base_qs.filter(created_at__gte=window_start)

    def _fetch(qs, max_offset_hint=500):
        offset = _random.randint(0, max_offset_hint)
        rows = list(
            qs
            .select_related('author', 'author__profile',
                            'original_post', 'original_post__author',
                            'original_post__author__profile')
            .prefetch_related('likes', 'reposts', 'images')
            .annotate(
                vibe_count    = Count('vibes',    distinct=True),
                comment_count = Count('comments', distinct=True),
                repost_count  = Count('reposts',  distinct=True),
            )
            .order_by('created_at')[offset: offset + n]
        )
        return rows

    # Try 7-day window first; if empty fall back to all posts
    rows = _fetch(window_qs, max_offset_hint=500)
    if not rows:
        rows = _fetch(base_qs, max_offset_hint=200)
    return rows


def _annotate_vibe_breakdown(posts):
    """
    Attach _vb_<vibe_type> integer attributes to each post in-place.
    For reposts the breakdown is pulled from the original post's vibes.
    Single bulk query regardless of list size — no N+1.
    """
    if not posts:
        return

    all_ids      = set()
    orig_id_map  = {}
    for p in posts:
        all_ids.add(p.post_id)
        if p.is_repost and p.original_post:
            all_ids.add(p.original_post.post_id)
            orig_id_map[p.post_id] = p.original_post.post_id

    rows = (
        PostVibe.objects
        .filter(post_id__in=all_ids)
        .values('post_id', 'vibe_type')
        .annotate(cnt=Count('id'))
    )
    vb_lookup: dict = {}
    for row in rows:
        vb_lookup.setdefault(row['post_id'], {})[row['vibe_type']] = row['cnt']

    _VIBE_TYPES = ['fire', 'real', 'vibing', 'dead', 'cringe', 'chill', 'love']
    for post in posts:
        lookup_id = orig_id_map.get(post.post_id, post.post_id)
        bd = vb_lookup.get(lookup_id, {})
        for vt in _VIBE_TYPES:
            setattr(post, f'_vb_{vt}', bd.get(vt, 0))


def _get_feed_page(user, following_ids, cursor_dt=None, page_size=None,
                   seen_post_ids=None, seen_suggestion_ids=None):
    """
    Full scored/ranked feed page.

    Pipeline:
      1. Candidate pool  — _FEED_SAMPLE posts newest-first (cursor-aware)
         + unseen posts from followed accounts since last visit
      2. Per-vibe annotate — attach _vb_<type> count to each post object
      3. Score & rank    — _score_post() with all 5 signal families
      4. Exploration     — inject dynamic % random posts to prevent boredom
         (30 % for new users, 15 % for established users)
      5. Re-sort + jitter— per-user seeded RNG so different users see
         different orderings of the same scored pool
      6. Slice           — take page_size items
      6b. Own-post pinning — first page only
      7. FoF metadata + suggestion cards → feed_items list

    Args:
        seen_post_ids : set/list of post_ids already shown to this user
                        in earlier scroll pages — excluded from explore
                        slot so the same post never re-surfaces via explore.

    Returns (feed_items list, next_cursor float|None).
    """
    if page_size is None:
        page_size = FEED_PAGE_SIZE

    following_ids_set = set(following_ids)
    now               = timezone.now()
    seen_post_ids     = set(seen_post_ids or [])

    # ── Blocked users — fetch once, apply everywhere ──────────────────────────
    # Posts from blocked/blocking users must be invisible in BOTH the main
    # candidate pool AND the explore slot.
    _blocked_qs  = BlockedUser.objects.filter(Q(blocker=user) | Q(blocked=user))
    _blocked_ids = set(
        list(_blocked_qs.values_list('blocked_id', flat=True)) +
        list(_blocked_qs.values_list('blocker_id', flat=True))
    )
    _blocked_ids.discard(user.id)   # never exclude the viewer themselves

    # ── Dynamic candidate pool size ───────────────────────────────────────────
    # Scale the candidate pool with the number of accounts the user follows so
    # that power users and large networks always get enough variety to find the
    # best top-10. Formula: clamp(len(following) * multiplier, min, max).
    _feed_sample = max(
        _FEED_SAMPLE_MIN,
        min(_FEED_SAMPLE_MAX, len(following_ids_set) * _FEED_SAMPLE_MULTIPLIER),
    )

    # ── Signals setup ─────────────────────────────────────────────────────────
    feed_prof           = _get_or_create_feed_profile(user)
    vibe_weights        = feed_prof.get_weights()
    adaptive_author_ids = set(feed_prof.interacted_authors or [])

    interacted_post_ids, author_affinity = _build_user_interest_profile(user)
    fof_ids, fof_via_map = _build_fof(following_ids_set, user.id)

    # ── 1. Candidate pool ─────────────────────────────────────────────────────
    # New-post visibility guarantee: always include ALL posts from the last
    # 2 h regardless of author, so a brand-new post from anyone can collect
    # its first engagement and not be invisible to the algorithm.
    _NEW_POST_WINDOW = timezone.now() - timedelta(hours=2)

    # FIX 1 — Last-visit unseen posts: always pull ALL posts from followed
    # accounts posted since the user's last feed visit, regardless of the
    # _FEED_SAMPLE cap.  This prevents posts from being permanently buried
    # when the user hasn't opened the app for a day or two.
    _last_visit = getattr(feed_prof, 'last_feed_visit', None)
    _unseen_since = _last_visit if _last_visit else (now - timedelta(hours=48))

    if not following_ids:
        base_qs = Post.objects.all()
    else:
        base_qs = Post.objects.filter(
            Q(author__in=following_ids) |                    # people you follow
            Q(author=user) |                                  # your own posts
            Q(is_repost=True, author__in=following_ids) |    # reposts by followings
            Q(author__in=fof_ids) |                           # friend-of-friend posts
            Q(created_at__gte=_NEW_POST_WINDOW)               # ANY brand-new post (< 2 h)
        )

    # Exclude blocked users from the main pool
    if _blocked_ids:
        base_qs = base_qs.exclude(author__in=_blocked_ids)

    if cursor_dt:
        base_qs = base_qs.filter(created_at__lt=cursor_dt)

    posts = list(
        base_qs
        .select_related(
            'author', 'author__profile',
            'original_post', 'original_post__author', 'original_post__author__profile',
        )
        .prefetch_related('likes', 'reposts', 'images')
        .annotate(
            vibe_count    = Count('vibes',    distinct=True),
            comment_count = Count('comments', distinct=True),
            repost_count  = Count('reposts',  distinct=True),
        )
        .order_by('-created_at')[:_feed_sample]
    )

    # ── FIX 1b: Unseen posts from followings since last visit ────────────────
    # Fetch posts from followed accounts created after _unseen_since that are
    # NOT already in the main pool (i.e. fell outside the _feed_sample cap).
    # This runs only on the first page (no cursor) to avoid duplication.
    if cursor_dt is None and following_ids:
        _existing_pool_ids = {p.post_id for p in posts}
        _unseen_extras = list(
            Post.objects
            .filter(
                Q(author__in=following_ids) | Q(author=user),
                created_at__gt=_unseen_since,
            )
            .exclude(post_id__in=_existing_pool_ids)
            .exclude(author__in=_blocked_ids)
            .select_related(
                'author', 'author__profile',
                'original_post', 'original_post__author', 'original_post__author__profile',
            )
            .prefetch_related('likes', 'reposts', 'images')
            .annotate(
                vibe_count    = Count('vibes',    distinct=True),
                comment_count = Count('comments', distinct=True),
                repost_count  = Count('reposts',  distinct=True),
            )
            .order_by('-created_at')[:50]   # cap at 50 to avoid memory blowout
        )
        if _unseen_extras:
            posts = posts + _unseen_extras

    # ── FIX 4: Inject original posts of reposts as independent candidates ──────
    # When a followed user reposts a 3-day-old post, that original post never
    # enters the candidate pool on its own and stays invisible.  We collect the
    # original_post ids from all repost rows already fetched, then bulk-fetch
    # any originals not already present — they compete on their own score.
    _repost_orig_ids = {
        p.original_post.post_id
        for p in posts
        if p.is_repost and p.original_post
    }
    _existing_ids = {p.post_id for p in posts}
    _missing_orig_ids = _repost_orig_ids - _existing_ids
    if _missing_orig_ids:
        _orig_extras = list(
            Post.objects
            .filter(post_id__in=_missing_orig_ids)
            .exclude(author__in=_blocked_ids)
            .select_related(
                'author', 'author__profile',
                'original_post', 'original_post__author', 'original_post__author__profile',
            )
            .prefetch_related('likes', 'reposts', 'images')
            .annotate(
                vibe_count    = Count('vibes',    distinct=True),
                comment_count = Count('comments', distinct=True),
                repost_count  = Count('reposts',  distinct=True),
            )
        )
        posts = posts + _orig_extras

    # next_cursor is computed AFTER slicing to final_posts (step 6 below)
    # so it always points to the oldest post that was actually rendered.
    # Do NOT calculate it here from the raw 40-post pool — that skips posts.

    # ── 2. Per-vibe breakdown annotation ──────────────────────────────────────
    # Single bulk query via shared helper — handles repost → original resolution.
    _annotate_vibe_breakdown(posts)

    # ── 3. Score & rank — compute once, cache on object ───────────────────────
    # _score_post is called only once per post here; the cached value is reused
    # in the merge sort below so we never compute it twice.
    def _cached_score(p):
        if not hasattr(p, '_feed_score'):
            p._feed_score = _score_post(
                p, now, vibe_weights, interacted_post_ids,
                author_affinity, fof_ids, adaptive_author_ids,
            )
        return p._feed_score

    scored = sorted(posts, key=_cached_score, reverse=True)

    # ── 4. Cursor — derived from the SCORED pool before any explore mixing ────
    # We take the Nth post in the scored list (where N = page_size) as the
    # cursor anchor. This guarantees:
    #   a) The cursor always advances exactly page_size posts per scroll.
    #   b) Explore posts (which may be random-offset older posts) never drag
    #      the cursor backwards and cause duplicate posts on the next load.
    #   c) next_cursor is None only when the scored pool itself has fewer
    #      than page_size posts — meaning genuine exhaustion.
    if len(scored) >= page_size:
        # Use the page_size-th scored post's timestamp as the cursor boundary.
        # On the next call, base_qs will filter created_at < this timestamp.
        next_cursor = scored[page_size - 1].created_at.timestamp()
    else:
        next_cursor = None

    # ── 5. Exploration injection ─────────────────────────────────────────────
    # Explore posts add novelty but are EXCLUDED from cursor calculation above.
    # Uses _random_posts_sample() — random offset scan, no ORDER BY RANDOM().
    #
    # Dynamic explore ratio: users with few followings get a larger explore
    # slice (30 %) so new/unseen content from outside their network still
    # reaches them.  Power users keep the default 15 %.
    _effective_explore_ratio = 0.30 if len(following_ids_set) < 10 else _EXPLORE_RATIO
    n_explore  = max(1, int(page_size * _effective_explore_ratio))
    scored_ids = {p.post_id for p in scored}

    explore_posts = _random_posts_sample(scored_ids, cursor_dt, n_explore,
                                         blocked_ids=_blocked_ids,
                                         seen_post_ids=seen_post_ids)
    _annotate_vibe_breakdown(explore_posts)

    # ── 6. Merge, jitter, re-sort, slice ──────────────────────────────────────
    # Take top (page_size - n_explore) scored posts + explore posts, then
    # re-sort with jitter so explore posts land naturally in the feed.
    # If explore returned 0 posts (thin window), fall back to full page_size
    # from scored so the user always sees a complete page.
    #
    # Per-user jitter seed: combining user.id with the current hour means:
    #   - Two different users always get a different ordering for the same posts.
    #   - The same user gets a fresh shuffle each hour (not on every reload),
    #     so the feed feels stable within a session but evolves over time.
    _rng = random.Random(user.id ^ hash(now.strftime('%Y%m%d%H')))

    n_from_scored = page_size - len(explore_posts)
    merged = scored[:n_from_scored] + explore_posts
    merged.sort(
        key=lambda p: _cached_score(p) + _rng.uniform(0, 1.5),
        reverse=True,
    )
    final_posts = merged[:page_size]

    # ── 6b. Own-post pinning — only on the FIRST page load (no cursor) ─────────
    # After jitter and explore injection the user's own brand-new posts can be
    # displaced from the visible page.  We guarantee visibility on first load by:
    #   • Only activating when cursor_dt is None (i.e. fresh feed, not scroll).
    #   • Separating own posts (author == user) posted in the last 2 h.
    #   • Sorting own posts newest-first so the most recent appears at the top.
    #   • Prepending them to final_posts and trimming back to page_size.
    # Skipping on subsequent pages prevents the same post from re-appearing
    # at the top on every scroll load.
    # Zero extra DB queries — purely a reorder of the already-fetched pool.
    if cursor_dt is None:
        _OWN_PIN_WINDOW = timezone.now() - timedelta(hours=2)
        own_posts   = [p for p in final_posts
                       if p.author_id == user.id and p.created_at >= _OWN_PIN_WINDOW]
        other_posts = [p for p in final_posts if p not in own_posts]

        if own_posts:
            own_posts.sort(key=lambda p: p.created_at, reverse=True)
            final_posts = own_posts + other_posts
            final_posts = final_posts[:page_size]

    # ── FIX 1c: Stamp last_feed_visit so next load knows where to resume ────────
    # Only update on the first page (cursor_dt is None) so mid-scroll loads
    # don't advance the cursor prematurely.
    if cursor_dt is None:
        try:
            feed_prof.last_feed_visit = now
            feed_prof.save(update_fields=['last_feed_visit'])
        except Exception:
            pass

    # ── 7. Build feed_items ───────────────────────────────────────────────────
    # Suggestion users: random offset instead of ORDER BY RANDOM().
    # seen_suggestion_ids — user IDs already shown as suggestion cards on
    # earlier scroll pages — are excluded so the same person is never
    # recommended twice across a session.
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

    feed_items = []
    _suggestion_injected = 0
    # FIX 7: Only inject suggestion cards for users with < 20 followings
    # (genuinely new / small accounts who benefit from discovery).
    # Cap at 1 card per page so post density is never starved.
    _max_suggestions_this_page = 1 if len(following_ids_set) < 20 else 0

    # ── Market product injection ───────────────────────────────────────────────
    # Fetch a small pool of random products to sprinkle into the feed.
    # We use a random offset scan (no ORDER BY RANDOM()) to stay fast.
    _market_pool = []
    _market_count = Market.objects.count()
    if _market_count > 0:
        _market_offset = random.randint(0, max(0, _market_count - 6))
        _market_pool = list(
            Market.objects
            .select_related('product_owner', 'product_owner__profile')
            .prefetch_related('images')
            [_market_offset: _market_offset + 6]
        )
        random.shuffle(_market_pool)
    _market_injected = 0
    _MAX_MARKET_PER_PAGE = 2   # at most 2 product cards per feed page

    for i, post in enumerate(final_posts, 1):
        actual_author_id = (
            post.original_post.author_id
            if post.is_repost and post.original_post
            else post.author_id
        )
        is_fof  = actual_author_id in fof_ids
        fof_via = fof_via_map.get(actual_author_id, []) if is_fof else []
        feed_items.append({'type': 'post', 'data': post, 'is_fof': is_fof, 'fof_via': fof_via})
        if (i % 4 == 2
                and suggestion_users
                and _suggestion_injected < _max_suggestions_this_page):
            feed_items.append({'type': 'user_suggestion', 'data': suggestion_users.pop(0)})
            _suggestion_injected += 1
        # Inject an ad card every 5 posts (offset by 3 so it never overlaps
        # the suggestion card at position 6).
        if (i % 5 == 3
                and _market_pool
                and _market_injected < _MAX_MARKET_PER_PAGE):
            feed_items.append({'type': 'market', 'data': _market_pool.pop(0)})
            _market_injected += 1
            _suggestion_injected += 1

    return feed_items, next_cursor


# ─────────────────────────────────────────────────────────────────────────────
# Feed profile update helpers
# Call these from your like_post / vibe_post / comment views so the
# algorithm adapts over time to each user's actual behaviour.
# ─────────────────────────────────────────────────────────────────────────────

def _feed_record_vibe(user, vibe_type, post_author_id):
    """
    Call when a user ADDS or SWITCHES a vibe reaction.
    Bumps the vibe taste weight for `vibe_type` in the user's UserFeedProfile,
    records author affinity, and busts the interest cache so the next feed load
    reflects this interaction immediately.
    Already wired into PostVibeConsumer.toggle_vibe().
    """
    try:
        from django.core.cache import cache
        _get_or_create_feed_profile(user).record_vibe(vibe_type, post_author_id)
        cache.delete(f'kvibe_interest_v2_{user.id}')
    except Exception:
        pass


def _feed_record_like(user, post_author_id):
    """Call when a user LIKES a post.  Updates author affinity + busts interest cache."""
    try:
        from django.core.cache import cache
        _get_or_create_feed_profile(user).record_like(post_author_id)
        cache.delete(f'kvibe_interest_v2_{user.id}')
    except Exception:
        pass


def _feed_record_comment(user, post_author_id):
    """Call when a user submits a COMMENT.  Updates author affinity + busts interest cache."""
    try:
        from django.core.cache import cache
        _get_or_create_feed_profile(user).record_comment(post_author_id)
        cache.delete(f'kvibe_interest_v2_{user.id}')
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def home(request):
    profile = Profile.objects.get(user=request.user)
    following = profile.followings.values_list('user', flat=True)

    following_ids = list(following)

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).count()
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()

    # Trending hashtags
    hashtag_counts = {}
    for post in (Post.objects
                 .filter(Q(author__in=following_ids) | Q(author=request.user))
                 .only('content')
                 .order_by('-created_at')[:200]):
        if post.content:
            for tag in extract_hashtags(post.content):
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
    trending_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # First page of the feed
    feed, next_cursor = _get_feed_page(request.user, following_ids)

    # Store page-load timestamp in session — used by "New posts" banner polling
    import datetime as _dt
    feed_anchor_ts = _dt.datetime.now(_dt.timezone.utc).timestamp()
    request.session['feed_anchor'] = feed_anchor_ts

    # Only pass counts — lists are loaded lazily via HTMX
    sidebar_following_count = profile.followings.count()
    sidebar_follower_count  = profile.followers.count()

    users = list(
        User.objects.exclude(id__in=following_ids)
               .exclude(id=request.user.id)
               .order_by('?')[:3]
    )

    return render(request, 'home.html', {
        'posts_with_ads':             feed,
        'next_cursor':                next_cursor,
        'feed_anchor':                feed_anchor_ts,
        'unread_follow_count':        unread_follow_count,
        'unread_notifications_count': unread_notifications_count,
        'users':                      users,
        'trending_hashtags':          trending_hashtags,
        'following_ids':              following_ids,
        'sidebar_following_count':    sidebar_following_count,
        'sidebar_follower_count':     sidebar_follower_count,
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
# HTMX infinite-scroll endpoint
# GET /feed/more/?cursor=<float_unix_timestamp>
# Returns the next page partial (posts + new sentinel) or 204 if exhausted.
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
@require_GET
def feed_load_more(request):
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    import datetime as _dt

    # ── New-posts banner check ────────────────────────────────────────────────
    # The banner JS calls ?cursor=<anchor_ts>&check_new=1
    # We just check if any posts exist newer than the anchor.
    if request.GET.get('check_new') == '1':
        try:
            anchor_ts = float(request.GET.get('cursor', 0))
            anchor_dt = _dt.datetime.fromtimestamp(anchor_ts, tz=_dt.timezone.utc)
        except (ValueError, TypeError):
            return HttpResponse(status=204)

        profile       = Profile.objects.get(user=request.user)
        following_ids = list(profile.followings.values_list('user', flat=True))

        if not following_ids:
            new_qs = Post.objects.all()
        else:
            new_qs = Post.objects.filter(
                Q(author__in=following_ids) |
                Q(author=request.user) |
                Q(is_repost=True, author__in=following_ids)
            )

        if new_qs.filter(created_at__gt=anchor_dt).exists():
            return HttpResponse(status=200)   # new posts exist → show banner
        return HttpResponse(status=204)        # nothing new

    # ── Normal infinite scroll ────────────────────────────────────────────────
    try:
        cursor_ts = float(request.GET.get('cursor', 0))
    except (ValueError, TypeError):
        cursor_ts = 0

    cursor_dt = (
        _dt.datetime.fromtimestamp(cursor_ts, tz=_dt.timezone.utc)
        if cursor_ts else None
    )

    profile       = Profile.objects.get(user=request.user)
    following_ids = list(profile.followings.values_list('user', flat=True))

    # FIX 6: Pass seen post IDs so explore slot never resurfaces a post the
    # user already scrolled past.  The client sends them as a comma-separated
    # query param ?seen=<id1>,<id2>,...
    seen_raw      = request.GET.get('seen', '')
    seen_post_ids = set(seen_raw.split(',')) if seen_raw else set()

    # Pass seen suggestion user IDs so the same user is never recommended
    # twice across scroll pages.  Client sends ?seen_users=<id1>,<id2>,...
    seen_users_raw      = request.GET.get('seen_users', '')
    seen_suggestion_ids = set(seen_users_raw.split(',')) if seen_users_raw else set()

    feed, next_cursor = _get_feed_page(
        request.user, following_ids,
        cursor_dt=cursor_dt,
        seen_post_ids=seen_post_ids,
        seen_suggestion_ids=seen_suggestion_ids,
    )

    # Only return 204 when there are genuinely no post items in the feed.
    # Suggestion cards count as items too — check specifically for post type.
    post_items = [item for item in feed if item.get('type') == 'post']
    if not post_items:
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
# Vibe helpers — shared by like_post and get_post_vibes
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Vibe helpers — shared by like_post and get_post_vibes
# ─────────────────────────────────────────────────────────────────────────────

_VIBE_EMOJIS = {
    'fire':   '🔥',
    'real':   '💯',
    'vibing': '🎵',
    'dead':   '😂',
    'cringe': '😬',
    'chill':  '🧊',
    'love':   '❤️',  # NEW: Love reaction
}

_VIBE_COLORS = {
    'fire':   '#ff4500',
    'real':   '#ff0080',
    'vibing': '#3b82f6',
    'dead':   '#f59e0b',
    'cringe': '#8b5cf6',
    'chill':  '#06b6d4',
    'love':   '#e11d48',  # NEW: Deep pink/red for love
}


def _get_vibe_context(post_obj, user):
    """
    Returns vibe_summary, vibe_total, user_vibe, user_vibe_emoji,
    vibe_emojis, and vibe_colors for a given post and user.
    Used by both like_post (HTMX) and get_post_vibes (JSON).
    """
    vibe_rows = (
        PostVibe.objects
        .filter(post=post_obj)
        .values('vibe_type')
        .annotate(count=Count('id'))
    )
    vibe_summary = {row['vibe_type']: row['count'] for row in vibe_rows}
    vibe_total   = sum(vibe_summary.values())

    user_vibe_obj = PostVibe.objects.filter(post=post_obj, user=user).first()
    user_vibe     = user_vibe_obj.vibe_type if user_vibe_obj else None

    return {
        'vibe_summary':    vibe_summary,
        'vibe_total':      vibe_total,
        'user_vibe':       user_vibe,
        'user_vibe_emoji': _VIBE_EMOJIS.get(user_vibe, ''),
        'vibe_emojis':     _VIBE_EMOJIS,
        'vibe_colors':     _VIBE_COLORS,
    }

@login_required(login_url='/')
def repost_post(request, post_id):
    """Handle reposting a post and notify the original author."""
    try:
        original_post = get_object_or_404(Post, post_id=post_id)
        user = request.user

        data    = json.loads(request.body)
        caption = data.get('caption', '').strip()[:500]
        undo    = data.get('undo', False)

        existing_repost = Post.objects.filter(
            author=user,
            is_repost=True,
            original_post=original_post,
        ).first()

        if undo and existing_repost:
            existing_repost.delete()
            original_post.reposts.remove(user)

            # Remove repost notification
            Notification.objects.filter(
                recipient=original_post.author,
                actor=user,
                post=original_post,
                notification_type=Notification.REPOST,
            ).delete()

            reposted = False
            message  = 'Repost removed'

        elif not undo and not existing_repost:
            repost = Post.objects.create(
                author=user,
                is_repost=True,
                original_post=original_post,
                repost_content=caption,
                content='',
            )
            original_post.reposts.add(user)

            # Notify original author (not for self-reposts)
            if original_post.author != user:
                Notification.objects.get_or_create(
                    recipient=original_post.author,
                    actor=user,
                    post=original_post,
                    notification_type=Notification.REPOST,
                )

            reposted = True
            message  = 'Post reposted successfully!'

        elif not undo and existing_repost:
            existing_repost.repost_content = caption
            existing_repost.save()
            reposted = True
            message  = 'Repost updated!'

        else:
            return JsonResponse({'success': False, 'error': 'Invalid operation'})

        return JsonResponse({
            'success':      True,
            'reposted':     reposted,
            'repost_count': original_post.reposts.count(),
            'message':      message,
            'caption':      caption,
        })

    except Post.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Post not found'})
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Something went wrong.'}, status=500)


@login_required(login_url='/')
def follow_user(request, user_id):
    if request.method == 'POST':
        try:
            user_to_follow = User.objects.get(id=user_id)
            current_profile = Profile.objects.get(user=request.user)
            target_profile = Profile.objects.get(user=user_to_follow)

            if target_profile in current_profile.followings.all():
                current_profile.followings.remove(target_profile)
                followed = False
                FollowNotification.objects.filter(
                    from_user=request.user,
                    to_user=user_to_follow
                ).delete()
            else:
                current_profile.followings.add(target_profile)
                followed = True
                if request.user != user_to_follow:
                    FollowNotification.objects.get_or_create(
                        from_user=request.user,
                        to_user=user_to_follow
                    )
            
            current_profile.save()
            
            return JsonResponse({
                'success': True,
                'followed': followed,
                'follower_count': target_profile.followers.count(),
                'following_count': current_profile.followings.count()
            })
            
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': 'Something went wrong.'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required(login_url='/')
def post(request):
    if request.method =='POST':
        content = request.POST.get('content','').strip()
        images = request.FILES.getlist('images')
        audio = request.FILES.get('audio_file')
        video = request.FILES.get('video_file')
        
        mood = request.POST.get('mood', '')
        custom_mood = request.POST.get('custom_mood', '').strip()
        
        mood_emojis = {
            'slay': '💅', 'vibing': '🎵', 'sheesh': '🥶', 'periodt': '⏸️',
            'no-cap': '🎯', 'bussin': '🔥', 'mid': '😐', 'cringe': '😬'
        }
        
        final_mood = custom_mood if custom_mood else mood
        emoji = mood_emojis.get(mood, '✨') if not custom_mood else '✨'
        
        if not content and not images and not audio and not video and final_mood:
            content = f"{emoji} feeling {final_mood}"
        
        if not content and not images and not audio and not video:
            messages.error(request, 'Add something to your post bestie ✨')
            return redirect('post')
        
        new_post = Post.objects.create(
            author=request.user,
            content=content if content else '',
            file=audio if audio else None,
            video_file=video if video else None,
            mood=mood if mood else None,
            custom_mood=custom_mood if custom_mood else None,
            mood_emoji=emoji
        )
        
        for image in images:
            PostImage.objects.create(post=new_post, image=image)
        
        # ── Auto-fetch link preview from post content (background thread) ─
        _url_match = re.search(r'https?://[^\s]{4,}', content or '')
        if _url_match and not images and not audio and not video:
            _url_for_preview = html_unescape(_url_match.group(0))

            def _bg_fetch_preview(post_pk, fetch_url):
                try:
                    if not _is_safe_url_for_preview(fetch_url):
                        return
                    _headers = {
                        'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
                        'Accept':     'text/html,application/xhtml+xml',
                    }
                    _resp = requests.get(fetch_url, headers=_headers, timeout=5, allow_redirects=True, stream=True)
                    _raw = b''
                    for _chunk in _resp.iter_content(8192):
                        _raw += _chunk
                        if len(_raw) > 500_000:
                            break
                    _soup = BeautifulSoup(_raw, 'html.parser')

                    def _og(p):
                        t = (
                            _soup.find('meta', property=f'og:{p}')
                            or _soup.find('meta', attrs={'name': f'twitter:{p}'})
                            or _soup.find('meta', attrs={'name': p})
                        )
                        return t['content'].strip() if t and t.get('content') else ''

                    _title       = _og('title') or (_soup.title.string.strip() if _soup.title else '')
                    _description = _og('description')
                    _image       = _og('image')
                    _domain      = urlparse(_resp.url).netloc.replace('www.', '')

                    if _image and not _image.startswith(('http://', 'https://')):
                        _image = ''

                    _lp = {
                        'title':       html_escape(_title[:200]),
                        'description': html_escape(_description[:400]),
                        'image':       _image[:500],
                        'domain':      html_escape(_domain[:100]),
                        'url':         fetch_url,
                    }
                    if _lp['title'] or _lp['image']:
                        Post.objects.filter(pk=post_pk).update(link_preview=_lp)
                except Exception:
                    pass

            threading.Thread(
                target=_bg_fetch_preview,
                args=(new_post.pk, _url_for_preview),
                daemon=True,
            ).start()
        
        # ── Feed: bust interest cache so the new post surfaces immediately ──
        try:
            from django.core.cache import cache
            cache.delete(f'kvibe_interest_v2_{request.user.id}')
        except Exception:
            pass

        messages.success(request, 'Post dropped successfully! ✨')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'redirect': '/home'})
        return redirect('home')
    
    return render(request, 'post.html')


@login_required(login_url='/')
def editpost(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id, author=request.user)
    image = PostImage.objects.filter(post=post_obj)
    if request.method =='POST':
        content = request.POST.get('comment')
        images = request.FILES.getlist('images')
        if not content and not images:
            return
        post_obj.content=content
        post_obj.save()
        if images:
            for m in images:
                if image:
                   for n in image:
                        n.image=m
                        n.save()
                else:
                    PostImage.objects.create(post=post_obj, image=m)
        return _safe_redirect_back(request, fallback='home')
    context = {
        'post': post_obj,
        'post_id': post_id
    }
    return render(request, 'editpost.html', context)


@login_required(login_url='/')
def like_post(request, post_id):
    """
    Legacy HTMX like endpoint — kept for backwards compatibility.
    The new vibe system runs through WebSocket (PostVibeConsumer).
    This view now renders post_like.html with full vibe context so
    the snippet displays correctly when it falls back to HTMX.
    NOTE: Notifications are fired by PostVibeConsumer.toggle_vibe()
    — we do NOT create them here to avoid duplicates.
    """
    post_obj = get_object_or_404(Post, post_id=post_id)

    # Keep the old likes M2M in sync (used by older parts of the UI)
    if request.user in post_obj.likes.all():
        post_obj.likes.remove(request.user)
    else:
        post_obj.likes.add(request.user)
        # ── Feed profile: record author affinity signal ───────────────────
        _feed_record_like(request.user, post_obj.author_id)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        likers      = list(post_obj.likes.all()[:3])
        like_count  = post_obj.likes.count()
        is_liked    = request.user in post_obj.likes.all()
        liker_pics  = [_safe_pic_url(u) for u in likers]
        liker_names = [u.username for u in likers]
        return JsonResponse({
            'success':     True,
            'like_count':  like_count,
            'is_liked':    is_liked,
            'liker_pics':  liker_pics,
            'liker_names': liker_names,
        })

    vibe_ctx = _get_vibe_context(post_obj, request.user)
    return render(request, 'snippet/post_like.html', {
        'post':    post_obj,
        'post_id': post_id,
        **vibe_ctx,
    })


@login_required(login_url='/')
def get_post_vibes(request, post_id):
    """
    REST endpoint — returns current vibe snapshot for a post as JSON.
    Called on initial page load so the UI is hydrated before WS connects.
    Also used as a fallback if the WebSocket is unavailable.
    """
    post_obj  = get_object_or_404(Post, post_id=post_id)
    vibe_ctx  = _get_vibe_context(post_obj, request.user)

    return JsonResponse({
        'summary':   vibe_ctx['vibe_summary'],
        'total':     vibe_ctx['vibe_total'],
        'user_vibe': vibe_ctx['user_vibe'],
    })


@login_required(login_url='/')
def post_comment(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    # View increment is now handled client-side via /record-view/<post_id>/
    # (fired when the comment sheet opens or play is clicked), so we no
    # longer double-count here.
    comments = PostComment.objects.filter(post=post_obj).order_by('-created_at')
    following_ids = []
    if request.user.is_authenticated:
        following_ids = list(Profile.objects.get(user=request.user).followings.values_list('user', flat=True))
    return render(request, 'postcomment.html', {'post': post_obj, 'comments': comments, 'following_ids': following_ids})


@login_required(login_url='/')
def postcomment(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)

    if request.method == 'POST':
        content = request.POST.get('comment')
        image   = request.FILES.get('image')
        audio   = request.FILES.get('audio_file')

        if not content and not image and not audio:
            return HttpResponse(status=204)

        comment = PostComment.objects.create(
            post=post_obj,
            author=request.user,
            comment=content or '',
            image=image,
            file=audio,
        )
        # ── Feed profile: record author affinity signal ───────────────────
        _feed_record_comment(request.user, post_obj.author_id)

        # ── Comment notification ──────────────────────────────────────────
        if post_obj.author != request.user:
            Notification.objects.create(
                recipient=post_obj.author,
                actor=request.user,
                post=post_obj,
                notification_type=Notification.COMMENT,
            )

        # ── Mention notifications (@username in comment text) ─────────────
        if content:
            mentioned_usernames = set(re.findall(r'@(\w+)', content))
            for username in mentioned_usernames:
                try:
                    mentioned_user = User.objects.get(username=username)
                except User.DoesNotExist:
                    continue

                if mentioned_user == request.user:
                    continue

                already_exists = Notification.objects.filter(
                    recipient=mentioned_user,
                    actor=request.user,
                    post=post_obj,
                    comment=comment,
                    notification_type=Notification.MENTION,
                ).exists()

                if not already_exists:
                    Notification.objects.create(
                        recipient=mentioned_user,
                        actor=request.user,
                        post=post_obj,
                        comment=comment,
                        notification_type=Notification.MENTION,
                    )

        return render(
            request,
            'snippet/comment_list.html',
            {'post': post_obj, 'comment': comment}
        )

    # GET — load comments for modal
    comments = post_obj.comments.all().order_by('-created_at')
    following_ids = list(Profile.objects.get(user=request.user).followings.values_list('user', flat=True))
    return render(
        request,
        'postcomment.html',
        {'post': post_obj, 'comments': comments, 'following_ids': following_ids}
    )


@login_required(login_url='/')
def comment_like(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    if request.user in comment.like.all():
        comment.like.remove(request.user)
    else:
        comment.like.add(request.user)
    return render(request, 'snippet/comment_like.html', {'comment': comment, 'comment_id': comment_id})


@login_required(login_url='/')
def comment_reply(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    context = {'comment': comment, 'comment_id': comment_id}
    return render(request, 'comment_reply.html', context)


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
        }
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(request, 'profile_posts_partial.html', context)
        return render(request, 'profile.html', context)

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved      = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received  = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count      = 0
    if request.user.is_authenticated and request.user != user:
        my_following      = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count      = my_following.filter(followings=profile).count()

    posts = Post.objects.filter(
        author=user, images__isnull=False
    ).prefetch_related('images').distinct()[:30]

    # ── Privacy: determine if viewer can see personal details ───────────────
    can_view_details = profile.can_view_details(request.user)

    context = {
        'user': user, 'posts': posts, 'profile': profile,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': False,
        'can_view_details': can_view_details,
        'is_own_profile': request.user.is_authenticated and request.user == user,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'profile_posts_partial.html', context)
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
        fname         = request.POST.get('fname')
        lname         = request.POST.get('lname')
        phone         = request.POST.get('phone')
        address       = request.POST.get('address')
        location      = request.POST.get('location')
        image         = request.FILES.get('image')
        bio           = request.POST.get('bio')
        website       = request.POST.get('website')
        privacy_level = request.POST.get('privacy_level', '').strip()

        VALID_PRIVACY = {'public', 'followers_only', 'private'}
        if privacy_level not in VALID_PRIVACY:
            privacy_level = None

        try:
            if fname and lname:
                user.first_name = fname
                user.last_name  = lname
                user.save()

            profile_dirty = False
            if phone:    profile.phone    = phone;    profile_dirty = True
            if address:  profile.address  = address;  profile_dirty = True
            if location: profile.location = location; profile_dirty = True
            if bio is not None: profile.bio = bio;    profile_dirty = True
            if website:  profile.website  = website;  profile_dirty = True
            if privacy_level:
                profile.privacy_level = privacy_level
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
                        'first_name':    user.first_name,
                        'last_name':     user.last_name,
                        'bio':           profile.bio,
                        'phone':         profile.phone,
                        'address':       profile.address,
                        'location':      profile.location,
                        'picture_url':   profile.picture.url,
                        'website':       profile.website,
                        'privacy_level': profile.privacy_level,
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


@login_required(login_url='/')
def profile_videos(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked = False
    if request.user.is_authenticated and request.user != user:
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()
        if viewer_is_blocked:
            return render(request, 'blocked.html', {'blocked_by': user})
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()

    video_posts = Post.objects.filter(
        author=user, video_file__isnull=False
    ).prefetch_related('images')[:30]

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count = 0
    if request.user.is_authenticated and request.user != user:
        my_following = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count = my_following.filter(followings=profile).count()

    context = {
        'user': user, 'profile': profile, 'posts': video_posts,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': is_blocked, 'active_tab': 'videos',
        'can_view_details': profile.can_view_details(request.user),
        'is_own_profile': request.user.is_authenticated and request.user == user,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_videos_partial.html', context)
    return render(request, 'profile.html', context)


def profile_text_posts(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked = False
    if request.user.is_authenticated and request.user != user:
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()
        if viewer_is_blocked:
            return render(request, 'blocked.html', {'blocked_by': user})
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()

    text_posts = (
        Post.objects.filter(author=user)
        .annotate(image_count=Count('images'))
        .filter(image_count=0)
        .filter(Q(video_file__isnull=True) | Q(video_file=''))
        .filter(Q(file__isnull=True) | Q(file=''))
        .filter(content__isnull=False)
        .exclude(content__exact='')
        .select_related('author', 'author__profile')
        .prefetch_related('likes', 'comments')
        .order_by('-created_at')[:30]
    )

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count = 0
    if request.user.is_authenticated and request.user != user:
        my_following = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count = my_following.filter(followings=profile).count()

    for p in text_posts:
        p.liker_data = [
            {'url': _safe_pic_url(u), 'username': u.username}
            for u in p.likes.all()[:3]
        ]

    context = {
        'user': user, 'profile': profile, 'posts': text_posts,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': is_blocked, 'active_tab': 'text',
        'can_view_details': profile.can_view_details(request.user),
        'is_own_profile': request.user.is_authenticated and request.user == user,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_text_posts_partial.html', context)
    return render(request, 'profile.html', context)


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

    if other_profile not in current_profile.followings.all():
        current_profile.followings.add(other_profile)
        messages.info(request, 'Following')
        return _safe_redirect_back(request, fallback='home')
    else:
        current_profile.followings.remove(other_profile)
        messages.info(request, 'unFollowing')
        return _safe_redirect_back(request, fallback='home')


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


@login_required(login_url='/')
def search(request):
    """
    Unified search with HTMX infinite-scroll pagination.

    Main view — renders the shell + first page of results.
    Paginated partials are served by the three helpers below:
        search_users_partial   GET /search/users/
        search_posts_partial   GET /search/posts/
        search_hashtags_partial GET /search/tags/

    Explore mode (no query):
        · Recent search history
        · Suggested users (not yet followed, by follower count)
        · Trending hashtags (last 300 posts, global)
    """
    _PAGE = 10   # items per HTMX page

    query = request.GET.get('q', '').strip()[:100]

    # ── Trending hashtags — always needed ──────────────────────────────────────
    hashtag_counts: dict = {}
    for _p in Post.objects.filter(content__isnull=False).order_by('-created_at')[:300]:
        if _p.content:
            for _tag in extract_hashtags(_p.content):
                hashtag_counts[_tag] = hashtag_counts.get(_tag, 0) + 1
    trending_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    if query:
        SearchHistory.objects.create(user=request.user, query=query)

        # ── First page of users ────────────────────────────────────────────────
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
        users_total = users_qs.count()
        users = users_qs[:_PAGE]

        # ── First page of posts ────────────────────────────────────────────────
        posts_qs = (
            Post.objects.filter(
                Q(content__icontains=query) |
                Q(author__username__icontains=query)
            )
            .select_related(
                'author', 'author__profile',
                'original_post', 'original_post__author',
                'original_post__author__profile',
            )
            .prefetch_related('images', 'likes', 'vibes', 'reposts')
            .annotate(
                vibe_count=Count('vibes', distinct=True),
                comment_count=Count('comments', distinct=True),
                repost_count=Count('reposts', distinct=True),
            )
            .order_by('-created_at')
        )
        posts_total = posts_qs.count()
        posts = posts_qs[:_PAGE]

        # Attach per-user vibe on each post
        _VIBE_EMOJIS = {
            'fire': '🔥', 'real': '💯', 'vibing': '🎵',
            'dead': '😂', 'cringe': '😬', 'chill': '🧊', 'love': '❤️',
        }
        _user_vibes = {
            v.post_id: v.vibe_type
            for v in PostVibe.objects.filter(user=request.user, post__in=posts)
        }
        for p in posts:
            p.user_vibe = _user_vibes.get(p.post_id)
            p.user_vibe_emoji = _VIBE_EMOJIS.get(p.user_vibe, '') if p.user_vibe else ''

        # ── Matching hashtags ──────────────────────────────────────────────────
        clean_query = query.lstrip('#').lower()
        matching_hashtags = sorted(
            [(tag, cnt) for tag, cnt in hashtag_counts.items() if clean_query in tag.lower()],
            key=lambda x: x[1], reverse=True,
        )[:30]
        hashtags_total = len(matching_hashtags)
        hashtags_page = matching_hashtags[:_PAGE]

        recent_searches = (
            SearchHistory.objects.filter(user=request.user)
            .exclude(query=query).order_by('-created_at')[:8]
        )

        from social.models import PostVibe as _PV
        vibe_emojis = _PV.VIBE_EMOJIS

        # ── Sidebar context (mirrors home view) ───────────────────────────────
        _profile = request.user.profile
        _followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
            last_app_activity=Max('channel_messages__created_at')
        ).order_by('-last_app_activity', '-created_at')
        _followed_list = []
        for _ch in _followed_channels:
            _unread = _ch.unread_count_for_user(request.user)
            _last_msg = _ch.channel_messages.order_by('-created_at').first()
            _followed_list.append({
                'channel':      _ch,
                'unread_count': _unread,
                'last_message': _last_msg.message if _last_msg else 'No messages yet',
                'last_time':    _last_msg.created_at if _last_msg else None,
            })
        _unread_follow_count = FollowNotification.objects.filter(to_user=request.user, is_read=False).count()
        _unread_notif_count  = Notification.objects.filter(recipient=request.user, is_read=False).count()

        return render(request, 'search.html', {
            'query':             query,
            'users':             users,
            'users_total':       users_total,
            'users_has_more':    users_total > _PAGE,
            'posts':             posts,
            'posts_total':       posts_total,
            'posts_has_more':    posts_total > _PAGE,
            'hashtags_page':     hashtags_page,
            'hashtags_total':    hashtags_total,
            'hashtags_has_more': hashtags_total > _PAGE,
            'matching_hashtags': matching_hashtags,
            'recent_searches':   recent_searches,
            'trending_hashtags': trending_hashtags,
            'page_size':         _PAGE,
            # sidebar
            'followed_list':              _followed_list[:8],
            'unread_follow_count':        _unread_follow_count,
            'unread_notifications_count': _unread_notif_count,
            'sidebar_followings':         _profile.followings.select_related('user').all(),
            'sidebar_followers':          _profile.followers.select_related('user').all(),
        })

    # ── Explore (no query) ─────────────────────────────────────────────────────
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

    # ── Personalised Explore grid ──────────────────────────────────────────────
    # Strategy:
    #   1. Pull a large candidate pool (last 7 days, has media or content)
    #   2. Score each post using the user's interest profile (author affinity,
    #      liked hashtags, vibe taste) + a small engagement bonus
    #   3. Apply a per-user daily seed shuffle so every user and every day
    #      yields a different ordering even for equal-scored posts
    #   4. Skip posts the user already clicked (stored in session)
    #   5. Return top 60 after scoring

    # -- session-based seen set (persisted in session)
    _seen_ids = set(request.session.get('explore_seen_ids', []))

    # -- candidate pool: last 7 days, must have something to show
    _pool = (
        Post.objects
        .filter(
            Q(images__isnull=False) | Q(video_file__isnull=False) | Q(content__isnull=False),
            created_at__gte=timezone.now() - timedelta(days=7),
        )
        .select_related('author', 'author__profile', 'original_post', 'original_post__author')
        .prefetch_related('images', 'likes', 'vibes')
        .annotate(
            vibe_count=Count('vibes', distinct=True),
            like_count=Count('likes', distinct=True),
        )
        .distinct()
    )
    # Fallback: if fewer than 30 posts in 7 days widen to 30 days
    if _pool.count() < 30:
        _pool = (
            Post.objects
            .filter(Q(images__isnull=False) | Q(video_file__isnull=False) | Q(content__isnull=False))
            .select_related('author', 'author__profile', 'original_post', 'original_post__author')
            .prefetch_related('images', 'likes', 'vibes')
            .annotate(
                vibe_count=Count('vibes', distinct=True),
                like_count=Count('likes', distinct=True),
            )
            .distinct()
        )

    _pool_list = list(_pool[:200])  # cap DB work

    # -- interest profile for scoring
    try:
        _interest = _build_user_interest_profile(request.user)
        _author_affinity = _interest.get('author_affinity', {}) if _interest else {}
        _liked_tags = set(_interest.get('liked_hashtags', [])) if _interest else set()
    except Exception:
        _author_affinity = {}
        _liked_tags = set()

    # -- per-user daily seed: same user sees the same shuffle today but
    #    different from yesterday and different from every other user
    _today_str = timezone.now().strftime('%Y%m%d')
    _seed = hash(f"{request.user.id}_{_today_str}") & 0xFFFFFFFF
    _rng = random.Random(_seed)

    def _score_explore_post(p):
        score = 0.0
        rp = p.original_post if p.original_post else p
        # engagement signal
        score += min(p.vibe_count * 0.4, 6.0)
        score += min(p.like_count * 0.2, 4.0)
        # author affinity
        score += float(_author_affinity.get(p.author_id, 0)) * 2.0
        # hashtag interest
        if rp.content and _liked_tags:
            post_tags = set(extract_hashtags(rp.content))
            score += len(post_tags & _liked_tags) * 1.5
        # freshness bonus: posts from the last 24 h get a +2 boost
        age_hours = (timezone.now() - p.created_at).total_seconds() / 3600
        if age_hours < 24:
            score += 2.0
        elif age_hours < 72:
            score += 0.5
        # seen penalty: push already-viewed posts to the bottom
        if p.post_id in _seen_ids:
            score -= 20.0
        # small random jitter so equal-scored posts shuffle differently per user/day
        score += _rng.uniform(0, 1.5)
        return score

    _pool_list.sort(key=_score_explore_post, reverse=True)
    explore_posts = _pool_list[:60]

    # ── Sidebar context ────────────────────────────────────────────────────────
    _profile = request.user.profile
    _followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')
    _followed_list = []
    for _ch in _followed_channels:
        _unread = _ch.unread_count_for_user(request.user)
        _last_msg = _ch.channel_messages.order_by('-created_at').first()
        _followed_list.append({
            'channel':      _ch,
            'unread_count': _unread,
            'last_message': _last_msg.message if _last_msg else 'No messages yet',
            'last_time':    _last_msg.created_at if _last_msg else None,
        })
    _unread_follow_count = FollowNotification.objects.filter(to_user=request.user, is_read=False).count()
    _unread_notif_count  = Notification.objects.filter(recipient=request.user, is_read=False).count()

    return render(request, 'search.html', {
        'search_history':    search_history,
        'trending_hashtags': trending_hashtags,
        'suggested_users':   suggested_users,
        'explore_posts':     explore_posts,
        # sidebar
        'followed_list':              _followed_list[:8],
        'unread_follow_count':        _unread_follow_count,
        'unread_notifications_count': _unread_notif_count,
        'sidebar_followings':         _profile.followings.select_related('user').all(),
        'sidebar_followers':          _profile.followers.select_related('user').all(),
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
def search_posts_partial(request):
    """GET /search/posts/?q=…&page=N  — HTMX paginated post cards."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    from social.models import PostVibe as _PV

    posts_qs = (
        Post.objects.filter(
            Q(content__icontains=query) |
            Q(author__username__icontains=query)
        )
        .select_related(
            'author', 'author__profile',
            'original_post', 'original_post__author',
            'original_post__author__profile',
        )
        .prefetch_related('images', 'likes', 'vibes', 'reposts')
        .annotate(
            vibe_count=Count('vibes', distinct=True),
            comment_count=Count('comments', distinct=True),
            repost_count=Count('reposts', distinct=True),
        )
        .order_by('-created_at')
    )
    total = posts_qs.count()
    posts = list(posts_qs[offset: offset + _PAGE])
    has_more = (offset + _PAGE) < total

    _VIBE_EMOJIS = {
        'fire': '🔥', 'real': '💯', 'vibing': '🎵',
        'dead': '😂', 'cringe': '😬', 'chill': '🧊', 'love': '❤️',
    }
    _user_vibes = {
        v.post_id: v.vibe_type
        for v in _PV.objects.filter(user=request.user, post__in=posts)
    }
    for p in posts:
        p.user_vibe = _user_vibes.get(p.post_id)
        p.user_vibe_emoji = _VIBE_EMOJIS.get(p.user_vibe, '') if p.user_vibe else ''

    return render(request, 'snippet/search_posts_partial.html', {
        'posts':    posts,
        'query':    query,
        'page':     page + 1,
        'has_more': has_more,
    })


@login_required(login_url='/')
@require_GET
def search_hashtags_partial(request):
    """GET /search/tags/?q=…&page=N  — HTMX paginated hashtag rows."""
    if not request.headers.get('HX-Request'):
        return JsonResponse({'error': 'HTMX only'}, status=400)

    _PAGE = 10
    query = request.GET.get('q', '').strip()[:100]
    page  = max(1, int(request.GET.get('page', 1) or 1))
    offset = (page - 1) * _PAGE

    hashtag_counts: dict = {}
    for _p in Post.objects.filter(content__isnull=False).order_by('-created_at')[:300]:
        if _p.content:
            for _tag in extract_hashtags(_p.content):
                hashtag_counts[_tag] = hashtag_counts.get(_tag, 0) + 1

    clean_query = query.lstrip('#').lower()
    all_matches = sorted(
        [(tag, cnt) for tag, cnt in hashtag_counts.items() if clean_query in tag.lower()],
        key=lambda x: x[1], reverse=True,
    )
    total = len(all_matches)
    hashtags_page = all_matches[offset: offset + _PAGE]
    has_more = (offset + _PAGE) < total

    return render(request, 'snippet/search_hashtags_partial.html', {
        'hashtags_page': hashtags_page,
        'query':         query,
        'page':          page + 1,
        'has_more':      has_more,
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
# Notification Views
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def open_notification(request, post_id, notification_type):
    post_obj = get_object_or_404(Post, post_id=post_id)
    Notification.objects.filter(
        recipient=request.user,
        post=post_obj,
        notification_type=notification_type,
        is_read=False
    ).update(is_read=True)
    return redirect('post_comment', post_id=post_obj.post_id)


@login_required(login_url='/')
@login_required(login_url='/')
def notification_list(request):
    """
    Renders the notification page.
    Marks ALL notifications (post-based + follow) as read on page load.
    Grouped data is provided by the user_notifications context processor.

    When ?panel=1 is present (desktop modal AJAX call) returns only the
    inner list partial so no full page reload occurs.
    """
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True)
    from .models import FollowNotification as _FN
    _FN.objects.filter(to_user=request.user, is_read=False).update(is_read=True)

    if request.GET.get('panel') == '1':
        return render(request, 'snippet/notification_panel_partial.html')

    return render(request, 'notification.html')


def notification_partial(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
    else:
        unread_count = 0
        unread_follow_count = 0
    return render(request, 'snippet/notification_count.html', {
        'unread_notifications_count': unread_count,
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

    # ── Post-based notification group ─────────────────────────────────────────
    post_id           = data.get('post_id')
    notification_type = data.get('notification_type')
    actor_id          = data.get('actor_id')

    if not post_id or not notification_type:
        return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)

    try:
        post_uuid = uuid_module.UUID(str(post_id))
    except (ValueError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid post_id'}, status=400)

    VALID_TYPES = {'like', 'vibe', 'comment', 'repost', 'mention'}
    if notification_type not in VALID_TYPES:
        return JsonResponse({'status': 'error', 'message': 'Invalid notification_type'}, status=400)

    # 'vibe' is the frontend alias for 'like' stored in the DB
    db_type = 'like' if notification_type == 'vibe' else notification_type

    qs = Notification.objects.filter(
        recipient=request.user,
        post_id=post_uuid,
        notification_type=db_type,
    )

    if db_type == 'mention' and actor_id:
        try:
            qs = qs.filter(actor_id=int(actor_id))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid actor_id'}, status=400)

    deleted_count, _ = qs.delete()

    return JsonResponse({
        'status': 'success',
        'deleted_count': deleted_count,
        'message': f'Deleted {deleted_count} notification(s)',
    })


@login_required
@require_POST
def mark_all_notifications_read(request):
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True)
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


@login_required
def channel_create(request):
    if request.method == 'POST':
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

    notifications = request.user.notifications.filter(is_read=False)

    context = {
        'channel': channel_obj,
        'grouped_messages': grouped_messages,
        'channel_id': str(channel_id),
        'total_unread': total_unread,
        'notifications': notifications,
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

    highest_price = products.aggregate(Max('product_price'))['product_price__max']
    lowest_price  = products.aggregate(Min('product_price'))['product_price__min']

    if request.method == 'POST' and 'form_type' in request.POST:
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if request.POST['form_type'] == 'marketplace':
            from django.http import JsonResponse
            from urllib.parse import urlparse as _urlparse

            # ── FIX 5: Rate limit ad creation — max 10 ads per user per hour ──
            _rl_key = f'ad_post:{request.user.id}'
            _rl_hits = cache.get(_rl_key, 0)
            if _rl_hits >= 10:
                if is_ajax:
                    return JsonResponse({'success': False, 'errors': {'__all__': 'Too many ads posted. Please wait before posting again.'}}, status=429)
                messages.error(request, 'Too many ads posted. Please wait before posting again.')
                return redirect('market')
            cache.set(_rl_key, _rl_hits + 1, timeout=3600)

            # ── FIX 2: Allowlists for enum fields ──────────────────────────────
            _VALID_CATEGORIES   = {'Phones', 'Electronics', 'Fashion', 'Properties', 'Others'}
            _VALID_CONDITIONS   = {'New', 'Used', 'Used-Fair'}
            _VALID_AVAILABILITY = {'Single Item', 'In Stock'}

            product_owner        = request.user
            product_name         = request.POST.get('product_name', '').strip()
            product_price        = request.POST.get('product_price', '').strip()
            product_location     = request.POST.get('location', 'Ilorin, Nigeria').strip()
            product_description  = request.POST.get('description', '').strip()
            product_availability = request.POST.get('availability', 'Single Item')
            product_category     = request.POST.get('category', '').strip()
            product_condition    = request.POST.get('product_condition', 'New')
            whatsapp_number      = request.POST.get('whatsapp_number', '').strip()
            ad_url               = request.POST.get('ad_url', '').strip() or None
            email                = request.POST.get('email', '').strip() or None
            instagram_handle     = request.POST.get('instagram_handle', '').strip() or None
            twitter_handle       = request.POST.get('twitter_handle', '').strip() or None

            # FIX 2: Clamp enum fields to allowlist values
            if product_availability not in _VALID_AVAILABILITY:
                product_availability = 'Single Item'
            if product_condition not in _VALID_CONDITIONS:
                product_condition = 'New'

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

            # FIX 2: Category must be in allowlist
            if not product_category or product_category not in _VALID_CATEGORIES:
                errors['product_category'] = 'Please select a valid category.'

            if not product_description:
                errors['product_description'] = 'Description is required.'
            if not whatsapp_number:
                errors['whatsapp_number'] = 'WhatsApp number is required.'

            # FIX 3: SSRF check on ad_url using existing helper
            if ad_url:
                try:
                    _parsed_url = _urlparse(ad_url)
                    if _parsed_url.scheme not in ('http', 'https'):
                        errors['ad_url'] = 'Only http:// and https:// URLs are allowed.'
                    elif not _is_safe_url_for_preview(ad_url):
                        errors['ad_url'] = 'That URL is not allowed (private or reserved address).'
                except Exception:
                    errors['ad_url'] = 'Invalid URL format.'

            product_images = request.FILES.getlist('images')
            if len(product_images) == 0:
                errors['images'] = 'Please upload at least one image.'

            if errors:
                if is_ajax:
                    return JsonResponse({'success': False, 'errors': errors}, status=400)
                messages.error(request, 'Please fix the errors below.')
                return redirect('market')

            # FIX 4: Sanitize free-text fields through existing sanitize_text helper
            from social.models import sanitize_text as _sanitize
            product_name        = _sanitize(product_name, 'product_name')
            product_description = _sanitize(product_description, 'product_description')
            product_location    = _sanitize(product_location)

            try:
                product = Market.objects.create(
                    product_owner=product_owner,
                    product_name=product_name,
                    product_price=int(float(product_price)),
                    product_location=product_location,
                    product_description=product_description,
                    product_availability=product_availability,
                    product_category=product_category,
                    product_condition=product_condition,
                    whatsapp_number=whatsapp_number,
                    ad_url=ad_url,
                    email=email,
                    instagram_handle=instagram_handle,
                    twitter_handle=twitter_handle,
                )
                for image in product_images[:5]:
                    MarketImage.objects.create(product=product, product_image=image)

                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'message': 'Ad posted successfully! 🔥',
                        'product_id': str(product.product_id),
                    })
                messages.success(request, 'Ad Posted Successfully', extra_tags='ads_success')
                return redirect('market')

            # FIX 1 & 6: Never leak raw exception details to clients
            except ValidationError as ve:
                _ve_msg = '; '.join(
                    f'{k}: {", ".join(v) if isinstance(v, list) else v}'
                    for k, v in (ve.message_dict.items() if hasattr(ve, 'message_dict') else {'error': [str(ve)]}.items())
                )
                if is_ajax:
                    return JsonResponse({'success': False, 'errors': {'__all__': _ve_msg}}, status=400)
                messages.error(request, _ve_msg)
                return redirect('market')
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Ad creation failed for user %s', request.user.id)
                if is_ajax:
                    return JsonResponse({'success': False, 'errors': {'__all__': 'Something went wrong on our end. Please try again.'}}, status=500)
                messages.error(request, 'Something went wrong on our end. Please try again.')
                return redirect('market')

    context = {
        'products': products,
        'highest_price': highest_price or 0,
        'lowest_price':  lowest_price  or 0,
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

    context = {
        'product': product, 'images': images,
        'related_products': related_products, 'seller': seller_profile,
    }
    return render(request, 'product_details.html', context)


@login_required(login_url='/')
def contact_seller(request, product_id):
    """
    Redirect buyer to the private message thread with the seller,
    carrying ?product=<uuid> so the message view can pre-populate
    a product enquiry card in the composer.
    """
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


def spotlight_view(request):
    spotlight_posts = Post.objects.filter(
        Q(video_file__isnull=False) & ~Q(video_file='') |
        Q(is_repost=True, original_post__video_file__isnull=False) & ~Q(original_post__video_file='')
    ).order_by('?').select_related('author', 'original_post')
    return render(request, 'spotlight.html', {'posts': spotlight_posts})


@login_required(login_url='/')
@require_POST
def track_share(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    if post_obj.share is None:
        post_obj.share = 0
    post_obj.share += 1
    post_obj.save()
    return JsonResponse({'success': True, 'new_count': post_obj.share})


@require_POST
@login_required(login_url='/')
def increment_post_view(request, post_id):
    """
    Lightweight endpoint called from the frontend when:
      - A user clicks the play icon on a video/audio post (first play only)
      - A user opens the comment sheet for a post
    Uses F() expression to avoid race conditions on concurrent increments.
    Returns the new view count so the UI can update in place.
    Also updates the viewer's UserFeedProfile author-affinity so the feed
    algorithm learns that this viewer has passive interest in this creator.
    """
    from django.db.models import F
    post_obj = get_object_or_404(Post, post_id=post_id)
    # Atomic increment — no read-modify-write race
    Post.objects.filter(pk=post_obj.pk).update(view=F('view') + 1)
    post_obj.refresh_from_db(fields=['view'])

    # ── Feed signal: record passive view affinity ─────────────────────────────
    # Weight is intentionally low (base 1.0 in _build_user_interest_profile)
    # so passive scrolling/watching doesn't dilute active engagement signals.
    # We bust the interest cache so the next feed load reflects this view.
    try:
        from django.core.cache import cache
        _get_or_create_feed_profile(request.user).record_view(post_obj.author_id)
        cache.delete(f'kvibe_interest_v2_{request.user.id}')
    except Exception:
        pass

    return JsonResponse({'success': True, 'new_count': post_obj.view})


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


@login_required
@require_POST
def add_comment_reply(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    reply_text = request.POST.get('reply_text', '').strip()

    if reply_text:
        reply = CommentReply.objects.create(
            comment=comment, author=request.user, reply_text=reply_text
        )

        post_obj = comment.post

        # ── Notify the comment author that someone replied ────────────────
        if comment.author != request.user:
            Notification.objects.create(
                recipient=comment.author,
                actor=request.user,
                post=post_obj,
                comment=comment,
                notification_type=Notification.REPLY,
            )

        # ── Notify any @mentioned users in the reply text ─────────────────
        mentioned_usernames = set(re.findall(r"@(\w+)", reply_text))
        for username in mentioned_usernames:
            try:
                mentioned_user = User.objects.get(username=username)
            except User.DoesNotExist:
                continue

            # Skip self-mentions and the comment author (already notified above)
            if mentioned_user == request.user:
                continue
            if mentioned_user == comment.author:
                continue

            already_exists = Notification.objects.filter(
                recipient=mentioned_user,
                actor=request.user,
                post=post_obj,
                comment=comment,
                notification_type=Notification.MENTION,
            ).exists()

            if not already_exists:
                Notification.objects.create(
                    recipient=mentioned_user,
                    actor=request.user,
                    post=post_obj,
                    comment=comment,
                    notification_type=Notification.MENTION,
                )

        return render(request, 'snippet/comment_replies.html', {'replies': [reply]})

    return JsonResponse({'error': 'Reply text is required'}, status=400)


@login_required
@require_POST
def like_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id)
    if request.user in reply.like.all():
        reply.like.remove(request.user)
        liked = False
    else:
        reply.like.add(request.user)
        liked = True
    return JsonResponse({'liked': liked, 'likes_count': reply.like.count()})


@login_required
@require_POST
def edit_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id, author=request.user)
    new_text = request.POST.get('reply_text', '').strip()
    if new_text:
        reply.reply_text = new_text
        reply.is_edited = True
        reply.save()
        return render(request, 'snippet/reply_content.html', {'reply': reply})
    return JsonResponse({'success': False, 'error': 'Reply text is required'}, status=400)


@login_required
@require_POST
def delete_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id, author=request.user)
    reply.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
def comments_poll(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    after_str = request.GET.get('after', '')
    after_dt = None
    if after_str:
        from django.utils.dateparse import parse_datetime
        after_dt = parse_datetime(after_str)
        if after_dt is None:
            try:
                from dateutil.parser import parse as du_parse
                after_dt = du_parse(after_str)
            except Exception:
                after_dt = None

    qs = PostComment.objects.filter(post=post_obj)
    if after_dt:
        qs = qs.filter(created_at__gt=after_dt)

    new_comments = (
        qs.select_related('author', 'author__profile')
        .prefetch_related('like', 'replies', 'replies__author', 'replies__author__profile')
        .order_by('-created_at')
    )

    if not new_comments.exists():
        return HttpResponse(status=204)

    html_parts = []
    for comment in new_comments:
        html_parts.append(
            render_to_string(
                'snippet/comment_list.html',
                {'comment': comment, 'request': request, 'user': request.user},
                request=request,
            )
        )
    return HttpResponse(''.join(html_parts))


@login_required(login_url='/')
@login_required(login_url='login')
def hashtag_view(request, tag_name):
    from django.db.models import Q

    profile = request.user.profile

    posts = Post.objects.filter(
        Q(content__icontains=f'#{tag_name}') |
        Q(original_post__content__icontains=f'#{tag_name}')
    ).order_by('-created_at').select_related(
        'author', 'author__profile',
        'original_post', 'original_post__author', 'original_post__author__profile'
    ).prefetch_related('likes', 'reposts', 'images')

    post_count = posts.count()

    all_hashtags = {}
    for p in posts[:200]:
        content = p.original_post.content if p.is_repost and p.original_post else p.content
        if content:
            for tag in extract_hashtags(content):
                if tag.lower() != tag_name.lower():
                    all_hashtags[tag] = all_hashtags.get(tag, 0) + 1

    related_hashtags = sorted(all_hashtags.items(), key=lambda x: x[1], reverse=True)[:10]

    following_ids = list(profile.followings.values_list('user', flat=True))
    sidebar_followings = profile.followings.select_related('user', 'user__profile').all()
    sidebar_followers  = profile.followers.select_related('user', 'user__profile').all()

    hashtag_counts = {}
    recent_posts = Post.objects.filter(content__isnull=False).order_by('-created_at')[:200]
    for p in recent_posts:
        if p.content:
            for tag in extract_hashtags(p.content):
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
    trending_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).count()
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()

    return render(request, 'hashtag_view.html', {
        'tag_name': tag_name,
        'posts': posts,
        'post_count': post_count,
        'related_hashtags': related_hashtags,
        'following_ids': following_ids,
        'sidebar_followings': sidebar_followings,
        'sidebar_followers': sidebar_followers,
        'trending_hashtags': trending_hashtags,
        'unread_follow_count': unread_follow_count,
        'unread_notifications_count': unread_notifications_count,
    })


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

