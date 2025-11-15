from django.urls import re_path
from .consumers.channelConsumer import ChannelConsumer
websocket_urlpatterns = [
    re_path(r'ws/(?P<channel_id>[\w-]+)/$', ChannelConsumer.as_asgi())
]