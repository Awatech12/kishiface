# social/routing.py
from django.urls import re_path
from .consumers.channelConsumer import ChannelConsumer, UserConsumer
from .consumers.message import DirectMessageConsumer
from .consumers.notification import NotificationConsumer
from .consumers.onlineConsumer import OnlineStatusConsumer

websocket_urlpatterns = [
    re_path(r'ws/message/(?P<username>[\w.@+-]+)/$', DirectMessageConsumer.as_asgi()),
    re_path(r'ws/notification/$', NotificationConsumer.as_asgi()),
    re_path(r'ws/(?P<channel_id>[\w-]+)/$', ChannelConsumer.as_asgi()),
    re_path(r'ws/online-status/$', OnlineStatusConsumer.as_asgi()),
    re_path(r'ws/user/(?P<user_id>\d+)/$', UserConsumer.as_asgi()),
]