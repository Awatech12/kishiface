from django.contrib import admin
from social.models import Profile, Post, PostImage, PostComment, Message, Notification, Channel, ChannelMessage

# Register your models here.

admin.site.register(Profile)
admin.site.register(Post)
admin.site.register(PostImage)
admin.site.register(PostComment)
admin.site.register(Message)
admin.site.register(Notification)
admin.site.register(Channel)
admin.site.register(ChannelMessage)
