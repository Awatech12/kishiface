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

    # ── Onboarding ─────────────────────────────────────────────────────────────
    path('onboarding/',             views.onboarding,           name='onboarding'),

    # ── Home feed ──────────────────────────────────────────────────────────────
    path('home',                    views.home,                 name='home'),
    path('feed/more/',              views.feed_load_more,       name='feed_load_more'),
    path('sidebar/connections/',    views.sidebar_connections,  name='sidebar_connections'),
    path('profile-sidebar/<str:username>/connections/', views.profile_sidebar_connections, name='profile_sidebar_connections'),

    # ── Notifications (Follow notifications only) ─────────────────────────────
    path('notification',                                views.notification_partial,          name='notification_partial'),
    path('list',                                        views.notification_list,             name='notification_list'),
    path('notifications/delete-group/',                 views.delete_notification_group,     name='delete_notification_group'),
    path('notifications/mark-all-read/',                views.mark_all_notifications_read,   name='mark_all_notifications_read'),
    path('mark-follow-notifications-read/',             views.mark_follow_notifications_read,name='mark_follow_notifications_read'),

    # ── Auth ───────────────────────────────────────────────────────────────────
    path('logout', views.logout, name='logout'),

    # ── Search ─────────────────────────────────────────────────────────────────
    path('search',                           views.search,                   name='search'),
    path('search/suggestions/',              views.search_suggestions_v0,    name='search_suggestions'),
    path('search/users/',                    views.search_users_partial,     name='search_users_partial'),
    path('search/products/',                 views.search_products_partial,  name='search_products_partial'),
    path('search/pages/',                    views.search_pages_partial,     name='search_pages_partial'),
    path('search/jobs/',                     views.search_jobs_partial,      name='search_jobs_partial'),
    path('search/explore/products/',         views.explore_products_partial, name='explore_products_partial'),
    path('search/delete/<int:history_id>/',  views.delete_history,           name='delete_history'),
    path('search/clear/',                    views.clear_history,            name='clear_history'),

    # ── Inbox / Messages ───────────────────────────────────────────────────────
    path('inbox',                               views.inbox,             name='inbox'),
    path('inbox_count',                         views.inbox_partial,     name='inbox_partial'),
    path('inbox/last_message/',                 views.dm_last_message,   name='dm_last_message'),
    path('inbox/conversation/',                 views.dm_conversation,   name='dm_conversation'),
    path('private/<str:username>',              views.message,           name='message'),
    path('send_message/<str:username>/',        views.send_message,      name='send_message'),
    path('delete_message/<int:message_id>/',    views.delete_message,    name='delete_message'),
    path('react_message/<int:message_id>/',     views.react_to_message,  name='react_to_message'),

    # ── Services ───────────────────────────────────────────────────────────────
    path('services', views.services, name='services'),

    # ── Event Calendar ─────────────────────────────────────────────────────────
    path('events/',                    views.event_calendar,        name='event_calendar'),
    path('events/create/',             views.event_calendar_create, name='event_calendar_create'),
    path('events/<int:event_id>/',        views.event_detail,          name='event_detail'),
    path('events/<int:event_id>/edit/',   views.event_calendar_edit,   name='event_calendar_edit'),
    path('events/<int:event_id>/delete/', views.event_calendar_delete, name='event_calendar_delete'),
    path('events/<int:event_id>/follow/', views.event_follow_toggle,   name='event_follow_toggle'),

    # ── Follow ─────────────────────────────────────────────────────────────────
    path('follow/<str:username>',      views.follow,         name='follow'),
    path('followers/<str:username>',   views.follower_list,  name='followers'),
    path('following/<str:username>',   views.following_list, name='following'),

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

    # ── Job Vacancy ────────────────────────────────────────────────────────
    path('jobs/',                              views.job_vacancy,        name='job_vacancy'),
    path('jobs/create/',                       views.job_vacancy_create, name='job_vacancy_create'),
    path('jobs/<uuid:job_id>/',                views.job_detail,         name='job_detail'),
    path('jobs/<uuid:job_id>/contact/',        views.contact_poster,     name='contact_poster'),
    path('jobs/<uuid:job_id>/edit/',           views.job_vacancy_edit,   name='job_vacancy_edit'),
    path('jobs/<uuid:job_id>/delete/',         views.job_vacancy_delete, name='job_vacancy_delete'),

    # ── Ads ────────────────────────────────────────────────────────────
    path('market',                             views.market,          name='market'),
    path('product/<uuid:product_id>/',         views.product_detail,  name='product_detail'),
    path('product/<uuid:product_id>/contact/', views.contact_seller,  name='contact_seller'),
    path('product/<uuid:product_id>/edit/',    views.edit_product,    name='edit_product'),
    path('product/<uuid:product_id>/delete/',  views.delete_product,  name='delete_product'),

    # ── Wishlist ───────────────────────────────────────────────────────
    path('wishlist/',                              views.wishlist_view,     name='wishlist'),
    path('product/<uuid:product_id>/wishlist/',     views.toggle_wishlist,   name='toggle_wishlist'),

    # ── Reviews & Ratings ─────────────────────────────────────────────────
    path('product/<uuid:product_id>/review/',                     views.submit_review, name='submit_review'),
    path('product/<uuid:product_id>/review/<uuid:review_id>/delete/', views.delete_review, name='delete_review'),

    # ── Utilities ──────────────────────────────────────────────────────────────
    path('fetch_link_preview/',            views.fetch_link_preview,    name='fetch_link_preview'),
    path('get-location/<str:username>/',   views.get_location,          name='get_location'),

    # ── Online Status ──────────────────────────────────────────────────────────
    path('api/online-status/<int:user_id>/', views.online_status_api, name='online_status_api'),
    path('set-offline/',                     views.set_offline,       name='set_offline'),

    # ── Job vacancy reactions ──────────────────────────────────────────────────
    path('jobs/<uuid:job_id>/vibe/',           views.job_vibe,        name='job_vibe'),
    path('jobs/<uuid:job_id>/comments/',       views.job_comments,    name='job_comments'),

    # ── Social event reactions ─────────────────────────────────────────────────
    path('events/<int:event_id>/vibe/',        views.event_vibe,      name='event_vibe'),
    path('events/<int:event_id>/comments/',    views.event_comments,  name='event_comments'),

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN DASHBOARD  (staff only — guarded in views via @staff_member_required)
    # ══════════════════════════════════════════════════════════════════════════
    path('admin-dashboard/',                            views.admin_dashboard,      name='admin_dashboard'),
    path('admin-dashboard/report/<int:report_id>/resolve/', views.admin_resolve_report, name='admin_resolve_report'),
    path('admin-dashboard/user/<int:user_id>/delete/',      views.admin_delete_user,    name='admin_delete_user'),
    path('admin-dashboard/user/<int:user_id>/verify/',      views.admin_verify_user,    name='admin_verify_user'),
    path('admin-dashboard/channel/<uuid:channel_id>/delete/', views.admin_delete_channel, name='admin_delete_channel'),
    path('admin-dashboard/product/<uuid:product_id>/delete/', views.admin_delete_product, name='admin_delete_product'),
    path('admin-dashboard/event/<int:event_id>/delete/',    views.admin_delete_event,   name='admin_delete_event'),
    path('admin-dashboard/job/<uuid:job_id>/delete/',       views.admin_delete_job,     name='admin_delete_job'),

    # ── Business Pages ─────────────────────────────────────────────────────────
    path('business/',                                   views.business_pages_list,       name='business_pages_list'),
    path('business/create/',                            views.business_page_create,      name='business_page_create'),
    path('business/mine/',                              views.business_pages_mine,       name='business_pages_mine'),
    path('business/<slug:slug>/',                       views.business_page_detail,      name='business_page_detail'),
    path('business/<slug:slug>/edit/',                  views.business_page_edit,        name='business_page_edit'),
    path('business/<slug:slug>/follow/',                views.business_page_follow,      name='business_page_follow'),
    path('business/<slug:slug>/upload/',                views.business_product_upload,   name='business_product_upload'),
    path('business/<slug:slug>/jobs/upload/',           views.business_job_upload,       name='business_job_upload'),

    # ── Business Page Updates (image / video / text / poll posts) ─────────────
    path('business/<slug:slug>/posts/create/',          views.business_post_create,      name='business_post_create'),
    path('posts/<uuid:post_id>/delete/',                views.business_post_delete,      name='business_post_delete'),
    path('posts/<uuid:post_id>/vote/',                  views.business_post_poll_vote,   name='business_post_poll_vote'),
    path('posts/<uuid:post_id>/vibe/',                  views.business_post_vibe,        name='business_post_vibe'),
    path('posts/<uuid:post_id>/comments/',              views.business_post_comments,    name='business_post_comments'),

    # ── Business Page — optional professional sections ─────────────────────
    path('business/<slug:slug>/services/create/',       views.business_service_create,     name='business_service_create'),
    path('services/<uuid:service_id>/delete/',          views.business_service_delete,     name='business_service_delete'),
    path('business/<slug:slug>/portfolio/create/',      views.business_portfolio_create,   name='business_portfolio_create'),
    path('portfolio/<uuid:item_id>/delete/',            views.business_portfolio_delete,   name='business_portfolio_delete'),
    path('business/<slug:slug>/achievements/create/',   views.business_achievement_create, name='business_achievement_create'),
    path('achievements/<uuid:achievement_id>/delete/',  views.business_achievement_delete, name='business_achievement_delete'),

    # ── Business Page — Reviews & Ratings ───────────────────────────────────
    path('business/<slug:slug>/reviews/create/',        views.business_review_create,      name='business_review_create'),
    path('reviews/<uuid:review_id>/reply/',             views.business_review_reply,       name='business_review_reply'),
    path('reviews/<uuid:review_id>/delete/',            views.business_review_delete,      name='business_review_delete'),

    # ── Profile — professional sections (Services, Portfolio, Projects,
    # Achievements, Posts, Products) owned directly by the user's Profile,
    # no BusinessPage required ───────────────────────────────────────────
    path('profile/sections/update/',                    views.profile_sections_update,     name='profile_sections_update'),
    path('profile/services/create/',                    views.profile_service_create,      name='profile_service_create'),
    path('profile/services/<uuid:service_id>/delete/',   views.profile_service_delete,      name='profile_service_delete'),
    path('profile/experience/create/',                    views.profile_experience_create,   name='profile_experience_create'),
    path('profile/experience/<uuid:experience_id>/delete/', views.profile_experience_delete, name='profile_experience_delete'),
    path('profile/education/create/',                     views.profile_education_create,    name='profile_education_create'),
    path('profile/education/<uuid:education_id>/delete/', views.profile_education_delete,    name='profile_education_delete'),
    path('profile/portfolio/create/',                    views.profile_portfolio_create,    name='profile_portfolio_create'),
    path('profile/portfolio/<uuid:item_id>/delete/',      views.profile_portfolio_delete,    name='profile_portfolio_delete'),
    path('profile/portfolio/<uuid:item_id>/vibe/',        views.profile_portfolio_vibe,       name='profile_portfolio_vibe'),
    path('profile/portfolio/<uuid:item_id>/comments/',    views.profile_portfolio_comments,   name='profile_portfolio_comments'),
    path('profile/achievements/create/',                  views.profile_achievement_create,  name='profile_achievement_create'),
    path('profile/achievements/<uuid:achievement_id>/delete/', views.profile_achievement_delete, name='profile_achievement_delete'),
    path('profile/achievements/<uuid:achievement_id>/vibe/',     views.profile_achievement_vibe,     name='profile_achievement_vibe'),
    path('profile/achievements/<uuid:achievement_id>/comments/', views.profile_achievement_comments, name='profile_achievement_comments'),
    path('profile/experience/<uuid:experience_id>/vibe/',        views.profile_experience_vibe,      name='profile_experience_vibe'),
    path('profile/experience/<uuid:experience_id>/comments/',    views.profile_experience_comments,  name='profile_experience_comments'),
    path('profile/education/<uuid:education_id>/vibe/',          views.profile_education_vibe,       name='profile_education_vibe'),
    path('profile/education/<uuid:education_id>/comments/',      views.profile_education_comments,   name='profile_education_comments'),
    path('profile/services/<uuid:service_id>/vibe/',              views.profile_service_vibe,         name='profile_service_vibe'),
    path('profile/services/<uuid:service_id>/comments/',          views.profile_service_comments,     name='profile_service_comments'),
    path('profile/posts/create/',                         views.profile_post_create,         name='profile_post_create'),
    path('profile/posts/<uuid:post_id>/delete/',          views.profile_post_delete,         name='profile_post_delete'),
    path('profile/posts/<uuid:post_id>/vote/',            views.profile_post_poll_vote,      name='profile_post_poll_vote'),
    path('profile/posts/<uuid:post_id>/vibe/',            views.profile_post_vibe,           name='profile_post_vibe'),
    path('profile/posts/<uuid:post_id>/comments/',        views.profile_post_comments,       name='profile_post_comments'),
    path('profile/products/upload/',                      views.profile_product_upload,      name='profile_product_upload'),

    # ── Profiles (catch-alls — must stay at the bottom) ───────────────────────
    path('block/<str:username>/',                    views.block_user,          name='block_user'),
    path('report/<str:username>/',                   views.report_user,         name='report_user'),
    path('<str:username>/edit/',                     views.update_profile,      name='update_profile'),
    path('<str:username>/toggle-privacy/',           views.toggle_privacy_lock, name='toggle_privacy_lock'),
    path('<str:username>/',                          views.profile,             name='profile'),
]