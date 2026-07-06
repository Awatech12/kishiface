from django.contrib import admin
from social.models import Profile,UserReport, BlockedUser,LoginAttempt, Message, Channel, ChannelMessage, Market, MarketImage

# Register your models here.

admin.site.register(Profile)


admin.site.register(Message)
admin.site.register(Channel)
admin.site.register(ChannelMessage)
admin.site.register(Market)
admin.site.register(MarketImage)
admin.site.register(UserReport)
admin.site.register(BlockedUser)
admin.site.register(LoginAttempt)
