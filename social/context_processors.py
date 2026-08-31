from .models import Message, FollowNotification, ProfilePostNotification, ProfileItemNotification, BusinessNotification, EventNotification, JobApplicationNotification, Channel, BusinessPage, BusinessMessage
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
            'unread_profile_post_count': 0,
            'recent_profile_post_notifications': [],
            'has_unread_profile_post_notifications': False,
            'unread_profile_item_count': 0,
            'recent_profile_item_notifications': [],
            'has_unread_profile_item_notifications': False,
            'unread_business_count': 0,
            'recent_business_notifications': [],
            'has_unread_business_notifications': False,
            'unread_event_count': 0,
            'recent_event_notifications': [],
            'has_unread_event_notifications': False,
            'unread_job_application_count': 0,
            'recent_job_application_notifications': [],
            'has_unread_job_application_notifications': False,
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

        # Reactions + comments on the user's own ProfilePost updates.
        unread_profile_post_count = ProfilePostNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_profile_post_notifications = (
            ProfilePostNotification.objects
            .filter(to_user=request.user)
            .select_related('actor', 'actor__profile', 'post')
            .order_by('-created_at')[:10]
        )

        # Reactions + comments on the user's own Portfolio/Project,
        # Achievement, Experience, Education, and Service items.
        unread_profile_item_count = ProfileItemNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_profile_item_notifications = (
            ProfileItemNotification.objects
            .filter(to_user=request.user)
            .select_related(
                'actor', 'actor__profile',
                'portfolio_item', 'achievement', 'experience', 'education', 'service',
            )
            .order_by('-created_at')[:10]
        )

        unread_business_count = BusinessNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_business_notifications = (
            BusinessNotification.objects
            .filter(to_user=request.user)
            .select_related('actor', 'actor__profile', 'business_page', 'product', 'post')
            .order_by('-created_at')[:10]
        )

        unread_event_count = EventNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_event_notifications = (
            EventNotification.objects
            .filter(to_user=request.user)
            .select_related('actor', 'actor__profile', 'event')
            .order_by('-created_at')[:10]
        )

        unread_job_application_count = JobApplicationNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()

        recent_job_application_notifications = (
            JobApplicationNotification.objects
            .filter(to_user=request.user)
            .select_related('actor', 'actor__profile', 'application', 'application__job')
            .order_by('-created_at')[:10]
        )

        return {
            'unread_follow_count':        unread_follow_count,
            'recent_follows':             recent_follows,
            'total_follow_notifications': total_follow_notifications,
            'has_follow_notifications':   total_follow_notifications > 0,
            'has_unread_follows':         unread_follow_count > 0,
            'unread_profile_post_count':             unread_profile_post_count,
            'recent_profile_post_notifications':     recent_profile_post_notifications,
            'has_unread_profile_post_notifications': unread_profile_post_count > 0,
            'unread_profile_item_count':             unread_profile_item_count,
            'recent_profile_item_notifications':     recent_profile_item_notifications,
            'has_unread_profile_item_notifications': unread_profile_item_count > 0,
            'unread_business_count':              unread_business_count,
            'recent_business_notifications':      recent_business_notifications,
            'has_unread_business_notifications':  unread_business_count > 0,
            'unread_event_count':                 unread_event_count,
            'recent_event_notifications':         recent_event_notifications,
            'has_unread_event_notifications':     unread_event_count > 0,
            'unread_job_application_count':             unread_job_application_count,
            'recent_job_application_notifications':     recent_job_application_notifications,
            'has_unread_job_application_notifications': unread_job_application_count > 0,
            'unread_notifications_total':  (
                unread_follow_count + unread_profile_post_count
                + unread_profile_item_count
                + unread_business_count + unread_event_count
                + unread_job_application_count
            ),
        }
    except Exception:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0,
            'has_follow_notifications': False,
            'has_unread_follows': False,
            'unread_profile_post_count': 0,
            'recent_profile_post_notifications': [],
            'has_unread_profile_post_notifications': False,
            'unread_profile_item_count': 0,
            'recent_profile_item_notifications': [],
            'has_unread_profile_item_notifications': False,
            'unread_business_count': 0,
            'recent_business_notifications': [],
            'has_unread_business_notifications': False,
            'unread_event_count': 0,
            'recent_event_notifications': [],
            'has_unread_event_notifications': False,
            'unread_job_application_count': 0,
            'recent_job_application_notifications': [],
            'has_unread_job_application_notifications': False,
            'unread_notifications_total': 0,
        }


def channel_unread_processor(request):
    if not request.user.is_authenticated:
        return {'total_followed_unread': 0}
    followed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(c.unread_count_for_user(request.user) for c in followed_channels)
    return {'total_followed_unread': total_unread}


def viewer_business_page_processor(request):
    """
    Makes the logged-in user's own business page (if any) available on every
    page — used by the bottom-nav "Create" modal (footer.html) to decide
    whether the Product option should link to the user's existing page or
    to the page-creation flow.
    """
    if not request.user.is_authenticated:
        return {'viewer_primary_business_page': None}
    try:
        viewer_primary_business_page = (
            BusinessPage.objects.filter(owner=request.user, is_active=True)
            .order_by('-created_at')
            .first()
        )
    except Exception:
        viewer_primary_business_page = None
    return {'viewer_primary_business_page': viewer_primary_business_page}


def business_inbox_processor(request):
    """
    Unread-message badge count across every business page the user owns or
    administers, pulled from the dedicated business inbox (BusinessMessage)
    — kept separate from `unread_count`, which is the personal DM count.
    """
    if not request.user.is_authenticated:
        return {'unread_business_message_count': 0}
    try:
        pages = BusinessPage.objects.filter(
            Q(owner=request.user) | Q(admins=request.user), is_active=True
        ).distinct()
        unread_business_message_count = BusinessMessage.objects.filter(
            business_page__in=pages, is_from_business=False, is_read=False
        ).count()
    except Exception:
        unread_business_message_count = 0
    return {'unread_business_message_count': unread_business_message_count}