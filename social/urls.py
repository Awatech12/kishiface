from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('home', views.home, name='home'),
    path('open/<uuid:post_id>/<str:notification_type>', views.open_notification, name='open_notification'),
    path('comments/<uuid:post_id>', views.postcomment, name='postcomment'),
    path('comment_like/<uuid:comment_id>', views.comment_like, name='comment_like'),
    path('logout',views.logout, name='logout'),
    path('search', views.search, name='search'),
    path('search/delete/<int:history_id>/', views.delete_history, name='delete_history'),
    path('search/clear/', views.clear_history, name='clear_history'),
    path('inbox',views.inbox, name='inbox'),
    path('explore/', views.explore_users, name='explore'),
    path('mark-follow-notifications-read/', views.mark_follow_notifications_read, name='mark_follow_notifications_read'),
      
  path('delete_message/<int:message_id>/', views.delete_message, name='delete_message'),
    
    # If you want both /explore/ and /explore-users/ to work: and nexted comments
    path('comment/<uuid:comment_id>/add-reply/', views.add_comment_reply, name='add_comment_reply'),
    path('api/like-reply/<uuid:reply_id>/', views.like_reply, name='like_reply'),
    path('reply/<uuid:reply_id>/edit/', views.edit_reply, name='edit_reply'),
    path('reply/<uuid:reply_id>/delete/', views.delete_reply, name='delete_reply'),
    path('explore-users/', views.explore_users, name='explore_users'),
    path('inbox',views.inbox, name='inbox'),
    path('followers/<str:username>', views.follower_list, name="followers"),
    path('following/<str:username>', views.following_list, name='following'),
     path('inbox_count', views.inbox_partial, name='inbox_partial'),
    path('notification', views.notification_partial, name='notification_partial'),
    path('editpost/<uuid:post_id>', views.editpost, name='editpost'),
    path('list', views.notification_list, name='notification_list'),
    path('product/<uuid:product_id>/', views.product_detail, name='product_detail'),
    path('spotlight/', views.spotlight_view, name='spotlight'),
    path('track_share/<uuid:post_id>/', views.track_share, name='track_share'),
    path('get-location/<str:username>/', views.get_location, name='get_location'),
   path('mark-follow-notifications-read/', views.mark_follow_notifications_read, name='mark_follow_notifications_read'),
   path('notifications/delete-group/', views.delete_notification_group, name='delete_notification_group'),
   
   # Story APIs
    path('api/stories/', views.get_stories, name='get_stories'),
    path('api/stories/<uuid:story_id>/view/', views.mark_story_viewed, name='mark_story_viewed'),
    path('api/stories/<uuid:story_id>/reply/', views.send_story_reply, name='send_story_reply'),
    path('api/stories/create/', views.create_story, name='create_story'),
        path('api/stories/<uuid:story_id>/viewers/', views.get_story_viewers, name='get_story_viewers'),

    #====== Profials codes =======
    path('<str:username>/', views.profile, name='profile'),
    path('<str:username>/videos/', views.profile_videos, name='profile_videos'),
    path('<str:username>/audios/', views.profile_audios, name='profile_audios'),
    path('<str:username>/text-posts/', views.profile_text_posts, name='profile_text_posts'),
    path('follow/<int:user_id>/', views.follow_user, name='follow_user'),

    # ===== Market Place Path ======
    path('market', views.market, name='market'),
    path('channel_message/<uuid:channel_id>/', views.channel_message, name='channel_message'),
    path('channelmessage_like/<uuid:channelmessage_id>/', views.channelmessage_like, name='channelmessage_like'),

    
    # Admin Update View
    path('update_channel/<uuid:channel_id>/', views.update_channel, name='update_channel'),
    
    # Member Management API
    path('channel/manage-member/<uuid:channel_id>/<int:user_id>/', views.manage_member, name='manage_member'),
    path('channel/toggle-admin/<uuid:channel_id>/<int:user_id>/', views.toggle_admin, name='toggle_admin'),

    #====== market form =======
    path('comment_reply/<uuid:comment_id>', views.comment_reply, name='comment_reply'),
    path('followChannel/<uuid:channel_id>', views.follow_channel, name='follow_channel'),
    path('channel/<uuid:channel_id>/', views.channel, name='channel'),
    path('create_channel', views.channel_create, name='channel_create'),
    path('post', views.post, name="post"),
    path('private/<str:username>', views.message, name='message'),
    path('send_message/<str:username>/', views.send_message, name='send_message'),
    path('follow/<str:username>', views.follow, name='follow'),
    path('like/<uuid:post_id>', views.like_post, name='like_post'),
    path('comment/<uuid:post_id>', views.post_comment, name='post_comment'),
    #path('<str:username>', views.profile, name='profile'),
   path('repost/<uuid:post_id>/', views.repost_post, name='repost_post'),
    path('?/<str:username>', views.update_profile, name='update_profile')
]