from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),

    # ── Register — real-time AJAX validation ──────────────────────────────────
    path('register/check-username/', views.validate_username,          name='validate_username'),
    path('register/check-email/',    views.validate_email,             name='validate_email'),
    path('register/check-password/', views.validate_password_strength, name='validate_password_strength'),

    # ── Account ────────────────────────────────────────────────────────────────
    path('change-password/', views.change_password, name='change_password'),

    # ── Forgot Password (secret-question flow) ─────────────────────────────────
    path('forgot-password/lookup/', views.forgot_password_lookup, name='forgot_password_lookup'),
    path('forgot-password/reset/',  views.forgot_password_reset,  name='forgot_password_reset'),

    # ── Home feed ──────────────────────────────────────────────────────────────
    path('home',                    views.home,                 name='home'),
    path('feed/more/',              views.feed_load_more,       name='feed_load_more'),
    path('sidebar/connections/',    views.sidebar_connections,  name='sidebar_connections'),
    path('profile-sidebar/<str:username>/connections/', views.profile_sidebar_connections, name='profile_sidebar_connections'),

    # ── Notifications ──────────────────────────────────────────────────────────
    path('open/<uuid:post_id>/<str:notification_type>', views.open_notification,             name='open_notification'),
    path('list',                                        views.notification_list,             name='notification_list'),
    path('notification',                                views.notification_partial,          name='notification_partial'),
    path('notifications/delete-group/',                 views.delete_notification_group,     name='delete_notification_group'),
    path('notifications/mark-all-read/',                views.mark_all_notifications_read,   name='mark_all_notifications_read'),
    path('mark-follow-notifications-read/',             views.mark_follow_notifications_read,name='mark_follow_notifications_read'),

    # ── Auth ───────────────────────────────────────────────────────────────────
    path('logout', views.logout, name='logout'),

    # ── Search ─────────────────────────────────────────────────────────────────
    path('search',                           views.search,                   name='search'),
    path('search/users/',                    views.search_users_partial,     name='search_users_partial'),
    path('search/posts/',                    views.search_posts_partial,     name='search_posts_partial'),
    path('search/tags/',                     views.search_hashtags_partial,  name='search_hashtags_partial'),
    path('search/explore/',                  views.explore_partial,          name='explore_partial'),
    path('search/delete/<int:history_id>/',  views.delete_history,           name='delete_history'),
    path('search/clear/',                    views.clear_history,            name='clear_history'),

    # ── Inbox / Messages ───────────────────────────────────────────────────────
    path('inbox',                               views.inbox,          name='inbox'),
    path('inbox_count',                         views.inbox_partial,  name='inbox_partial'),
    path('private/<str:username>',              views.message,        name='message'),
    path('send_message/<str:username>/',        views.send_message,   name='send_message'),
    path('delete_message/<int:message_id>/',    views.delete_message, name='delete_message'),
    path('react_message/<int:message_id>/',     views.react_to_message, name='react_to_message'),

    # ── Posts ──────────────────────────────────────────────────────────────────
    path('post',                          views.post,         name='post'),
    path('editpost/<uuid:post_id>',       views.editpost,     name='editpost'),
    path('like/<uuid:post_id>',           views.like_post,    name='like_post'),
    path('repost/<uuid:post_id>/',        views.repost_post,  name='repost_post'),
    path('comment/<uuid:post_id>',        views.post_comment, name='post_comment'),
    path('comments/<uuid:post_id>',       views.postcomment,  name='postcomment'),
    path('comments/poll/<uuid:post_id>/', views.comments_poll,name='comments_poll'),
    path('comment_like/<uuid:comment_id>',views.comment_like, name='comment_like'),
    path('comment_reply/<uuid:comment_id>',views.comment_reply,name='comment_reply'),

    # ── Post Vibes ─────────────────────────────────────────────────────────────
    path('vibe/<uuid:post_id>/', views.get_post_vibes, name='get_post_vibes'),

    # ── Comment Replies ────────────────────────────────────────────────────────
    path('comment/<uuid:comment_id>/add-reply/', views.add_comment_reply, name='add_comment_reply'),
    path('api/like-reply/<uuid:reply_id>/',       views.like_reply,        name='like_reply'),
    path('reply/<uuid:reply_id>/edit/',           views.edit_reply,        name='edit_reply'),
    path('reply/<uuid:reply_id>/delete/',         views.delete_reply,      name='delete_reply'),

    path('follow/<int:user_id>/',      views.follow_user,    name='follow_user'),
    path('follow/<str:username>',      views.follow,         name='follow'),
    path('followers/<str:username>',   views.follower_list,  name='followers'),
    path('following/<str:username>',   views.following_list, name='following'),

    # ── Hashtags ───────────────────────────────────────────────────────────────
    path('hashtag/<str:tag_name>/', views.hashtag_view, name='hashtag_view'),

    # ── Channels ───────────────────────────────────────────────────────────────
    path('create_channel',                                              views.channel_create,              name='channel_create'),
    path('channel/<uuid:channel_id>/',                                  views.channel,                     name='channel'),
    path('channel_message/<uuid:channel_id>/',                          views.channel_message,             name='channel_message'),
    path('channelmessage_like/<uuid:channelmessage_id>/',               views.channelmessage_like,         name='channelmessage_like'),
    path('update_channel/<uuid:channel_id>/',                           views.update_channel,              name='update_channel'),
    path('channel/manage-member/<uuid:channel_id>/<int:user_id>/',      views.manage_member,               name='manage_member'),
    path('channel/toggle-admin/<uuid:channel_id>/<int:user_id>/',       views.toggle_admin,                name='toggle_admin'),
    path('followChannel/<uuid:channel_id>',                             views.follow_channel,              name='follow_channel'),
    path('channel/delete-message/<uuid:channel_id>/<uuid:message_id>/', views.delete_channel_message,      name='delete_channel_message'),
    path('channel/react/<uuid:message_id>/',                            views.react_to_channel_message,    name='react_to_channel_message'),

    # ── Ads ────────────────────────────────────────────────────────────
    path('market',                          views.market,          name='market'),
    path('product/<uuid:product_id>/',      views.product_detail,  name='product_detail'),
    path('product/<uuid:product_id>/contact/', views.contact_seller, name='contact_seller'),

    # ── Spotlight ──────────────────────────────────────────────────────────────
    path('spotlight/', views.spotlight_view, name='spotlight'),

    # ── Utilities ──────────────────────────────────────────────────────────────
    path('track_share/<uuid:post_id>/',    views.track_share,           name='track_share'),
    path('record-view/<uuid:post_id>/',    views.increment_post_view,   name='increment_post_view'),
    path('fetch_link_preview/',            views.fetch_link_preview,    name='fetch_link_preview'),
    path('get-location/<str:username>/',   views.get_location,          name='get_location'),

    # ── Online Status ──────────────────────────────────────────────────────────
    path('api/online-status/<int:user_id>/', views.online_status_api, name='online_status_api'),
    path('set-offline/',                     views.set_offline,       name='set_offline'),

    # ── Profiles (catch-alls — must stay at the bottom) ───────────────────────
    path('?/<str:username>',              views.update_profile,    name='update_profile'),
    path('block/<str:username>/',         views.block_user,        name='block_user'),
    path('report/<str:username>/',        views.report_user,       name='report_user'),
    path('<str:username>/videos/',        views.profile_videos,    name='profile_videos'),
    path('<str:username>/text-posts/',    views.profile_text_posts,name='profile_text_posts'),
    path('<str:username>/',               views.profile,           name='profile'),
]
