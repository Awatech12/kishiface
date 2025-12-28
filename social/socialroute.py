# social/routing.py
from django.urls import re_path
from .consumers.channelConsumer import ChannelConsumer
from .consumers.message import DirectMessageConsumer

from .consumers.notification import NotificationConsumer

websocket_urlpatterns = [
    re_path(r'ws/message/(?P<username>[\w.@+-]+)/$', DirectMessageConsumer.as_asgi()),
    re_path(r'ws/notification/$', NotificationConsumer.as_asgi()),
  
    re_path(r'ws/(?P<channel_id>[\w-]+)/$', ChannelConsumer.as_asgi()),  # Keep this exactly as it was
]