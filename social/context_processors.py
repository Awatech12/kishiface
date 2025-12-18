from .models import Message
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Max
from .models import Notification
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

    grouped_qs = (
        Notification.objects
        .filter(recipient=request.user)
        .values('post', 'notification_type')
        .annotate(
            total=Count('id'),
            latest_time=Max('created_at')
        )
        .order_by('-latest_time')
    )

    today_list = []
    week_list = []
    earlier_list = []

    for g in grouped_qs:
        qs = Notification.objects.filter(
            recipient=request.user,
            post_id=g['post'],
            notification_type=g['notification_type']
        ).order_by('-created_at')

        latest = qs.first()

        item = {
            'latest_actor': latest.actor,
            'post': latest.post,
            'type': g['notification_type'],
            'others_count': qs.count() - 1,
            'created_at': latest.created_at,
            'is_read': qs.filter(is_read=False).exists(),
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
    }

