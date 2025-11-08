from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('home', views.home, name='home'),
    path('open/<int:pk>', views.open_notification, name='open_notification'),
    path('comments/<uuid:post_id>', views.postcomment, name='postcomment'),
    path('comment_like/<uuid:comment_id>', views.comment_like, name='comment_like'),
    path('logout',views.logout, name='logout'),
    path('search', views.search, name='search'),
    path('inbox',views.inbox, name='inbox'),
     path('inbox_count', views.inbox_partial, name='inbox_partial'),
    path('notification', views.notification_partial, name='notification_partial'),
    path('editpost/<uuid:post_id>', views.editpost, name='editpost'),
    path('list', views.notification_list, name='notification_list'),
    path('comment_reply/<uuid:comment_id>', views.comment_reply, name='comment_reply'),
    #path('posts', views.post_content, name='post_content'),
    path('channel/<uuid:channel_id>/', views.channel, name='channel'),
    path('create_channel', views.channel_create, name='channel_create'),
    path('post', views.post, name="post"),
    path('private/<str:username>', views.message, name='message'),
    path('follow/<str:username>', views.follow, name='follow'),
    path('like/<uuid:post_id>', views.like_post, name='like_post'),
    path('comment/<uuid:post_id>', views.post_comment, name='post_comment'),
    path('<str:username>', views.profile, name='profile'),
   
    path('?/<str:username>', views.update_profile, name='update_profile')
]