from .models import Message, Notification, FollowNotification, Channel
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Max, Q


def unread_count_processor(request):
    if request.user.is_authenticated:
        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
    else:
        unread_count = 0
    return {'unread_count': unread_count}


def information(request):
    return {'name': 'Awatech Digital World'}


def user_notifications(request):
    """
    Unified notification feed covering:
      like | comment | repost | mention  (Notification table)
      follow                             (FollowNotification table)

    Returns time-bucketed lists: today / this week / earlier.
    Each item is a plain dict so templates need no model imports.
    """
    if not request.user.is_authenticated:
        return {}

    now      = timezone.now()
    today    = now.date()
    week_ago = now - timedelta(days=7)

    all_items = []

    # ── 1a. Post-based notifications (like / comment / repost) ─────────────────
    # Grouped by post + type so "X and 3 others liked your post" works.
    grouped_qs = (
        Notification.objects
        .filter(recipient=request.user)
        .exclude(notification_type='mention')
        .values('post', 'notification_type')
        .annotate(
            total=Count('id'),
            latest_time=Max('created_at'),
            unread_count=Count('id', filter=Q(is_read=False)),
        )
        .order_by('-latest_time')
    )

    for g in grouped_qs:
        latest = (
            Notification.objects
            .filter(
                recipient=request.user,
                post_id=g['post'],
                notification_type=g['notification_type'],
            )
            .select_related('actor', 'actor__profile', 'post')
            .order_by('-created_at')
            .first()
        )
        if not latest:
            continue

        all_items.append({
            'kind':         'post',
            'latest_actor': latest.actor,
            'post':         latest.post,
            'comment':      None,
            'type':         g['notification_type'],
            'others_count': g['total'] - 1,
            'created_at':   latest.created_at,
            'is_read':      g['unread_count'] == 0,
            'group_id':     f"post-{g['post']}-{g['notification_type']}",
        })

    # ── 1b. Mention notifications — grouped by post + actor ──────────────────
    # Each actor who mentions you on a post appears as one row (most recent).
    mention_qs = (
        Notification.objects
        .filter(recipient=request.user, notification_type='mention')
        .values('post', 'actor')
        .annotate(
            total=Count('id'),
            latest_time=Max('created_at'),
            unread_count=Count('id', filter=Q(is_read=False)),
        )
        .order_by('-latest_time')
    )

    for g in mention_qs:
        latest = (
            Notification.objects
            .filter(
                recipient=request.user,
                post_id=g['post'],
                actor_id=g['actor'],
                notification_type='mention',
            )
            .select_related('actor', 'actor__profile', 'post', 'comment')
            .order_by('-created_at')
            .first()
        )
        if not latest:
            continue

        all_items.append({
            'kind':         'post',
            'latest_actor': latest.actor,
            'post':         latest.post,
            'comment':      latest.comment,
            'type':         'mention',
            'others_count': 0,
            'created_at':   latest.created_at,
            'is_read':      g['unread_count'] == 0,
            'group_id':     f"post-{g['post']}-mention-{g['actor']}",
        })

    # ── 2. Follow notifications ───────────────────────────────────────────────
    follow_qs = (
        FollowNotification.objects
        .filter(to_user=request.user)
        .select_related('from_user', 'from_user__profile')
        .order_by('-created_at')
    )

    for fn in follow_qs:
        all_items.append({
            'kind':         'follow',
            'latest_actor': fn.from_user,
            'post':         None,
            'comment':      None,
            'type':         'follow',
            'others_count': 0,
            'created_at':   fn.created_at,
            'is_read':      fn.is_read,
            'follow_id':    fn.pk,
            'group_id':     f"follow-{fn.pk}",
        })

    # ── 3. Sort unified list newest-first ─────────────────────────────────────
    all_items.sort(key=lambda x: x['created_at'], reverse=True)

    # ── 4. Bucket into today / this-week / earlier ────────────────────────────
    today_list   = []
    week_list    = []
    earlier_list = []
    unread_groups_count = 0

    for item in all_items:
        if not item['is_read']:
            unread_groups_count += 1

        dt = item['created_at']
        if dt.date() == today:
            today_list.append(item)
        elif dt >= week_ago:
            week_list.append(item)
        else:
            earlier_list.append(item)

    # Build a set of user IDs the current user is already following.
    # Used in the template to show Follow vs Following on notification items.
    from .models import Profile as _Profile
    try:
        _profile = _Profile.objects.get(user=request.user)
        following_ids = set(_profile.followings.values_list('user', flat=True))
    except _Profile.DoesNotExist:
        following_ids = set()

    return {
        'today_notifications':        today_list,
        'week_notifications':         week_list,
        'earlier_notifications':      earlier_list,
        'unread_notifications_count': unread_groups_count,
        'notif_following_ids':        following_ids,
    }


def follow_notifications_context(request):
    """
    Kept for backward compatibility (header badge, etc.).
    Lightweight — only returns counts + 10 most recent follows.
    """
    if not request.user.is_authenticated:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0,
            'has_follow_notifications': False,
            'has_unread_follows': False,
        }

    try:
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_follows = (
            FollowNotification.objects
            .filter(to_user=request.user)
            .select_related('from_user', 'from_user__profile')
            .order_by('-created_at')[:10]
        )

        total_follow_notifications = FollowNotification.objects.filter(
            to_user=request.user
        ).count()

        return {
            'unread_follow_count':        unread_follow_count,
            'recent_follows':             recent_follows,
            'total_follow_notifications': total_follow_notifications,
            'has_follow_notifications':   total_follow_notifications > 0,
            'has_unread_follows':         unread_follow_count > 0,
        }
    except Exception:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0,
            'has_follow_notifications': False,
            'has_unread_follows': False,
        }


def channel_unread_processor(request):
    if not request.user.is_authenticated:
        return {'total_followed_unread': 0}
    followed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(c.unread_count_for_user(request.user) for c in followed_channels)
    return {'total_followed_unread': total_unread}
