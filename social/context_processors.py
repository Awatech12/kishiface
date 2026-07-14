from .models import Message, FollowNotification, BusinessNotification, Channel
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Max, Q


# Vibe emoji lookup — removed PostVibe references
_VIBE_EMOJIS = {
    'fire':   '🔥',
    'real':   '💯',
    'vibing': '🎵',
    'dead':   '😂',
    'cringe': '😬',
    'chill':  '🧊',
    'love':   '❤️',
}

_VIBE_LABELS = {
    'fire':   'Fire',
    'real':   'Real',
    'vibing': 'Vibing',
    'dead':   'Dead',
    'cringe': 'Cringe',
    'chill':  'Chill',
    'love':   'Love',
}


def unread_count_processor(request):
    if request.user.is_authenticated:
        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
    else:
        unread_count = 0
    return {'unread_count': unread_count}


def information(request):
    return {'name': 'Awatech Digital World'}


def follow_notifications_context(request):
    """
    Lightweight context processor for follow + business-page notifications
    (header badge, etc.). Returns counts + 10 most recent of each.
    """
    if not request.user.is_authenticated:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0,
            'has_follow_notifications': False,
            'has_unread_follows': False,
            'unread_business_count': 0,
            'recent_business_notifications': [],
            'has_unread_business_notifications': False,
            'unread_notifications_total': 0,
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

        unread_business_count = BusinessNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_business_notifications = (
            BusinessNotification.objects
            .filter(to_user=request.user)
            .select_related('actor', 'actor__profile', 'business_page', 'product')
            .order_by('-created_at')[:10]
        )

        return {
            'unread_follow_count':        unread_follow_count,
            'recent_follows':             recent_follows,
            'total_follow_notifications': total_follow_notifications,
            'has_follow_notifications':   total_follow_notifications > 0,
            'has_unread_follows':         unread_follow_count > 0,
            'unread_business_count':              unread_business_count,
            'recent_business_notifications':      recent_business_notifications,
            'has_unread_business_notifications':  unread_business_count > 0,
            'unread_notifications_total':  unread_follow_count + unread_business_count,
        }
    except Exception:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0,
            'has_follow_notifications': False,
            'has_unread_follows': False,
            'unread_business_count': 0,
            'recent_business_notifications': [],
            'has_unread_business_notifications': False,
            'unread_notifications_total': 0,
        }


def channel_unread_processor(request):
    if not request.user.is_authenticated:
        return {'total_followed_unread': 0}
    followed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(c.unread_count_for_user(request.user) for c in followed_channels)
    return {'total_followed_unread': total_unread}