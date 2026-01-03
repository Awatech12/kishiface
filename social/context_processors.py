from .models import Message, Notification, FollowNotification, Channel
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Max, Q

def unread_count_processor(request):
    if request.user.is_authenticated:
        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
    else:
        unread_count = 0
    
    return{'unread_count': unread_count}


def information(request):
    return {
        'name': 'Awatech Digital World'
    }


def user_notifications(request):
    if not request.user.is_authenticated:
        return {}

    now = timezone.now()
    today = now.date()
    week_ago = now - timedelta(days=7)

    # Group notifications by post + type
    grouped_qs = (
        Notification.objects
        .filter(recipient=request.user)
        .values('post', 'notification_type')
        .annotate(
            total=Count('id'),
            latest_time=Max('created_at'),
            unread_count=Count('id', filter=Q(is_read=False))
        )
        .order_by('-latest_time')
    )

    today_list = []
    week_list = []
    earlier_list = []

    unread_groups_count = 0

    for g in grouped_qs:
        qs = Notification.objects.filter(
            recipient=request.user,
            post_id=g['post'],
            notification_type=g['notification_type']
        ).order_by('-created_at')

        latest = qs.first()

        is_unread = g['unread_count'] > 0

        if is_unread:
            unread_groups_count += 1

        item = {
            'latest_actor': latest.actor,
            'post': latest.post,
            'type': g['notification_type'],
            'others_count': g['total'] - 1,
            'created_at': latest.created_at,
            'is_read': not is_unread,  # False if unread exists
        }

        if latest.created_at.date() == today:
            today_list.append(item)
        elif latest.created_at >= week_ago:
            week_list.append(item)
        else:
            earlier_list.append(item)

    return {
        'today_notifications': today_list,
        'week_notifications': week_list,
        'earlier_notifications': earlier_list,
        'unread_notifications_count': unread_groups_count,
    }


def follow_notifications_context(request):
    """
    Context processor for follow notifications
    Provides:
    - unread_follow_count: Count of unread follow notifications
    - recent_follows: Recent follow notifications (last 10)
    """
    if not request.user.is_authenticated:
        return {
            'unread_follow_count': 0,
            'recent_follows': [],
            'total_follow_notifications': 0
        }
    
    try:
        # Get unread follow notifications count
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user,
            is_read=False
        ).count()
        
        # Get recent follow notifications (last 10)
        recent_follows = FollowNotification.objects.filter(
            to_user=request.user
        ).select_related(
            'from_user', 
            'from_user__profile'
        ).order_by('-created_at')[:10]
        
        # Get total follow notifications count
        total_follow_notifications = FollowNotification.objects.filter(
            to_user=request.user
        ).count()
        
        return {
            'unread_follow_count': unread_follow_count,
            'recent_follows': recent_follows,
            'total_follow_notifications': total_follow_notifications,
            'has_follow_notifications': total_follow_notifications > 0,
            'has_unread_follows': unread_follow_count > 0,
        }
    
    except Exception as e:
        # In case of any error, return default values
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
    
    # Filter only channels the user follows
    followed_channels = Channel.objects.filter(subscriber=request.user)
    
    # Sum the unread counts
    total_unread = sum(c.unread_count_for_user(request.user) for c in followed_channels)
    
    return {'total_followed_unread': total_unread} #

