import os
import re
import uuid as uuid_module
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from .models import FollowNotification
from django.template.loader import render_to_string
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, Post, PostImage, UserReport, BlockedUser, CommentReply, ChannelUserLastSeen, PostComment, Message, Notification, ChannelMessage, Channel, Market, MarketImage, SearchHistory
from django.db.models import Q
from django.db.models import Count, Max, Min
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time, json, logging, re, requests, ipaddress
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from django.http import JsonResponse, Http404
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
import random
from django.views.decorators.csrf import csrf_exempt
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.http import require_POST
import cloudinary

# Create your views here.
def index(request):
    if request.user.is_authenticated:
        messages.info(request, f'{request.user.username} welcome')
        return redirect(request.GET.get('next','home'))
    if request.method =='POST':
        user_check = request.POST.get('user_check').strip()
        password = request.POST.get('password').strip()

        try:
            user_obj = User.objects.get(email=user_check)
            username = user_obj.username
        except User.DoesNotExist:
            username=user_check
        user =authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            request.session.set_expiry(None)
            messages.success(request, f"Welcome back {user.username}")
            return redirect(request.GET.get('next', 'home'))
        else:
            messages.error(request,'Invalid Login details')
            return redirect('/')
    return render(request, 'index.html')


def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('pass1')
        password2 = request.POST.get('pass2')
        if (len(username) < 5):
            messages.error(request, 'Username must contain atleast 5 Characters')
            return redirect('register')
        elif User.objects.filter(username=username):
            messages.error(request, ' Username is taken Already')
            return redirect('register')
        elif User.objects.filter(email=email):
            messages.error(request, 'Email is taken Already')
            return redirect('register')
        elif (password != password2):
            messages.error(request, 'Password are not the Same')
            return redirect('register')
        else:
            user=User.objects.create_user(username=username, email=email, password=password)
            Profile.objects.create(user=user)
            messages.success(request, f'Welcome {username}, You can now Login')
            return redirect('/')

    return render(request, 'register.html')


def extract_hashtags(content):
    """Extract hashtags from post content"""
    import re
    hashtags = re.findall(r'#(\w+)', content)
    return hashtags


@login_required(login_url='/')
def home(request):
    profile = Profile.objects.get(user=request.user)
    following = profile.followings.values_list('user', flat=True)
    
    followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')
    
    followed_list = []
    total_unread = 0
    
    for channel in followed_channels:
        unread = channel.unread_count_for_user(request.user)
        total_unread += unread
        last_msg = channel.channel_messages.order_by('-created_at').first()
        msg_type = 'text'
        if last_msg:
            if last_msg.file_type == 'audio':
                msg_type = 'audio'
            elif last_msg.file_type == 'video':
                msg_type = 'video'
            elif last_msg.file_type == 'image':
                msg_type = 'image'
        followed_list.append({
            'channel': channel,
            'unread_count': unread,
            'last_message': last_msg.message if last_msg else "No messages yet",
            'last_time': last_msg.created_at if last_msg else None,
            'message_type': msg_type
        })
    
    users = list(User.objects.exclude(id__in=following).exclude(id=request.user.id).order_by('?'))

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user,
        is_read=False
    ).count()

    unread_notifications_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    feed = []

    trending_hashtags = []
    recent_posts = Post.objects.filter(
        Q(author__in=following) | Q(author=request.user)
    )[:100]

    hashtag_counts = {}
    for post in recent_posts:
        hashtags = extract_hashtags(post.content)
        for tag in hashtags:
            hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1

    trending_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    if not following:
        posts = Post.objects.all().order_by('?').select_related(
            'author', 'author__profile',
            'original_post', 'original_post__author', 'original_post__author__profile'
        ).prefetch_related('likes', 'reposts', 'images')
    else:
        posts = Post.objects.filter(
            Q(author__in=following) |
            Q(author=request.user) |
            Q(is_repost=True, author__in=following)
        ).order_by('?').select_related(
            'author', 'author__profile',
            'original_post', 'original_post__author', 'original_post__author__profile'
        ).prefetch_related('likes', 'reposts', 'images')

    following_ids = list(following)
    following_ids_set = set(following)

    fof_ids = set()
    for followed_user_id in following_ids_set:
        try:
            followed_profile = Profile.objects.get(user_id=followed_user_id)
            their_followings = followed_profile.followings.values_list('user', flat=True)
            fof_ids.update(
                uid for uid in their_followings
                if uid not in following_ids_set and uid != request.user.id
            )
        except Profile.DoesNotExist:
            pass

    fof_via_cache = {}
    for fof_uid in fof_ids:
        for followed_user_id in following_ids_set:
            try:
                followed_profile = Profile.objects.get(user_id=followed_user_id)
                if followed_profile.followings.filter(user_id=fof_uid).exists():
                    fof_via_cache.setdefault(fof_uid, []).append(
                        User.objects.get(id=followed_user_id)
                    )
            except (Profile.DoesNotExist, User.DoesNotExist):
                pass

    for i, post in enumerate(posts, 1):
        actual_author_id = post.original_post.author_id if post.is_repost and post.original_post else post.author_id
        is_fof = actual_author_id in fof_ids
        fof_via = fof_via_cache.get(actual_author_id, []) if is_fof else []
        feed.append({'type': 'post', 'data': post, 'is_fof': is_fof, 'fof_via': fof_via})
        if i % 4 == 2 and users:
            feed.append({'type': 'user_suggestion', 'data': users.pop(0)})

    sidebar_followings = profile.followings.select_related('user').all()
    sidebar_followers  = profile.followers.select_related('user').all()

    return render(request, 'home.html', {
        'posts_with_ads': feed,
        'followed_list': followed_list[:8],
        'unread_follow_count': unread_follow_count,
        'unread_notifications_count': unread_notifications_count,
        'users': users[:3],
        'trending_hashtags': trending_hashtags,
        'following_ids': following_ids,
        'sidebar_followings': sidebar_followings,
        'sidebar_followers': sidebar_followers,
    })


def _safe_pic_url(user_obj):
    """
    Return picture URL safely. Works in both debug (ImageField) and
    production (CloudinaryField). Always returns a full https URL.
    """
    try:
        if hasattr(user_obj, 'profile') and user_obj.profile.picture:
            pic = user_obj.profile.picture
            if hasattr(pic, 'public_id') and pic.public_id:
                return cloudinary.CloudinaryImage(pic.public_id).build_url(secure=True)
            if hasattr(pic, 'url') and pic.url:
                url = pic.url
                if url.startswith('http://'):
                    url = 'https://' + url[7:]
                return url
    except Exception:
        pass
    return ''


@login_required(login_url='/')
@require_POST
def repost_post(request, post_id):
    """Handle reposting a post and notify the original author."""
    try:
        original_post = get_object_or_404(Post, post_id=post_id)
        user = request.user

        data    = json.loads(request.body)
        caption = data.get('caption', '').strip()
        undo    = data.get('undo', False)

        existing_repost = Post.objects.filter(
            author=user,
            is_repost=True,
            original_post=original_post,
        ).first()

        if undo and existing_repost:
            existing_repost.delete()
            original_post.reposts.remove(user)

            # Remove repost notification
            Notification.objects.filter(
                recipient=original_post.author,
                actor=user,
                post=original_post,
                notification_type=Notification.REPOST,
            ).delete()

            reposted = False
            message  = 'Repost removed'

        elif not undo and not existing_repost:
            repost = Post.objects.create(
                author=user,
                is_repost=True,
                original_post=original_post,
                repost_content=caption,
                content='',
            )
            original_post.reposts.add(user)

            # Notify original author (not for self-reposts)
            if original_post.author != user:
                Notification.objects.get_or_create(
                    recipient=original_post.author,
                    actor=user,
                    post=original_post,
                    notification_type=Notification.REPOST,
                )

            reposted = True
            message  = 'Post reposted successfully!'

        elif not undo and existing_repost:
            existing_repost.repost_content = caption
            existing_repost.save()
            reposted = True
            message  = 'Repost updated!'

        else:
            return JsonResponse({'success': False, 'error': 'Invalid operation'})

        return JsonResponse({
            'success':      True,
            'reposted':     reposted,
            'repost_count': original_post.reposts.count(),
            'message':      message,
            'caption':      caption,
        })

    except Post.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Post not found'})
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='/')
def follow_user(request, user_id):
    if request.method == 'POST':
        try:
            user_to_follow = User.objects.get(id=user_id)
            current_profile = Profile.objects.get(user=request.user)
            target_profile = Profile.objects.get(user=user_to_follow)

            if target_profile in current_profile.followings.all():
                current_profile.followings.remove(target_profile)
                followed = False
                FollowNotification.objects.filter(
                    from_user=request.user,
                    to_user=user_to_follow
                ).delete()
            else:
                current_profile.followings.add(target_profile)
                followed = True
                if request.user != user_to_follow:
                    FollowNotification.objects.get_or_create(
                        from_user=request.user,
                        to_user=user_to_follow
                    )
            
            current_profile.save()
            
            return JsonResponse({
                'success': True,
                'followed': followed,
                'follower_count': target_profile.followers.count(),
                'following_count': current_profile.followings.count()
            })
            
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required(login_url='/')
def post(request):
    if request.method =='POST':
        content = request.POST.get('content','').strip()
        images = request.FILES.getlist('images')
        audio = request.FILES.get('audio_file')
        video = request.FILES.get('video_file')
        
        mood = request.POST.get('mood', '')
        custom_mood = request.POST.get('custom_mood', '').strip()
        
        mood_emojis = {
            'slay': '💅', 'vibing': '🎵', 'sheesh': '🥶', 'periodt': '⏸️',
            'no-cap': '🎯', 'bussin': '🔥', 'mid': '😐', 'cringe': '😬'
        }
        
        final_mood = custom_mood if custom_mood else mood
        emoji = mood_emojis.get(mood, '✨') if not custom_mood else '✨'
        
        if not content and not images and not audio and not video and final_mood:
            content = f"{emoji} feeling {final_mood}"
        
        if not content and not images and not audio and not video:
            messages.error(request, 'Add something to your post bestie ✨')
            return redirect('post')
        
        new_post = Post.objects.create(
            author=request.user,
            content=content if content else '',
            file=audio if audio else None,
            video_file=video if video else None,
            mood=mood if mood else None,
            custom_mood=custom_mood if custom_mood else None,
            mood_emoji=emoji
        )
        
        for image in images:
            PostImage.objects.create(post=new_post, image=image)
        
        messages.success(request, 'Post dropped successfully! ✨')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'redirect': '/home'})
        return redirect('home')
    
    return render(request, 'post.html')


@login_required(login_url='/')
def editpost(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id, author=request.user)
    image = PostImage.objects.filter(post=post_obj)
    if request.method =='POST':
        content = request.POST.get('comment')
        images = request.FILES.getlist('images')
        if not content and not images:
            return
        post_obj.content=content
        post_obj.save()
        if images:
            for m in images:
                if image:
                   for n in image:
                        n.image=m
                        n.save()
                else:
                    PostImage.objects.create(post=post_obj, image=m)
        return redirect(request.META.get('HTTP_REFERER'))
    context = {
        'post': post_obj,
        'post_id': post_id
    }
    return render(request, 'editpost.html', context)


@login_required(login_url='/')
def like_post(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)

    if request.user in post_obj.likes.all():
        post_obj.likes.remove(request.user)
        Notification.objects.filter(
            recipient=post_obj.author,
            actor=request.user,
            post=post_obj,
            notification_type=Notification.LIKE
        ).delete()
    else:
        post_obj.likes.add(request.user)
        if post_obj.author != request.user:
            Notification.objects.create(
                recipient=post_obj.author,
                actor=request.user,
                post=post_obj,
                notification_type=Notification.LIKE
            )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        likers      = list(post_obj.likes.all()[:3])
        like_count  = post_obj.likes.count()
        is_liked    = request.user in post_obj.likes.all()
        liker_pics  = [_safe_pic_url(u) for u in likers]
        liker_names = [u.username for u in likers]
        return JsonResponse({
            'success':     True,
            'like_count':  like_count,
            'is_liked':    is_liked,
            'liker_pics':  liker_pics,
            'liker_names': liker_names,
        })

    return render(request, 'snippet/post_like.html', {
        'post': post_obj,
        'post_id': post_id
    })


@login_required(login_url='/')
def post_comment(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    post_obj.view += 1
    post_obj.save()
    comments = PostComment.objects.filter(post=post_obj).order_by('-created_at')
    following_ids = []
    if request.user.is_authenticated:
        following_ids = list(Profile.objects.get(user=request.user).followings.values_list('user', flat=True))
    return render(request, 'postcomment.html', {'post': post_obj, 'comments': comments, 'following_ids': following_ids})


@login_required(login_url='/')
def postcomment(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)

    if request.method == 'POST':
        content = request.POST.get('comment')
        image   = request.FILES.get('image')
        audio   = request.FILES.get('audio_file')

        if not content and not image and not audio:
            return HttpResponse(status=204)

        comment = PostComment.objects.create(
            post=post_obj,
            author=request.user,
            comment=content or '',
            image=image,
            file=audio,
        )

        # ── Comment notification ──────────────────────────────────────────
        if post_obj.author != request.user:
            Notification.objects.create(
                recipient=post_obj.author,
                actor=request.user,
                post=post_obj,
                notification_type=Notification.COMMENT,
            )

        # ── Mention notifications (@username in comment text) ─────────────
        if content:
            mentioned_usernames = set(re.findall(r'@(\w+)', content))
            for username in mentioned_usernames:
                try:
                    mentioned_user = User.objects.get(username=username)
                except User.DoesNotExist:
                    continue

                # Skip self-mentions only
                if mentioned_user == request.user:
                    continue
                # NOTE: We intentionally do NOT skip the post author here.
                # A mention (@username) is a distinct event from a comment
                # notification — the post author deserves to know they were
                # specifically called out, even if they also got a comment notif.

                # Create a new mention notification for each comment that
                # contains the @mention. Don't deduplicate across comments —
                # each mention in a new comment is a distinct event.
                # Only skip if this exact comment already triggered one
                # (guards against double-saves).
                already_exists = Notification.objects.filter(
                    recipient=mentioned_user,
                    actor=request.user,
                    post=post_obj,
                    comment=comment,
                    notification_type=Notification.MENTION,
                ).exists()

                if not already_exists:
                    Notification.objects.create(
                        recipient=mentioned_user,
                        actor=request.user,
                        post=post_obj,
                        comment=comment,
                        notification_type=Notification.MENTION,
                    )

        return render(
            request,
            'snippet/comment_list.html',
            {'post': post_obj, 'comment': comment}
        )

    # GET — load comments for modal
    comments = post_obj.comments.all().order_by('-created_at')
    following_ids = list(Profile.objects.get(user=request.user).followings.values_list('user', flat=True))
    return render(
        request,
        'postcomment.html',
        {'post': post_obj, 'comments': comments, 'following_ids': following_ids}
    )


@login_required(login_url='/')
def comment_like(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    if request.user in comment.like.all():
        comment.like.remove(request.user)
    else:
        comment.like.add(request.user)
    return render(request, 'snippet/comment_like.html', {'comment': comment, 'comment_id': comment_id})


@login_required(login_url='/')
def comment_reply(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    context = {'comment': comment, 'comment_id': comment_id}
    return render(request, 'comment_reply.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Profile View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def profile(request, username):
    user    = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked        = False
    viewer_is_blocked = False

    if request.user.is_authenticated and request.user != user:
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()

    if viewer_is_blocked:
        return render(request, 'blocked.html', {'blocked_by': user})

    if is_blocked:
        context = {
            'user': user, 'profile': profile, 'posts': [],
            'current_profile': request.user.profile if request.user.is_authenticated else None,
            'total_view': 0, 'total_like_recieved': 0,
            'total_comments_received': 0, 'mutual_followings': None,
            'mutual_count': 0, 'is_blocked': True,
        }
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(request, 'profile_posts_partial.html', context)
        return render(request, 'profile.html', context)

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved      = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received  = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count      = 0
    if request.user.is_authenticated and request.user != user:
        my_following      = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count      = my_following.filter(followings=profile).count()

    posts = Post.objects.filter(
        author=user, images__isnull=False
    ).prefetch_related('images').distinct()[:30]

    context = {
        'user': user, 'posts': posts, 'profile': profile,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': False,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'profile_posts_partial.html', context)
    return render(request, 'profile.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Update Profile View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def update_profile(request, username):
    user    = request.user
    profile = request.user.profile

    if request.method == 'POST':
        fname    = request.POST.get('fname')
        lname    = request.POST.get('lname')
        phone    = request.POST.get('phone')
        address  = request.POST.get('address')
        location = request.POST.get('location')
        image    = request.FILES.get('image')
        bio      = request.POST.get('bio')
        website  = request.POST.get('website')

        try:
            if fname and lname:
                user.first_name = fname
                user.last_name  = lname
                user.save()

            if phone or address or location or bio or website:
                if phone:    profile.phone    = phone
                if address:  profile.address  = address
                if location: profile.location = location
                if bio:      profile.bio      = bio
                if website:  profile.website  = website
                profile.save()

            if image:
                profile.picture = image
                profile.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'data': {
                        'first_name': user.first_name, 'last_name': user.last_name,
                        'bio': profile.bio, 'phone': profile.phone,
                        'address': profile.address, 'location': profile.location,
                        'picture_url': profile.picture.url, 'website': profile.website,
                    },
                    'message': 'Profile updated successfully!'
                })
            else:
                messages.info(request, 'Profile Updated Successfully')
                return redirect('profile', username=request.user.username)

        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)})
            else:
                messages.error(request, f'Error updating profile: {str(e)}')
                return redirect('profile', username=request.user.username)

    return render(request, 'update_profile.html', {'profile': profile})


# ─────────────────────────────────────────────────────────────────────────────
# Block / Unblock View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def block_user(request, username):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    target_user = get_object_or_404(User, username=username)

    if target_user == request.user:
        return JsonResponse({'success': False, 'error': "You can't block yourself."}, status=400)

    block_record, created = BlockedUser.objects.get_or_create(
        blocker=request.user, blocked=target_user
    )

    if not created:
        block_record.delete()
        return JsonResponse({'success': True, 'action': 'unblocked'})

    request.user.profile.followings.remove(target_user.profile)
    target_user.profile.followings.remove(request.user.profile)
    return JsonResponse({'success': True, 'action': 'blocked'})


# ─────────────────────────────────────────────────────────────────────────────
# Report User View
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def report_user(request, username):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    target_user = get_object_or_404(User, username=username)

    if target_user == request.user:
        return JsonResponse({'success': False, 'error': "You can't report yourself."}, status=400)

    try:
        body   = json.loads(request.body)
        reason = body.get('reason', '').strip()
        note   = body.get('note', '').strip()
    except (json.JSONDecodeError, AttributeError):
        reason = request.POST.get('reason', '').strip()
        note   = request.POST.get('note', '').strip()

    if not reason:
        return JsonResponse({'success': False, 'error': 'Please select a reason.'}, status=400)

    already_reported = UserReport.objects.filter(
        reporter=request.user,
        reported=target_user,
        created_at__gte=timezone.now() - timedelta(hours=24)
    ).exists()

    if already_reported:
        return JsonResponse({
            'success': False,
            'error': 'You already reported this user recently. Our team is reviewing it.'
        })

    UserReport.objects.create(
        reporter=request.user, reported=target_user, reason=reason, note=note,
    )
    return JsonResponse({'success': True})


@login_required(login_url='/')
def profile_videos(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked = False
    if request.user.is_authenticated and request.user != user:
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()
        if viewer_is_blocked:
            return render(request, 'blocked.html', {'blocked_by': user})
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()

    video_posts = Post.objects.filter(
        author=user, video_file__isnull=False
    ).prefetch_related('images')[:30]

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count = 0
    if request.user.is_authenticated and request.user != user:
        my_following = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count = my_following.filter(followings=profile).count()

    context = {
        'user': user, 'profile': profile, 'posts': video_posts,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': is_blocked, 'active_tab': 'videos',
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_videos_partial.html', context)
    return render(request, 'profile.html', context)


def profile_text_posts(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile

    is_blocked = False
    if request.user.is_authenticated and request.user != user:
        viewer_is_blocked = BlockedUser.objects.filter(
            blocker=user, blocked=request.user
        ).exists()
        if viewer_is_blocked:
            return render(request, 'blocked.html', {'blocked_by': user})
        is_blocked = BlockedUser.objects.filter(
            blocker=request.user, blocked=user
        ).exists()

    text_posts = (
        Post.objects.filter(author=user)
        .annotate(image_count=Count('images'))
        .filter(image_count=0)
        .filter(Q(video_file__isnull=True) | Q(video_file=''))
        .filter(Q(file__isnull=True) | Q(file=''))
        .filter(content__isnull=False)
        .exclude(content__exact='')
        .select_related('author', 'author__profile')
        .prefetch_related('likes', 'comments')
        .order_by('-created_at')[:30]
    )

    user_posts = Post.objects.filter(author=user)
    total_view = sum(p.view for p in user_posts)
    total_like_recieved = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received = PostComment.objects.filter(post__author=user).count()

    mutual_followings = None
    mutual_count = 0
    if request.user.is_authenticated and request.user != user:
        my_following = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count = my_following.filter(followings=profile).count()

    for p in text_posts:
        p.liker_data = [
            {'url': _safe_pic_url(u), 'username': u.username}
            for u in p.likes.all()[:3]
        ]

    context = {
        'user': user, 'profile': profile, 'posts': text_posts,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view': total_view, 'total_like_recieved': total_like_recieved,
        'total_comments_received': total_comments_received,
        'mutual_followings': mutual_followings, 'mutual_count': mutual_count,
        'is_blocked': is_blocked, 'active_tab': 'text',
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_text_posts_partial.html', context)
    return render(request, 'profile.html', context)


@login_required
def mark_follow_notifications_read(request):
    if request.method == 'POST':
        updated = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).update(is_read=True)
        return JsonResponse({'success': True, 'updated_count': updated})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def explore_users(request):
    current_profile = get_object_or_404(Profile, user=request.user)

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).count()

    recent_follows = FollowNotification.objects.filter(
        to_user=request.user
    ).select_related('from_user', 'from_user__profile').order_by('-created_at')[:10]

    following_profile_ids = current_profile.followings.values_list('id', flat=True)

    profiles = Profile.objects.exclude(user=request.user).exclude(id__in=following_profile_ids)
    profiles = profiles.annotate(follower_count=Count('followers')).order_by('-follower_count', '-created_at')
    profiles = profiles[:30]

    return render(request, 'explore_users.html', {
        'profiles': profiles,
        'title': 'Explore Users',
        'unread_follow_count': unread_follow_count,
        'recent_follows': recent_follows,
    })


def follow(request, username):
    other_user = get_object_or_404(User, username=username)
    current_profile = request.user.profile
    other_profile = other_user.profile

    if other_profile not in current_profile.followings.all():
        current_profile.followings.add(other_profile)
        messages.info(request, 'Following')
        return redirect(request.META.get('HTTP_REFERER'))
    else:
        current_profile.followings.remove(other_profile)
        messages.info(request, 'unFollowing')
        return redirect(request.META.get('HTTP_REFERER'))


@login_required(login_url='/')
def follower_list(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    followers = profile.followers.all()
    context = {'user': user, 'profile': profile, 'followers': followers}
    return render(request, 'followers_list.html', context)


@login_required(login_url='/')
def following_list(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    followings = profile.followings.all()
    context = {'user': user, 'profile': profile, 'followings': followings}
    return render(request, 'following_list.html', context)


@login_required(login_url='/')
def search(request):
    query = request.GET.get('q', '').strip()
    
    if query:
        SearchHistory.objects.create(user=request.user, query=query)
        users = User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
        recent_searches = SearchHistory.objects.filter(
            user=request.user
        ).exclude(query=query).order_by('-created_at')[:5]
        return render(request, 'search.html', {
            'query': query, 'users': users, 'recent_searches': recent_searches
        })
    
    search_history = SearchHistory.objects.filter(
        user=request.user
    ).order_by('-created_at')[:20]
    return render(request, 'search.html', {'search_history': search_history})


@login_required
def delete_history(request, history_id):
    SearchHistory.objects.filter(id=history_id, user=request.user).delete()
    return redirect('search')


@login_required
def clear_history(request):
    SearchHistory.objects.filter(user=request.user).delete()
    return redirect('search')


@login_required(login_url='/')
def message(request, username):
    receiver = get_object_or_404(User, username=username)
    sender = request.user

    try:
        if sender.profile.has_blocked(receiver.profile) or receiver.profile.has_blocked(sender.profile):
            from django.contrib import messages as _msgs
            _msgs.error(request, 'You cannot view this conversation.')
            return redirect('inbox')
    except Exception:
        pass

    unread_messages = Message.objects.filter(sender=receiver, receiver=sender, is_read=False)
    unread_messages.update(is_read=True)
    
    conversations = Message.objects.filter(
        Q(sender=sender, receiver=receiver) | Q(sender=receiver, receiver=sender)
    ).order_by('created_at')

    from social.models import MessageReaction
    from django.db.models import Count as _Count

    reaction_rows = (
        MessageReaction.objects
        .filter(message__in=conversations)
        .values('message_id', 'emoji')
        .annotate(count=_Count('id'))
    )
    reactions_by_msg = {}
    for row in reaction_rows:
        reactions_by_msg.setdefault(row['message_id'], {})[row['emoji']] = row['count']

    user_reaction_rows = MessageReaction.objects.filter(
        message__in=conversations, user=request.user
    ).values('message_id', 'emoji')
    user_reactions = {r['message_id']: r['emoji'] for r in user_reaction_rows}

    conversations_list = list(conversations)
    for msg in conversations_list:
        msg.reactions_summary = reactions_by_msg.get(msg.id, {})
        my_emoji = user_reactions.get(msg.id)
        msg.reaction_users = [request.user] if my_emoji else []
        msg.my_reaction = my_emoji
    
    grouped_messages = {}
    for msg in conversations_list:
        label = msg.chat_date_label
        grouped_messages.setdefault(label, []).append(msg)
    
    context = {'grouped_messages': grouped_messages, 'receiver': receiver}
    return render(request, 'message.html', context)


@login_required(login_url='/')
def send_message(request, username):
    receiver = get_object_or_404(User, username=username)
    
    if request.method == 'POST':
        try:
            sender_profile   = request.user.profile
            receiver_profile = receiver.profile
            if sender_profile.has_blocked(receiver_profile) or receiver_profile.has_blocked(sender_profile):
                return JsonResponse({'status': 'error', 'message': 'Unable to send message.'}, status=403)
        except Exception:
            pass

        if request.content_type == 'application/json':
            if len(request.body) > 100_000:
                return JsonResponse({'status': 'error', 'message': 'Request too large.'}, status=413)
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Invalid JSON.'}, status=400)
            message_text = str(data.get('message', ''))
            reply_to_id = data.get('reply_to')
        else:
            message_text = request.POST.get('message', '')
            reply_to_id = request.POST.get('reply_to')
        
        file_upload = request.FILES.get('file_upload')

        if message_text and len(message_text) > 5000:
            return JsonResponse({'status': 'error', 'message': 'Message too long. Maximum 5000 characters.'}, status=400)

        if not message_text and not file_upload:
            return JsonResponse({'status': 'success', 'message': 'No content to send'})
        
        file_type = None
        file_name = None
        if file_upload:
            raw_name = file_upload.name or 'file'
            raw_name = os.path.basename(raw_name.replace('\\', '/'))
            raw_name = re.sub(r'[^\w\s\-\.]', '', raw_name).strip()[:100] or 'file'
            file_name = raw_name
            ext = os.path.splitext(file_name)[1].lower()
            ALLOWED_EXTENSIONS = {
                'image':    {'.jpg', '.jpeg', '.png', '.gif'},
                'video':    {'.mp4', '.webm', '.mov', '.avi'},
                'audio':    {'.mp3', '.wav'},
                'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'},
            }
            file_type = next((t for t, exts in ALLOWED_EXTENSIONS.items() if ext in exts), None)
            if not file_type:
                return JsonResponse({'status': 'error', 'message': 'Unsupported file type'}, status=400)
            if file_upload.size > 50 * 1024 * 1024:
                return JsonResponse({'status': 'error', 'message': 'File too large. Maximum size is 50MB.'}, status=400)
        
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id)
                if not (reply_to.sender == request.user or reply_to.receiver == request.user or
                        reply_to.sender == receiver or reply_to.receiver == receiver):
                    reply_to = None
            except Message.DoesNotExist:
                reply_to = None
        
        link_preview = None
        if message_text:
            url_match = re.search(r'https?://[^\s]+', message_text)
            if url_match:
                preview_url = url_match.group(0)
                if _is_safe_url_for_preview(preview_url):
                    try:
                        _headers = {
                            'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
                            'Accept': 'text/html,application/xhtml+xml',
                        }
                        _resp = requests.get(preview_url, headers=_headers, timeout=4, allow_redirects=True, stream=True)
                        _content = b''
                        for _chunk in _resp.iter_content(chunk_size=8192):
                            _content += _chunk
                            if len(_content) > 500_000:
                                break
                        _soup = BeautifulSoup(_content, 'html.parser')

                        def _og(prop):
                            tag = (
                                _soup.find('meta', property=f'og:{prop}')
                                or _soup.find('meta', attrs={'name': f'twitter:{prop}'})
                            )
                            return tag['content'].strip() if tag and tag.get('content') else ''

                        _image = _og('image')
                        if _image and not _image.startswith(('http://', 'https://')):
                            _image = ''

                        link_preview = {
                            'title':       (_og('title') or (_soup.title.string.strip() if _soup.title else ''))[:200],
                            'description': _og('description')[:400],
                            'image':       _image[:500],
                            'domain':      urlparse(_resp.url).netloc.replace('www.', '')[:100],
                            'url':         preview_url,
                        }
                    except Exception:
                        link_preview = None

        msg_obj = Message.objects.create(
            sender=request.user, receiver=receiver,
            conversation=message_text if message_text else '',
            file_type=file_type,
            file=file_upload if file_upload else None,
            reply_to=reply_to,
            link_preview=link_preview,
        )
        
        Message.objects.filter(sender=receiver, receiver=request.user, is_read=False).update(is_read=True)
        
        channel_layer = get_channel_layer()
        user_ids = sorted([request.user.id, receiver.id])
        room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        room_group_name = f"chat_{room_name}"
        
        file_url = msg_obj.file.url if msg_obj.file else None
        
        reply_data = None
        if reply_to:
            reply_data = {
                'message_id': str(reply_to.id),
                'sender': reply_to.sender.username,
                'message': reply_to.conversation,
                'file_type': reply_to.file_type
            }

        sender_avatar = request.user.profile.picture.url if request.user.profile.picture else ''

        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'chat_message',
                'message_id': str(msg_obj.id),
                'sender': request.user.username,
                'sender_avatar': sender_avatar,
                'receiver': receiver.username,
                'message': message_text,
                'file_type': file_type,
                'file_url': file_url,
                'file_name': file_name or '',
                'time': msg_obj.created_at.isoformat(),
                'reply_to': reply_data,
                'link_preview': link_preview,
            }
        )
        
        return JsonResponse({'status': 'success', 'message': 'Message sent', 'message_id': msg_obj.id, 'file_url': file_url})
    
    return redirect('message', username=username)


@login_required(login_url='/')
def delete_message(request, message_id):
    if request.method == 'POST':
        try:
            msg_obj = Message.objects.get(id=message_id)
            if msg_obj.sender != request.user and msg_obj.receiver != request.user:
                return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
            
            channel_layer = get_channel_layer()
            user_ids = sorted([msg_obj.sender.id, msg_obj.receiver.id])
            room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
            room_group_name = f"chat_{room_name}"
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'message_deleted',
                    'message_id': msg_obj.id,
                    'sender': msg_obj.sender.username,
                    'receiver': msg_obj.receiver.username,
                }
            )
            
            msg_obj.delete()
            return JsonResponse({'status': 'success', 'message': 'Message deleted successfully'})
            
        except Message.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Message not found'})
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'An error occurred. Please try again.'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)


@login_required(login_url='/')
def react_to_message(request, message_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    from social.models import MessageReaction

    try:
        msg_obj = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Message not found'}, status=404)

    if request.user not in (msg_obj.sender, msg_obj.receiver):
        return JsonResponse({'status': 'error', 'message': 'Forbidden'}, status=403)

    try:
        body  = json.loads(request.body)
        emoji = body.get('emoji', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    ALLOWED_EMOJIS = {'❤️', '😂', '😮', '😢', '😡', '👍', '🔥', '🎉'}
    if emoji not in ALLOWED_EMOJIS:
        return JsonResponse({'status': 'error', 'message': 'Invalid emoji'}, status=400)

    existing = MessageReaction.objects.filter(message=msg_obj, user=request.user).first()

    if existing:
        if existing.emoji == emoji:
            existing.delete()
            user_reaction = None
        else:
            existing.emoji = emoji
            existing.save()
            user_reaction = emoji
    else:
        MessageReaction.objects.create(message=msg_obj, user=request.user, emoji=emoji)
        user_reaction = emoji

    from django.db.models import Count as _Count
    summary = (
        MessageReaction.objects.filter(message=msg_obj)
        .values('emoji').annotate(count=_Count('id')).order_by('emoji')
    )
    reaction_summary = {row['emoji']: row['count'] for row in summary}

    try:
        user_ids = sorted([msg_obj.sender_id, msg_obj.receiver_id])
        room_group_name = f"chat_dm_{user_ids[0]}_{user_ids[1]}"
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'message_reaction',
                'message_id': msg_obj.id,
                'reactions': reaction_summary,
                'actor': request.user.username,
            }
        )
    except Exception:
        pass

    return JsonResponse({
        'status': 'success',
        'message_id': msg_obj.id,
        'reactions': reaction_summary,
        'user_reaction': user_reaction,
    })


# ── SSRF protection ──────────────────────────────────────────────────────────

_BLOCKED_HOSTS = {'localhost', 'metadata.google.internal'}
_PRIVATE_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]

def _is_safe_url_for_preview(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() in _BLOCKED_HOSTS:
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            for network in _PRIVATE_NETWORKS:
                if ip in network:
                    return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


@login_required(login_url='/')
def fetch_link_preview(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    url = request.GET.get('url', '').strip()
    if not url:
        return JsonResponse({'error': 'No URL provided'}, status=400)

    if not url.startswith(('http://', 'https://')):
        return JsonResponse({'error': 'Invalid URL'}, status=400)

    if not _is_safe_url_for_preview(url):
        return JsonResponse({'error': 'URL not allowed'}, status=400)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; KvibeBot/1.0)',
            'Accept': 'text/html,application/xhtml+xml',
        }
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True, stream=True)
        content = b''
        for chunk in resp.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > 500_000:
                break

        soup = BeautifulSoup(content, 'html.parser')

        def og(prop):
            tag = (
                soup.find('meta', property=f'og:{prop}')
                or soup.find('meta', attrs={'name': f'twitter:{prop}'})
                or soup.find('meta', attrs={'name': prop})
            )
            return tag['content'].strip() if tag and tag.get('content') else ''

        title       = og('title') or (soup.title.string.strip() if soup.title else '')
        description = og('description')
        image       = og('image')
        domain      = urlparse(resp.url).netloc.replace('www.', '')

        if image and not image.startswith(('http://', 'https://')):
            image = ''

        return JsonResponse({
            'title': title[:200], 'description': description[:400],
            'image': image[:500], 'domain': domain[:100], 'url': url,
        })
    except Exception:
        return JsonResponse({'title': '', 'description': '', 'image': '', 'domain': '', 'url': url})


# ─────────────────────────────────────────────────────────────────────────────
# Notification Views
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def open_notification(request, post_id, notification_type):
    post_obj = get_object_or_404(Post, post_id=post_id)
    Notification.objects.filter(
        recipient=request.user,
        post=post_obj,
        notification_type=notification_type,
        is_read=False
    ).update(is_read=True)
    return redirect('post_comment', post_id=post_obj.post_id)


@login_required(login_url='/')
def notification_list(request):
    """
    Renders the notification page.
    Marks all post-based notifications read on page load.
    Follow notifications are marked read by mark_follow_notifications_read or
    mark_all_notifications_read.
    """
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True)
    return render(request, 'notification.html')


def notification_partial(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        unread_follow_count = FollowNotification.objects.filter(
            to_user=request.user, is_read=False
        ).count()
    else:
        unread_count = 0
        unread_follow_count = 0
    return render(request, 'snippet/notification_count.html', {
        'unread_notifications_count': unread_count,
        'unread_follow_count': unread_follow_count,
    })


def inbox_partial(request):
    return render(request, 'snippet/inbox_count.html')


@login_required
@require_POST
def delete_notification_group(request):
    """
    Deletes either:
      • a group of post-based notifications  → body: {post_id, notification_type}
      • a single follow notification          → body: {follow_id}

    The recipient/to_user check ensures users can only delete their own data.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    # ── Follow notification ───────────────────────────────────────────────────
    follow_id = data.get('follow_id')
    if follow_id is not None:
        try:
            follow_id = int(follow_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid follow_id'}, status=400)

        deleted_count, _ = FollowNotification.objects.filter(
            pk=follow_id,
            to_user=request.user,  # security: own notifications only
        ).delete()

        return JsonResponse({'status': 'success', 'deleted_count': deleted_count})

    # ── Post-based notification group ─────────────────────────────────────────
    post_id           = data.get('post_id')
    notification_type = data.get('notification_type')
    actor_id          = data.get('actor_id')  # required for mention dismissal

    if not post_id or not notification_type:
        return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)

    # Validate UUID to prevent injection
    try:
        post_uuid = uuid_module.UUID(str(post_id))
    except (ValueError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid post_id'}, status=400)

    # Whitelist notification types
    VALID_TYPES = {'like', 'comment', 'repost', 'mention'}
    if notification_type not in VALID_TYPES:
        return JsonResponse({'status': 'error', 'message': 'Invalid notification_type'}, status=400)

    qs = Notification.objects.filter(
        recipient=request.user,  # security: own notifications only
        post_id=post_uuid,
        notification_type=notification_type,
    )

    # For mention notifications the group_id includes the actor_id —
    # only delete notifications from that specific actor, not all mentions.
    if notification_type == 'mention' and actor_id:
        try:
            qs = qs.filter(actor_id=int(actor_id))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid actor_id'}, status=400)

    deleted_count, _ = qs.delete()

    return JsonResponse({
        'status': 'success',
        'deleted_count': deleted_count,
        'message': f'Deleted {deleted_count} notification(s)',
    })


@login_required
@require_POST
def mark_all_notifications_read(request):
    """Marks all unread post-based AND follow notifications as read."""
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True)
    FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).update(is_read=True)
    return JsonResponse({'status': 'success'})


# ─────────────────────────────────────────────────────────────────────────────
# Inbox
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='/')
def inbox(request):
    conversations = {}
    all_messages = Message.objects.filter(
        Q(sender=request.user) | Q(receiver=request.user)
    )
    conversation_partners = set()
    for msg in all_messages:
        other_user = msg.sender if msg.sender != request.user else msg.receiver
        conversation_partners.add(other_user)
    
    for partner in conversation_partners:
        last_message = Message.objects.filter(
            Q(sender=request.user, receiver=partner) |
            Q(sender=partner, receiver=request.user)
        ).order_by('-created_at').first()
        
        if last_message:
            unread_count = Message.objects.filter(
                sender=partner, receiver=request.user, is_read=False
            ).count()
            conversations[partner] = {'last_message': last_message, 'unread_count': unread_count}
    
    sorted_conversations = sorted(
        conversations.items(),
        key=lambda x: x[1]['last_message'].created_at,
        reverse=True
    )
    
    contacts = conversation_partners
    return render(request, 'inbox.html', {
        'conversations': dict(sorted_conversations),
        'contacts': contacts,
        'user': request.user
    })


@login_required
def channel_create(request):
    if request.method == 'POST':
        name  = request.POST.get('name')
        about = request.POST.get('about')
        icon  = request.FILES.get('icon')
        new_channel = Channel.objects.create(
            channel_owner=request.user,
            channel_name=name,
            about=about,
            image=icon if icon else 'male.png'
        )
        new_channel.subscriber.add(request.user)
        return redirect('channel', channel_id=new_channel.channel_id)

    followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')

    followed_list = []
    total_unread = 0
    
    for c in followed_channels:
        unread = c.unread_count_for_user(request.user)
        total_unread += unread
        last_msg = c.channel_messages.order_by('-created_at').first()
        msg_type = 'text'
        if last_msg:
            if last_msg.file_type == 'audio':   msg_type = 'audio'
            elif last_msg.file_type == 'video': msg_type = 'video'
            elif last_msg.file_type == 'image': msg_type = 'image'
        followed_list.append({
            'channel': c, 'unread_count': unread,
            'last_message': last_msg.message if last_msg else "No messages yet",
            'last_time': last_msg.created_at if last_msg else None,
            'message_type': msg_type
        })

    unfollowed_channels = Channel.objects.exclude(subscriber=request.user).order_by('-created_at')
    context = {
        'followed_list': followed_list,
        'unfollowed_channels': unfollowed_channels,
        'total_followed_unread': total_unread,
    }
    return render(request, 'channel_create.html', context)


def follow_channel(request, channel_id):
    channel = get_object_or_404(Channel, channel_id=channel_id)
    if request.user not in channel.subscriber.all():
        channel.subscriber.add(request.user)
    else:
        channel.subscriber.remove(request.user)
    return redirect(request.META.get('HTTP_REFERER'))


@login_required
def channel(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    
    if request.user in channel_obj.blocked_users.all():
        return redirect('home')

    ChannelUserLastSeen.objects.update_or_create(
        channel=channel_obj, user=request.user,
        defaults={'last_seen_at': timezone.now()}
    )
    
    channel_messages_qs = ChannelMessage.objects.filter(channel=channel_obj).order_by('created_at')
    grouped_messages = {}
    for msg in channel_messages_qs:
        date_label = msg.chat_date_label
        if date_label not in grouped_messages:
            grouped_messages[date_label] = []
        grouped_messages[date_label].append(msg)
    
    subscribed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(ch.unread_count_for_user(request.user) for ch in subscribed_channels)
    
    notifications = request.user.notifications.filter(is_read=False)
    
    context = {
        'channel': channel_obj,
        'grouped_messages': grouped_messages,
        'channel_id': str(channel_id),
        'total_unread': total_unread,
        'notifications': notifications,
        'is_admin': channel_obj.is_user_admin(request.user),
        'is_owner': channel_obj.channel_owner == request.user
    }
    return render(request, 'channel.html', context)


@login_required
def channel_message(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    
    if channel_obj.is_broadcast_only and request.user != channel_obj.channel_owner:
        return JsonResponse({'status': 'error', 'message': 'Only admins can post in this channel.'}, status=403)

    if request.method == 'POST':
        message_text = request.POST.get('message', '')
        file_upload  = request.FILES.get('file_upload')
        reply_to_id  = request.POST.get('reply_to')

        file_type = None
        if file_upload:
            _ext = os.path.splitext(file_upload.name or '')[1].lower()
            _ALLOWED = {
                'image':    {'.jpg', '.jpeg', '.png', '.gif'},
                'video':    {'.mp4', '.webm', '.mov', '.avi'},
                'audio':    {'.mp3', '.wav'},
                'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'},
            }
            file_type = next((t for t, exts in _ALLOWED.items() if _ext in exts), None)
            if not file_type:
                return JsonResponse({'status': 'error', 'message': 'Unsupported file type'}, status=400)
            if file_upload.size > 50 * 1024 * 1024:
                return JsonResponse({'status': 'error', 'message': 'File too large. Maximum size is 50MB.'}, status=400)

        channel_msg = ChannelMessage.objects.create(
            channel=channel_obj,
            author=request.user,
            message=message_text if message_text else '',
            file_type=file_type,
            file=file_upload,
            reply_to_id=reply_to_id if reply_to_id else None
        )

        layer = get_channel_layer()
        group_name = f'channel_{channel_id}'
        file_url = channel_msg.file.url if channel_msg.file else None
        
        reply_data = None
        if channel_msg.reply_to:
            reply_data = {
                'author': channel_msg.reply_to.author.username,
                'message': channel_msg.reply_to.message[:50] if channel_msg.reply_to.message else "Media file"
            }

        async_to_sync(layer.group_send)(
            group_name,
            {
                'type': 'channel_message',
                'author': channel_msg.author.username,
                'message': channel_msg.message,
                'file_type': file_type,
                'file_url': file_url,
                'time': channel_msg.created_at.isoformat(),
                'message_id': str(channel_msg.channelmessage_id),
                'reply_to': reply_data,
            }
        )
        
        subscribers = channel_obj.subscriber.exclude(id=request.user.id)
        for subscriber in subscribers:
            unread_count = channel_obj.unread_count_for_user(subscriber)
            user_group_name = f'user_{subscriber.id}_channels'
            async_to_sync(layer.group_send)(
                user_group_name,
                {
                    'type': 'unread_update',
                    'channel_id': str(channel_obj.channel_id),
                    'unread_count': unread_count,
                    'channel_name': channel_obj.channel_name,
                    'message_preview': message_text[:30] if message_text else "New media message",
                }
            )
        
        return JsonResponse({'status': 'success', 'message_id': str(channel_msg.channelmessage_id)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


@login_required
def update_channel(request, channel_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    if request.user != channel_obj.channel_owner:
        return redirect('channel', channel_id=channel_id)

    if request.method == 'POST':
        channel_obj.channel_name = request.POST.get('name', channel_obj.channel_name)
        channel_obj.about = request.POST.get('about', channel_obj.about)
        broadcast = request.POST.get('broadcast')
        channel_obj.is_broadcast_only = (broadcast == 'true')
        if request.FILES.get('image'):
            channel_obj.image = request.FILES.get('image')
        channel_obj.save()
        
    return redirect('channel', channel_id=channel_id)


@login_required
def manage_member(request, channel_id, user_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    
    if not channel_obj.is_user_admin(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            target_user = get_object_or_404(User, id=user_id)
            
            is_target_admin = channel_obj.admins.filter(id=target_user.id).exists()
            is_target_owner = (target_user == channel_obj.channel_owner)

            if (is_target_admin or is_target_owner) and request.user != channel_obj.channel_owner:
                return JsonResponse({
                    'success': False,
                    'message': 'Permission denied: Only the owner can remove admins.'
                }, status=403)
            
            if action in ('remove', 'block'):
                channel_obj.subscriber.remove(target_user)
                channel_obj.admins.remove(target_user)
                if action == 'block':
                    channel_obj.blocked_users.add(target_user)
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'message': 'Unknown action'}, status=400)

        except (json.JSONDecodeError, User.DoesNotExist):
            return JsonResponse({'success': False, 'message': 'Invalid request data'}, status=400)

    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)


@login_required
def toggle_admin(request, channel_id, user_id):
    channel_obj = get_object_or_404(Channel, channel_id=channel_id)
    if request.user != channel_obj.channel_owner:
        return JsonResponse({'success': False}, status=403)

    target_user = get_object_or_404(User, id=user_id)
    if channel_obj.admins.filter(id=target_user.id).exists():
        channel_obj.admins.remove(target_user)
    else:
        channel_obj.admins.add(target_user)
    return JsonResponse({'success': True})


@login_required
def channelmessage_like(request, channelmessage_id):
    channelmessage = get_object_or_404(ChannelMessage, channelmessage_id=channelmessage_id)
    if request.user not in channelmessage.like.all():
        channelmessage.like.add(request.user)
        liked = True
    else:
        channelmessage.like.remove(request.user)
        liked = False
    return JsonResponse({'liked': liked, 'like_count': channelmessage.like.count()})


# ======= Marketplace =======

@login_required(login_url='/')
def market(request):
    category = request.GET.get('category', 'all')
    if category == 'all':
        products = Market.objects.all().order_by('-posted_on')
    else:
        products = Market.objects.filter(product_category=category).order_by('-posted_on')

    highest_price = products.aggregate(Max('product_price'))['product_price__max']
    lowest_price  = products.aggregate(Min('product_price'))['product_price__min']

    if request.method == 'POST' and 'form_type' in request.POST:
        if request.POST['form_type'] == 'marketplace':
            product_owner       = request.user
            product_name        = request.POST.get('product_name')
            product_price       = request.POST.get('product_price')
            product_location    = request.POST.get('location', 'Ilorin, Nigeria')
            product_description = request.POST.get('description')
            product_availability= request.POST.get('availability', 'Single Item')
            product_category    = request.POST.get('category')
            product_condition   = request.POST.get('product_condition', 'New')
            whatsapp_number     = request.POST.get('whatsapp_number')

            if not all([product_name, product_price, product_category, product_description, whatsapp_number]):
                messages.error(request, 'Please fill in all required fields.')
                return redirect('market')

            product_images = request.FILES.getlist('images')
            if len(product_images) == 0:
                messages.error(request, 'Please upload at least one image.')
                return redirect('market')

            product = Market.objects.create(
                product_owner=product_owner, product_name=product_name,
                product_price=product_price, product_location=product_location,
                product_description=product_description,
                product_availability=product_availability,
                product_category=product_category, product_condition=product_condition,
                whatsapp_number=whatsapp_number
            )

            for image in product_images[:5]:
                MarketImage.objects.create(product=product, product_image=image)

            messages.success(request, 'Product Added Successfully', extra_tags='marketplace_success')
            return redirect('market')

    context = {
        'products': products,
        'highest_price': highest_price or 0,
        'lowest_price':  lowest_price  or 0,
    }
    return render(request, 'marketplace.html', context)


@login_required(login_url='/')
def product_detail(request, product_id):
    product = get_object_or_404(Market, product_id=product_id)
    if product.views_count is None:
        product.views_count = 0
    product.views_count += 1
    product.save()

    images = product.images.all()
    related_products = Market.objects.filter(
        product_category=product.product_category
    ).exclude(product_id=product_id)[:4]
    seller_profile = get_object_or_404(Profile, user=product.product_owner)

    context = {
        'product': product, 'images': images,
        'related_products': related_products, 'seller': seller_profile,
    }
    return render(request, 'product_details.html', context)


def spotlight_view(request):
    spotlight_posts = Post.objects.filter(
        Q(video_file__isnull=False) & ~Q(video_file='') |
        Q(is_repost=True, original_post__video_file__isnull=False) & ~Q(original_post__video_file='')
    ).order_by('?').select_related('author', 'original_post')
    return render(request, 'spotlight.html', {'posts': spotlight_posts})


@require_POST
def track_share(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    if post_obj.share is None:
        post_obj.share = 0
    post_obj.share += 1
    post_obj.save()
    return JsonResponse({'success': True, 'new_count': post_obj.share})


def get_location(request, username):
    user = Profile.objects.get(user__username=username)
    return JsonResponse({'lat': user.latitude, 'lng': user.longitude})


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request, exception):
    return render(request, '500.html', status=500)


def logout(request):
    if request.user.is_authenticated:
        try:
            from social.models import Profile
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            Profile.mark_user_offline(request.user.id)
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'online_status_group',
                {'type': 'user_status_event', 'user_id': request.user.id, 'status': 'Offline'}
            )
        except Exception:
            pass
    auth.logout(request)
    messages.info(request, 'Logout Successfully')
    return redirect('/')


@require_POST
def set_offline(request):
    logger = logging.getLogger(__name__)
    try:
        user_id = int(request.POST.get('user_id', 0))
    except (ValueError, TypeError):
        return HttpResponse(status=400)

    if not request.user.is_authenticated or request.user.id != user_id:
        return HttpResponse(status=403)

    try:
        Profile.mark_user_offline(user_id)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'online_status_group',
            {'type': 'user_status_event', 'user_id': user_id, 'status': 'Offline'}
        )
    except Exception:
        logger.exception('set_offline: failed to mark user %s offline', user_id)

    return HttpResponse(status=204)


@login_required
@require_POST
def add_comment_reply(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    reply_text = request.POST.get('reply_text', '').strip()
    
    if reply_text:
        reply = CommentReply.objects.create(
            comment=comment, author=request.user, reply_text=reply_text
        )
        return render(request, 'snippet/comment_replies.html', {'replies': [reply]})
    
    return JsonResponse({'error': 'Reply text is required'}, status=400)


@login_required
@require_POST
def like_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id)
    if request.user in reply.like.all():
        reply.like.remove(request.user)
        liked = False
    else:
        reply.like.add(request.user)
        liked = True
    return JsonResponse({'liked': liked, 'likes_count': reply.like.count()})


@login_required
@require_POST
def edit_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id, author=request.user)
    new_text = request.POST.get('reply_text', '').strip()
    if new_text:
        reply.reply_text = new_text
        reply.is_edited = True
        reply.save()
        return render(request, 'snippet/reply_content.html', {'reply': reply})
    return JsonResponse({'success': False, 'error': 'Reply text is required'}, status=400)


@login_required
@require_POST
def delete_reply(request, reply_id):
    reply = get_object_or_404(CommentReply, reply_id=reply_id, author=request.user)
    reply.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/')
def comments_poll(request, post_id):
    post_obj = get_object_or_404(Post, post_id=post_id)
    after_str = request.GET.get('after', '')
    after_dt = None
    if after_str:
        from django.utils.dateparse import parse_datetime
        after_dt = parse_datetime(after_str)
        if after_dt is None:
            try:
                from dateutil.parser import parse as du_parse
                after_dt = du_parse(after_str)
            except Exception:
                after_dt = None

    qs = PostComment.objects.filter(post=post_obj)
    if after_dt:
        qs = qs.filter(created_at__gt=after_dt)

    new_comments = (
        qs.select_related('author', 'author__profile')
        .prefetch_related('like', 'replies', 'replies__author', 'replies__author__profile')
        .order_by('-created_at')
    )

    if not new_comments.exists():
        return HttpResponse(status=204)

    html_parts = []
    for comment in new_comments:
        html_parts.append(
            render_to_string(
                'snippet/comment_list.html',
                {'comment': comment, 'request': request, 'user': request.user},
                request=request,
            )
        )
    return HttpResponse(''.join(html_parts))


@login_required(login_url='/')
@login_required(login_url='login')
def hashtag_view(request, tag_name):
    from django.db.models import Q

    profile = request.user.profile

    posts = Post.objects.filter(
        Q(content__icontains=f'#{tag_name}') |
        Q(original_post__content__icontains=f'#{tag_name}')
    ).order_by('-created_at').select_related(
        'author', 'author__profile',
        'original_post', 'original_post__author', 'original_post__author__profile'
    ).prefetch_related('likes', 'reposts', 'images')

    post_count = posts.count()

    all_hashtags = {}
    for p in posts[:200]:
        content = p.original_post.content if p.is_repost and p.original_post else p.content
        if content:
            for tag in extract_hashtags(content):
                if tag.lower() != tag_name.lower():
                    all_hashtags[tag] = all_hashtags.get(tag, 0) + 1

    related_hashtags = sorted(all_hashtags.items(), key=lambda x: x[1], reverse=True)[:10]

    following_ids = list(profile.followings.values_list('user', flat=True))
    sidebar_followings = profile.followings.select_related('user', 'user__profile').all()
    sidebar_followers  = profile.followers.select_related('user', 'user__profile').all()

    hashtag_counts = {}
    recent_posts = Post.objects.filter(content__isnull=False).order_by('-created_at')[:200]
    for p in recent_posts:
        if p.content:
            for tag in extract_hashtags(p.content):
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
    trending_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user, is_read=False
    ).count()
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()

    return render(request, 'hashtag_view.html', {
        'tag_name': tag_name,
        'posts': posts,
        'post_count': post_count,
        'related_hashtags': related_hashtags,
        'following_ids': following_ids,
        'sidebar_followings': sidebar_followings,
        'sidebar_followers': sidebar_followers,
        'trending_hashtags': trending_hashtags,
        'unread_follow_count': unread_follow_count,
        'unread_notifications_count': unread_notifications_count,
    })


# ─── Online Status API ────────────────────────────────────────────────────────

@login_required
def online_status_api(request, user_id):
    try:
        from social.models import Profile
        profile_obj = Profile.objects.get(user__id=user_id)
        return JsonResponse({'is_online': profile_obj.is_online})
    except Profile.DoesNotExist:
        return JsonResponse({'is_online': False})
