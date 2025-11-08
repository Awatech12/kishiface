from .models import Message
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
    if request.user.is_authenticated:
        return{
            'notifications': Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
        }
    return {}