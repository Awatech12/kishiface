from django.urls import re_path
from .consumers.channelConsumer import ChannelConsumer
from .consumers.message import MessageChannel
from .consumers.notification import NotificationConsumer
websocket_urlpatterns = [
    re_path(r'ws/message/$', MessageChannel.as_asgi()),
    re_path(r'ws/notification/$', NotificationConsumer.as_asgi()),
    
    re_path(r'ws/(?P<channel_id>[\w-]+)/$', ChannelConsumer.as_asgi()),

]