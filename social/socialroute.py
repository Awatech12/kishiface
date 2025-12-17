from django.urls import re_path
from .consumers.channelConsumer import ChannelConsumer
from .consumers.message import MessageChannel
from .consumers.commentConsumer import CommentConsumer
from .consumers.notification import NotificationConsumer
websocket_urlpatterns = [
    re_path(r'ws/message/$', MessageChannel.as_asgi()),
    re_path(r'ws/notification/$', NotificationConsumer.as_asgi()),
    re_path(r'ws/comment/(?P<post_id>[\w-]+)/$', CommentConsumer.as_asgi()),
    re_path(r'ws/(?P<channel_id>[\w-]+)/$', ChannelConsumer.as_asgi()),

]