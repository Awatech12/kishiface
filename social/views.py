from django.shortcuts import render, redirect, get_object_or_404, HttpResponse 
from .models import FollowNotification
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, Post, PostImage,ChannelUserLastSeen,Story, PostComment, Message, Notification, ChannelMessage, Channel, Market, MarketImage, SearchHistory
from django.db.models import Q
from django.db.models import Count, Max, Min
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time, json
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
import random
from django.views.decorators.csrf import csrf_exempt
from django.contrib.contenttypes.models import ContentType

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

@login_required(login_url='/')
def home(request):
    profile = Profile.objects.get(user=request.user)
    following = profile.followings.values_list('user', flat=True)
    
    # Get channel data
    followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')
    
    followed_list = []
    total_unread = 0
    
    for channel in followed_channels:
        unread = channel.unread_count_for_user(request.user)
        total_unread += unread
        
        # Get the actual last message object
        last_msg = channel.channel_messages.order_by('-created_at').first()
        
        # Determine the message type for the initial page load icons
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
    
    # Get data - include reposts from followed users
    posts = Post.objects.filter(
        Q(author__in=following) | 
        Q(author=request.user) |
        Q(is_repost=True, author__in=following)  # Include reposts by followed users
    ).order_by('?')
    
    products = list(Market.objects.exclude(product_owner_id=request.user.id).order_by('?'))
    users = list(User.objects.exclude(id__in=following).exclude(id=request.user.id).order_by('?'))
    user_products = Market.objects.filter(product_owner_id=request.user.id).order_by('-posted_on')
    
    # Get unread follow notifications count
    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user,
        is_read=False
    ).count()
    
    # Get unread notifications count
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()
    
    # ===== GET INSTAGRAM-STYLE STORIES (ONE PER USER) =====
    from django.utils import timezone
    from datetime import timedelta
    
    # Get active stories from last 24 hours
    twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
    
    # Get all active stories from followed users and yourself
    all_stories = Story.objects.filter(
        Q(author__in=following) | Q(author=request.user),
        created_at__gte=twenty_four_hours_ago,
        is_active=True
    ).select_related('author', 'author__profile').order_by('-created_at')
    
    # Filter to show only latest story per user (like Instagram)
    seen_users = set()
    active_stories = []
    
    # First, get the current user's story (if exists) and put it first
    user_story = None
    other_stories = []
    
    for story in all_stories:
        if story.author.id not in seen_users:
            if story.author == request.user:
                user_story = story
            else:
                other_stories.append(story)
            seen_users.add(story.author.id)
    
    # Add user's story first, then other stories
    if user_story:
        active_stories.append(user_story)
    active_stories.extend(other_stories)
    
    # Limit to show maximum 10 stories in the carousel
    active_stories = active_stories[:10]
    
    # Check if there are any unviewed stories (for UI indicators)
    user_has_unviewed = False
    for story in active_stories:
        if story.author != request.user and request.user not in story.viewers.all():
            user_has_unviewed = True
            break
    
    # Show stories section if there are stories or user can create one
    stories_available = len(active_stories) > 0
    
    # ===== BUILD FEED =====
    feed = []
    
    if not following:  # New user - hasn't followed anyone yet
        # Always show welcome message for new users
        feed.append({'type': 'welcome'})
        
        # Then add some user suggestions (up to 3)
        if users:
            feed += [{'type': 'user_suggestion', 'data': u} for u in users[:3]]
        
        # Then add some marketplace products (up to 2)
        if products:
            feed += [{'type': 'product', 'data': p} for p in products[:2]]
    
    else:  # Existing user - already follows people
        for i, post in enumerate(posts, 1):
            feed.append({'type': 'post', 'data': post})
            if i % 2 == 0:
                if i % 4 == 0 and products:
                    feed.append({'type': 'product', 'data': products.pop(0)})
                elif i % 4 == 2 and users:
                    feed.append({'type': 'user_suggestion', 'data': users.pop(0)})
    
    return render(request, 'home.html', {
        'posts_with_ads': feed,
        'products': products[:5],
        'user_products': user_products[:6],
        'followed_list': followed_list[:8],  # Only show first 8 channels
        'unread_follow_count': unread_follow_count,
        'unread_notifications_count': unread_notifications_count,
        'users': users[:3],  # For right sidebar suggestions
        'active_stories': active_stories,
        'stories_available': stories_available,
        'user_has_unviewed_stories': user_has_unviewed,
    })
    

from django.views.decorators.http import require_POST
@csrf_exempt
@require_POST
def repost_post(request, post_id):
    """Handle reposting a post"""
    try:
        original_post = Post.objects.get(post_id=post_id)
        user = request.user
        
        # Parse JSON data
        import json
        data = json.loads(request.body)
        caption = data.get('caption', '').strip()
        undo = data.get('undo', False)
        
        # Check if user has already reposted this
        existing_repost = Post.objects.filter(
            author=user, 
            is_repost=True, 
            original_post=original_post
        ).first()
        
        if undo and existing_repost:
            # User wants to undo repost
            existing_repost.delete()
            original_post.reposts.remove(user)
            reposted = False
            message = "Repost removed"
        elif not undo and not existing_repost:
            # Create a new repost
            repost = Post.objects.create(
                author=user,
                is_repost=True,
                original_post=original_post,
                repost_content=caption,
                content=""  # Empty content for repost
            )
            # Add to reposts count
            original_post.reposts.add(user)
            reposted = True
            message = "Post reposted successfully!"
        elif not undo and existing_repost:
            # Update existing repost caption
            existing_repost.repost_content = caption
            existing_repost.save()
            reposted = True
            message = "Repost updated!"
        else:
            return JsonResponse({'success': False, 'error': 'Invalid operation'})
        
        # Get updated counts
        repost_count = original_post.reposts.count()
        
        return JsonResponse({
            'success': True,
            'reposted': reposted,
            'repost_count': repost_count,
            'message': message,
            'caption': caption  # Return the caption
        })
        
    except Post.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Post not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def follow_user(request, user_id):
    if request.method == 'POST':
        try:
            # Get the user to follow
            user_to_follow = User.objects.get(id=user_id)
            
            # Get current user's profile
            current_profile = Profile.objects.get(user=request.user)
            
            # Get target user's profile
            target_profile = Profile.objects.get(user=user_to_follow)
            
            # Check if already following
            if target_profile in current_profile.followings.all():
                # Unfollow
                current_profile.followings.remove(target_profile)
                followed = False
                
                # Delete follow notification if exists
                FollowNotification.objects.filter(
                    from_user=request.user,
                    to_user=user_to_follow
                ).delete()
            else:
                # Follow
                current_profile.followings.add(target_profile)
                followed = True
                
                # Create follow notification (only create if not self)
                if request.user != user_to_follow:
                    FollowNotification.objects.get_or_create(
                        from_user=request.user,
                        to_user=user_to_follow
                    )
            
            # Save the profile
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


    
def post(request):
    if request.method =='POST':
        content = request.POST.get('content','').strip()
        images = request.FILES.getlist('images')
        audio = request.FILES.get('audio_file')
        video = request.FILES.get('video_file')
        if not content and not images and not audio and not video:
            return 
        post = Post.objects.create(
            author = request.user,
            content = content if content else '',
            file = audio if audio else None,
            video_file = video if video else None
        )
        for image in images:
            PostImage.objects.create(post=post, image=image)
        
        messages.success(request, 'Post Successfully Shared')
        return redirect('home')
    

    return render(request, 'post.html')

@login_required(login_url='/')
def editpost(request, post_id):
    post = get_object_or_404(Post, post_id=post_id, author=request.user)
    image = PostImage.objects.filter(post=post)
    if request.method =='POST':
        content = request.POST.get('comment')
        images = request.FILES.getlist('images')
        if not content and not images:
            return
        post.content=content
        post.save()
        if images:
            for m in images:
                if image:
                   for n in image:
                        n.image=m
                        n.save()
                else:
                    PostImage.objects.create(post=post, image=m)
        return redirect(request.META.get('HTTP_REFERER'))
    context = {
        'post':post,
        'post_id':post_id
    }
    return render(request, 'editpost.html', context)
        
@login_required(login_url='/')
def like_post(request, post_id):
    post = get_object_or_404(Post, post_id=post_id)

    if request.user in post.likes.all():
        post.likes.remove(request.user)

        # Remove like notification on unlike
        Notification.objects.filter(
            recipient=post.author,
            actor=request.user,
            post=post,
            notification_type='like'
        ).delete()

    else:
        post.likes.add(request.user)

        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                actor=request.user,
                post=post,
                notification_type='like'
            )

    return render(request, 'snippet/post_like.html', {
        'post': post,
        'post_id': post_id
    })

       

@login_required(login_url='/')
def post_comment(request, post_id):
    post=get_object_or_404(Post, post_id=post_id)
    post.view +=1
    post.save()
    comments=PostComment.objects.filter(post=post).order_by('-created_at')

    return render(request, 'postcomment.html', {'post':post, 'comments': comments})


@login_required(login_url='/')
def commentpopup(request, post_id):
    post=get_object_or_404(Post, post_id=post_id)
    
    comments=PostComment.objects.filter(post=post).order_by('-created_at')
    return render(request, 'commentpopup.html', {'post':post, 'comments': comments})
@login_required(login_url='/')
def postcomment(request, post_id):
    post = get_object_or_404(Post, post_id=post_id)

    if request.method == 'POST':
        content = request.POST.get('comment')
        image = request.FILES.get('image')
        audio = request.FILES.get('audio_file')

        # If nothing was submitted, return an empty successful response
        if not content and not image and not audio:
            return HttpResponse(status=204) # 204 No Content

        comment = PostComment.objects.create(
            post=post,
            author=request.user,
            comment=content or "",
            image=image,
            file=audio
        )
      
        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                actor=request.user,
                post=post,
                notification_type='comment'
            )

        # Return just the new comment (used by HTMX 'afterbegin')
        return render(
            request,
            'snippet/comment_list.html',
            {'post': post, 'comment': comment}
        )

    # --- HANDLE GET REQUEST (Modal loading) ---
    # This fetches all existing comments when you open the modal
    comments = post.comments.all().order_by('-created_at')
    
    return render(
        request, 
        'postcomment.html', # Or the specific template fragment containing the list
        {'post': post, 'comments': comments}
    )
def comment_like(request, comment_id):
    comment=get_object_or_404(PostComment, comment_id=comment_id)
    if request.user in comment.like.all():
        comment.like.remove(request.user)
    else:
        comment.like.add(request.user)
    return render(request, 'snippet/comment_like.html', {'comment':comment, 'comment_id':comment_id})

@login_required(login_url='/')
def comment_reply(request, comment_id):
    comment = get_object_or_404(PostComment, comment_id=comment_id)
    context = {
        'comment': comment,
        'comment_id': comment_id
    }
    return render(request, 'comment_reply.html', context)
@login_required(login_url='/')
def profile(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    total_posts = Post.objects.filter(author=user)
    total_view = 0
    for post in total_posts:
        total_view +=post.view

    user_posts = Post.objects.filter(author=user)
    
    total_like_recieved = user_posts.aggregate(total=Count('likes'))['total'] or 0
    total_comments_received = PostComment.objects.filter(post__author = user).count() 

    mutual_followings = None
    mutual_count = 0
    if request.user.is_authenticated and request.user !=user:
        my_following = request.user.profile.followings.all()
        mutual_followings = my_following.filter(followings=profile)[:3]
        mutual_count = my_following.filter(followings=profile).count()
        
    # Get ONLY image posts for the Posts tab
    posts = Post.objects.filter(
        author=user,
        images__isnull=False
    ).prefetch_related('images').distinct()[:30]
    
    context = {
        'user': user,
        'posts': posts,
        'profile': profile,
        'current_profile': request.user.profile if request.user.is_authenticated else None,
        'total_view':total_view,
        'total_like_recieved':total_like_recieved,
        'total_comments_received':total_comments_received,
        'mutual_followings':mutual_followings,
        'mutual_count':mutual_count

    }
    
    # Check if this is an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'profile_posts_partial.html', context)
    
    return render(request, 'profile.html', context)

def profile_videos(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    
    # Get video posts
    video_posts = Post.objects.filter(
        author=user,
        video_file__isnull=False
    ).prefetch_related('images')[:30]
    
    context = {
        'user': user,
        'profile': profile,
        'posts': video_posts,
    }
    
    # Always return partial for AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_videos_partial.html', context)
    
    # For direct access, return full page with video posts
    context['posts'] = video_posts
    return render(request, 'profile.html', context)

def profile_audios(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    
    # Get audio posts
    audio_posts = Post.objects.filter(
        author=user,
        file__isnull=False
    ).prefetch_related('images')[:30]
    
    context = {
        'user': user,
        'profile': profile,
        'posts': audio_posts,
    }
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_audios_partial.html', context)
    
    context['posts'] = audio_posts
    return render(request, 'profile.html', context)

def profile_text_posts(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    
    # Get text posts
    text_posts = Post.objects.filter(
        author=user,
        images__isnull=True,
        video_file__isnull=True,
        file__isnull=True
    ).exclude(content='').filter(content__isnull=False)[:30]
    
    context = {
        'user': user,
        'profile': profile,
        'posts': text_posts,
    }
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'profile_text_posts_partial.html', context)
    
    context['posts'] = text_posts
    return render(request, 'profile.html', context)

@login_required(login_url='/')
def update_profile(request, username):
    user = request.user
    profile = request.user.profile
    
    if request.method == 'POST':
        fname = request.POST.get('fname')
        lname = request.POST.get('lname')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        location = request.POST.get('location')
        image = request.FILES.get('image')
        bio = request.POST.get('bio')
        website = request.POST.get('website')
        
        try:
            if fname and lname:
                user.first_name = fname
                user.last_name = lname
                user.save()
            
            if phone or address or location or bio or website:
                if phone:
                    profile.phone = phone
                if address:
                    profile.address = address
                if location:
                    profile.location = location
                if bio:
                    profile.bio = bio
                if website:
                    profile.website =website
                profile.save()
            
            if image:
                profile.picture = image
                profile.save()
            
            # Check if it's an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'data': {
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'bio': profile.bio,
                        'phone': profile.phone,
                        'address': profile.address,
                        'location': profile.location,
                        'picture_url': profile.picture.url,
                        'website':profile.website
                    },
                    'message': 'Profile updated successfully!'
                })
            else:
                messages.info(request, 'Profile Updated Successfully')
                return redirect('profile', username=request.user.username)
                
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
            else:
                messages.error(request, f'Error updating profile: {str(e)}')
                return redirect('profile', username=request.user.username)
    
    # For GET requests, still render the old page as fallback
    return render(request, 'update_profile.html', {'profile': profile})
@login_required
def mark_follow_notifications_read(request):
    if request.method == 'POST':
        # Mark all unread follow notifications as read
        updated = FollowNotification.objects.filter(
            to_user=request.user,
            is_read=False
        ).update(is_read=True)
        
        return JsonResponse({
            'success': True,
            'updated_count': updated
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})
@login_required
def explore_users(request):
    # Get current user's profile
    current_profile = get_object_or_404(Profile, user=request.user)
    
    # Get unread follow notifications count
    unread_follow_count = FollowNotification.objects.filter(
        to_user=request.user,
        is_read=False
    ).count()
    
    # Get recent follow notifications (last 10)
    recent_follows = FollowNotification.objects.filter(
        to_user=request.user
    ).select_related('from_user', 'from_user__profile').order_by('-created_at')[:10]
    
    # Get Profile IDs of people the current user follows
    following_profile_ids = current_profile.followings.values_list('id', flat=True)
    
    # Base queryset - exclude self profile and already followed profiles
    profiles = Profile.objects.exclude(user=request.user).exclude(id__in=following_profile_ids)
    
    # Order by popularity (most followers first) by default
    profiles = profiles.annotate(
        follower_count=Count('followers')
    ).order_by('-follower_count', '-created_at')
    
    # For initial page load, limit to 30 profiles
    profiles = profiles[:30]
    
    return render(request, 'explore_users.html', {
        'profiles': profiles,
        'title': 'Explore Users',
        'unread_follow_count': unread_follow_count,
        'recent_follows': recent_follows,
    })




def follow(request, username):
    other_user = get_object_or_404(User, username=username)
    current_profile=request.user.profile
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
    profile=user.profile
    followers = profile.followers.all()

    context = {
        'user':user,
        'profile': profile,
        'followers': followers
    }


    return render(request, 'followers_list.html', context)

@login_required(login_url='/')
def following_list(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    followings = profile.followings.all()

    context = {
        'user': user,
        'profile': profile,
        'followings': followings
    }


    return render(request, 'following_list.html', context)
@login_required(login_url='/')
def search(request):
    query = request.GET.get('q', '').strip()
    
    if query:
        # Save search to history
        SearchHistory.objects.create(user=request.user, query=query)
        
        # Perform search
        users = User.objects.filter(
            Q(username__icontains=query) | 
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query)
        )
        
        # Get recent searches (excluding current)
        recent_searches = SearchHistory.objects.filter(
            user=request.user
        ).exclude(query=query).order_by('-created_at')[:5]
        
        return render(request, 'search.html', {
            'query': query,
            'users': users,
            'recent_searches': recent_searches
        })
    
    # Show search history when no query
    search_history = SearchHistory.objects.filter(
        user=request.user
    ).order_by('-created_at')[:20]
    
    return render(request, 'search.html', {
        'search_history': search_history
    })

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
    
    # Mark unread messages as read
    unread_messages = Message.objects.filter(
        sender=receiver,
        receiver=sender,
        is_read=False
    )
    unread_messages.update(is_read=True)
    
    # Get conversations
    conversations = Message.objects.filter(
        Q(sender=sender, receiver=receiver) | Q(sender=receiver, receiver=sender)
    ).order_by('created_at')
    
    # Group messages by date
    grouped_messages = {}
    for label, msgs in groupby(conversations, key=lambda m: m.chat_date_label):
        grouped_messages[label] = list(msgs)
    
    context = {
        'grouped_messages': grouped_messages,
        'receiver': receiver
    }
    return render(request, 'message.html', context)

@login_required(login_url='/')
def send_message(request, username):
    receiver = get_object_or_404(User, username=username)
    
    if request.method == 'POST':
        # Check if it's JSON data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            message_text = data.get('message', '')
            reply_to_id = data.get('reply_to')
        else:
            message_text = request.POST.get('message', '')
            reply_to_id = request.POST.get('reply_to')
        
        file_upload = request.FILES.get('file_upload')
        
        # If no message and no file, just return success
        if not message_text and not file_upload:
            return JsonResponse({
                'status': 'success',
                'message': 'No content to send'
            })
        
        file_type = None
        if file_upload:
            content_type = file_upload.content_type
            if content_type.startswith('image/'):
                file_type = 'image'
            elif content_type.startswith('video/'):
                file_type = 'video'
            elif content_type.startswith('audio/'):
                file_type = 'audio'
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unsupported file type'
                })
        
        # Get reply_to message if exists
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id)
                # Verify reply_to message is in the same conversation
                if not (reply_to.sender == request.user or reply_to.receiver == request.user or
                        reply_to.sender == receiver or reply_to.receiver == receiver):
                    reply_to = None
            except Message.DoesNotExist:
                reply_to = None
        
        # Create message
        message = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            conversation=message_text if message_text else '',
            file_type=file_type,
            file=file_upload if file_upload else None,
            reply_to=reply_to
        )
        
        # Mark any unread messages from this sender as read
        unread_messages = Message.objects.filter(
            sender=receiver,
            receiver=request.user,
            is_read=False
        )
        unread_messages.update(is_read=True)
        
        # Broadcast via WebSocket
        channel_layer = get_channel_layer()
        
        # Create consistent room name (MUST match consumer)
        user_ids = sorted([request.user.id, receiver.id])
        room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        room_group_name = f"chat_{room_name}"
        
        file_url = message.file.url if message.file else None
        
        print(f"📤 Broadcasting message to room: {room_group_name}")
        print(f"👤 From: {request.user.username}")
        print(f"👥 To: {receiver.username}")
        
        # Prepare reply data for WebSocket
        reply_data = None
        if reply_to:
            reply_data = {
                'sender': reply_to.sender.username,
                'message': reply_to.conversation,
                'file_type': reply_to.file_type
            }
        
        # Send to both users in the room
        async_to_sync(channel_layer.group_send)(
            room_group_name,  # Use the SAME group name as in consumer
            {
                'type': 'chat_message',  # This MUST match the method name in consumer
                'message_id': message.id,
                'sender': request.user.username,
                'receiver': receiver.username,
                'message': message_text,
                'file_type': file_type,
                'file_url': file_url,
                'time': message.chat_time,
                'date_label': message.chat_date_label,
                'created_at': message.created_at.isoformat(),
                'reply_to': reply_data
            }
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Message sent',
            'message_id': message.id,
            'file_url': file_url
        })
    
    # Handle GET requests by redirecting to message page
    return redirect('message', username=username)

@login_required(login_url='/')
def delete_message(request, message_id):
    if request.method == 'POST':
        try:
            message = Message.objects.get(id=message_id)
            
            # Check if user is authorized to delete (sender or receiver)
            if message.sender != request.user and message.receiver != request.user:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unauthorized'
                })
            
            # Broadcast deletion via WebSocket
            channel_layer = get_channel_layer()
            
            # Create consistent room name
            user_ids = sorted([message.sender.id, message.receiver.id])
            room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
            room_group_name = f"chat_{room_name}"
            
            # Broadcast deletion to both users
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'chat_message',
                    'message_id': message.id,
                    'type': 'message_deleted',
                    'sender': message.sender.username,
                    'receiver': message.receiver.username
                }
            )
            
            # Delete the message
            message.delete()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Message deleted successfully'
            })
            
        except Message.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Message not found'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})
@login_required(login_url='/')
def open_notification(request, post_id, notification_type):


    # Ensure post exists
    post = get_object_or_404(Post, post_id=post_id)

    Notification.objects.filter(
        recipient = request.user,
        post = post,
        notification_type=notification_type,
        is_read = False
    ).update(is_read=True)

    # Redirect to post comment page
    return redirect('post_comment', post_id=post.post_id)
    
login_required(login_url='/')
def inbox(request):
    # Get all unique conversations for the current user
    conversations = {}
    
    # Get the last message for each conversation
    # First, get all messages involving the current user
    all_messages = Message.objects.filter(
        Q(sender=request.user) | Q(receiver=request.user)
    )
    
    # Get distinct conversation partners
    conversation_partners = set()
    for msg in all_messages:
        other_user = msg.sender if msg.sender != request.user else msg.receiver
        conversation_partners.add(other_user)
    
    # For each conversation partner, get the most recent message
    for partner in conversation_partners:
        # Get the last message in this conversation
        last_message = Message.objects.filter(
            Q(sender=request.user, receiver=partner) |
            Q(sender=partner, receiver=request.user)
        ).order_by('-created_at').first()
        
        if last_message:
            # Get unread count for this conversation
            unread_count = Message.objects.filter(
                sender=partner,
                receiver=request.user,
                is_read=False
            ).count()
            
            conversations[partner] = {
                'last_message': last_message,
                'unread_count': unread_count
            }
    
    # Sort conversations by last message time (most recent first)
    sorted_conversations = sorted(
        conversations.items(),
        key=lambda x: x[1]['last_message'].created_at,
        reverse=True
    )
    
    # Get contacts for stories (all conversation partners)
    contacts = conversation_partners
    
    return render(request, 'inbox.html', {
        'conversations': dict(sorted_conversations),
        'contacts': contacts,
        'user': request.user
    })

login_required(login_url='/')
def notification_list(request):
    return render(request, 'notification.html')

@login_required
def channel_create(request):
    # 1. Handle New Channel Creation (POST)
    if request.method == 'POST':
        name = request.POST.get('name')
        about = request.POST.get('about')
        icon = request.FILES.get('icon')
        
        new_channel = Channel.objects.create(
            channel_owner=request.user,
            channel_name=name,
            about=about,
            image=icon if icon else 'male.png'
        )
        new_channel.subscriber.add(request.user)
        return redirect('channel', channel_id=new_channel.channel_id)

    # 2. Logic for Followed Channels
    followed_channels = Channel.objects.filter(subscriber=request.user).annotate(
        last_app_activity=Max('channel_messages__created_at')
    ).order_by('-last_app_activity', '-created_at')

    followed_list = []
    total_unread = 0
    
    for c in followed_channels:
        unread = c.unread_count_for_user(request.user)
        total_unread += unread
        
        # Get the actual last message object
        last_msg = c.channel_messages.order_by('-created_at').first()
        
        # Determine the message type for the initial page load icons
        msg_type = 'text'
        if last_msg:
            if last_msg.file_type == 'audio':
                msg_type = 'audio'
            elif last_msg.file_type == 'video':
                msg_type = 'video'
            elif last_msg.file_type == 'image':
                msg_type = 'image'

        followed_list.append({
            'channel': c,
            'unread_count': unread,
            'last_message': last_msg.message if last_msg else "No messages yet",
            'last_time': last_msg.created_at if last_msg else None,
            'message_type': msg_type 
        })

    # 3. Logic for Unfollowed Channels (Discover)
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
    """
    Renders the channel page with grouped messages and channel details.
    Includes security check for blocked users.
    """
    channel = get_object_or_404(Channel, channel_id=channel_id)
    
    # SECURITY: Check if current user is blocked from this channel
    if request.user in channel.blocked_users.all():
        # Redirect to a generic page or home if blocked
        return redirect('home') 

    # Update user's last seen timestamp for unread calculation
    ChannelUserLastSeen.objects.update_or_create(
        channel=channel,
        user=request.user,
        defaults={'last_seen_at': timezone.now()}
    )
    
    # Get all messages and group them by date
    messages = ChannelMessage.objects.filter(channel=channel).order_by('created_at')
    grouped_messages = {}
    for message in messages:
        date_label = message.chat_date_label
        if date_label not in grouped_messages:
            grouped_messages[date_label] = []
        grouped_messages[date_label].append(message)
    
    # Get total unread count across all subscribed channels for the sidebar/footer
    subscribed_channels = Channel.objects.filter(subscriber=request.user)
    total_unread = sum(ch.unread_count_for_user(request.user) for ch in subscribed_channels)
    
    # User notifications
    notifications = request.user.notifications.filter(is_read=False)
    
    context = {
        'channel': channel,
        'grouped_messages': grouped_messages,
        'channel_id': str(channel_id),
        'total_unread': total_unread,
        'notifications': notifications,
        'is_admin': channel.is_user_admin(request.user), 
        'is_owner': channel.channel_owner == request.user
    }
    
    return render(request, 'channel.html', context)
 
@login_required
def channel_message(request, channel_id):
    """
    Handles sending messages (text, files, audio) and broadcasts via WebSockets.
    Respects Broadcast Mode (Admins only if enabled).
    """
    channel = get_object_or_404(Channel, channel_id=channel_id)
    
    # SECURITY: Prevent non-admins from posting if broadcast mode is ON
    if channel.is_broadcast_only and request.user != channel.channel_owner:
        return JsonResponse({'status': 'error', 'message': 'Only admins can post in this channel.'}, status=403)

    if request.method == 'POST':
        message_text = request.POST.get('message', '')
        file_upload = request.FILES.get('file_upload')
        reply_to_id = request.POST.get('reply_to')

        file_type = None
        if file_upload:
            content_type = file_upload.content_type
            if content_type.startswith('image/'):
                file_type = 'image'
            elif content_type.startswith('video/'):
                file_type = 'video'
            elif content_type.startswith('audio/'):
                file_type = 'audio'
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported file type'})

        # Create the message instance
        channelMessage = ChannelMessage.objects.create(
            channel=channel,
            author=request.user,
            message=message_text if message_text else '',
            file_type=file_type,
            file=file_upload,
            reply_to_id=reply_to_id if reply_to_id else None
        )

        # Real-time Broadcast via WebSockets
        layer = get_channel_layer()
        group_name = f'channel_{channel_id}'
        file_url = channelMessage.file.url if channelMessage.file else None
        
        # Determine reply data for real-time update
        reply_data = None
        if channelMessage.reply_to:
            reply_data = {
                'author': channelMessage.reply_to.author.username,
                'message': channelMessage.reply_to.message[:50] if channelMessage.reply_to.message else "Media file"
            }

        async_to_sync(layer.group_send)(
            group_name,
            {
                'type': 'channel_message', # This triggers appendNewMessage in your JS
                'author': channelMessage.author.username,
                'message': channelMessage.message,
                'file_type': file_type,
                'file_url': file_url,
                "time": channelMessage.chat_time,
                "message_id": str(channelMessage.channelmessage_id),
                "reply_to": reply_data,
            }
        )
        
        # Update unread counts for all other subscribers
        subscribers = channel.subscriber.exclude(id=request.user.id)
        for subscriber in subscribers:
            unread_count = channel.unread_count_for_user(subscriber)
            user_group_name = f'user_{subscriber.id}_channels'
            async_to_sync(layer.group_send)(
                user_group_name,
                {
                    'type': 'unread_update',
                    'channel_id': str(channel.channel_id),
                    'unread_count': unread_count,
                    'channel_name': channel.channel_name,
                    'message_preview': message_text[:30] if message_text else "New media message",
                }
            )
        
        return JsonResponse({
            'status': 'success',
            'message_id': str(channelMessage.channelmessage_id),
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})

@login_required
def update_channel(request, channel_id):
    """
    View for the Channel Owner to update settings (Name, About, Image, Broadcast Mode).
    """
    channel = get_object_or_404(Channel, channel_id=channel_id)
    
    if request.user != channel.channel_owner:
        return redirect('channel', channel_id=channel_id)

    if request.method == 'POST':
        channel.channel_name = request.POST.get('name', channel.channel_name)
        channel.about = request.POST.get('about', channel.about)
        
        # Handle Broadcast Mode Toggle
        broadcast = request.POST.get('broadcast')
        channel.is_broadcast_only = (broadcast == 'true')
        
        # Handle Channel Icon
        if request.FILES.get('image'):
            channel.image = request.FILES.get('image')
            
        channel.save()
        
    return redirect('channel', channel_id=channel_id)

@login_required
def manage_member(request, channel_id, user_id):
    """
    Handles removing or blocking users from a channel.
    Respects hierarchy: Regular Admins can manage members, 
    but only the primary Owner can manage other Admins.
    """
    channel = get_object_or_404(Channel, channel_id=channel_id)
    
    # 1. Permission Check: Must be an Admin or the Owner to perform management
    if not channel.is_user_admin(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            # Parse the JSON data from the request body
            data = json.loads(request.body)
            action = data.get('action')
            target_user = get_object_or_404(User, id=user_id)
            
            # 2. Hierarchy Check:
            # Check if the target is an admin or the primary creator
            is_target_admin = channel.admins.filter(id=target_user.id).exists()
            is_target_owner = (target_user == channel.channel_owner)

            # Security logic: Regular Admins cannot remove the Owner or other Admins.
            if (is_target_admin or is_target_owner) and request.user != channel.channel_owner:
                return JsonResponse({
                    'success': False, 
                    'message': 'Permission denied: Only the owner can remove admins.'
                }, status=403)
            
            # 3. Execute Actions
            if action == 'remove' or action == 'block':
                # Remove from subscribers list
                channel.subscriber.remove(target_user)
                
                # Cleanup: Always remove from admin list if they are being kicked out
                channel.admins.remove(target_user) 
                
                if action == 'block':
                    # Add to the blocked_users ManyToMany field
                    channel.blocked_users.add(target_user)
                    
                return JsonResponse({'success': True})
            
            else:
                return JsonResponse({'success': False, 'message': 'Unknown action'}, status=400)

        except (json.JSONDecodeError, User.DoesNotExist):
            return JsonResponse({'success': False, 'message': 'Invalid request data'}, status=400)

    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

@login_required
def toggle_admin(request, channel_id, user_id):
    """View to promote/demote a user."""
    channel = get_object_or_404(Channel, channel_id=channel_id)
    if request.user != channel.channel_owner:
        return JsonResponse({'success': False}, status=403)

    target_user = get_object_or_404(User, id=user_id)
    if channel.admins.filter(id=target_user.id).exists():
        channel.admins.remove(target_user)
    else:
        channel.admins.add(target_user)
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
    
    return JsonResponse({
        'liked': liked,
        'like_count': channelmessage.like.count()
    })
  
# ======= Market Plce ======='



def market(request):
    # Handle category filtering
    category = request.GET.get('category', 'all')
    
    # Filter products based on category
    if category == 'all':
        products = Market.objects.all().order_by('-posted_on')
    else:
        products = Market.objects.filter(product_category=category).order_by('-posted_on')
    
    # Calculate stats
    highest_price = products.aggregate(Max('product_price'))['product_price__max']
    lowest_price = products.aggregate(Min('product_price'))['product_price__min']
    
    # Handle POST request for product creation
    if request.method == 'POST' and 'form_type' in request.POST:
        if request.POST['form_type'] == 'marketplace':
            product_owner = request.user
            product_name = request.POST.get('product_name')
            product_price = request.POST.get('product_price')
            product_location = request.POST.get('location', 'Ilorin, Nigeria')
            product_description = request.POST.get('description')
            product_availability = request.POST.get('availability', 'Single Item')
            product_category = request.POST.get('category')
            product_condition = request.POST.get('product_condition', 'New')
            whatsapp_number = request.POST.get('whatsapp_number')
            
            # Validate required fields
            if not all([product_name, product_price, product_category, product_description, whatsapp_number]):
                messages.error(request, 'Please fill in all required fields.')
                return redirect('market')
            
            # Check if at least one image is uploaded
            images = request.FILES.getlist('images')
            if len(images) == 0:
                messages.error(request, 'Please upload at least one image.')
                return redirect('market')
            
            # Create the product
            product = Market.objects.create(
                product_owner=product_owner,
                product_name=product_name,
                product_price=product_price,
                product_location=product_location,
                product_description=product_description,
                product_availability=product_availability,
                product_category=product_category,
                product_condition=product_condition,
                whatsapp_number=whatsapp_number
            )
            
            # Save images (limit to 5)
            for image in images[:5]:
                MarketImage.objects.create(product=product, product_image=image)
            
            messages.success(request, 'Product Added Successfully', extra_tags='marketplace_success')
            return redirect('market')
    
    context = {
        'products': products,
        'highest_price': highest_price or 0,
        'lowest_price': lowest_price or 0,
    }
    return render(request, 'marketplace.html', context)



def notification_partial(request):
    if request.user.is_authenticated:
        # Calculate unread notifications count
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
    else:
        unread_count = 0
    
    # Return the complete badge HTML
    return render(request, 'snippet/notification_count.html', {
        'unread_notifications_count': unread_count
    })
def inbox_partial(request):
    return render(request, 'snippet/inbox_count.html')
# Alternative simpler delete view
@login_required
def delete_notification_group(request):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        
        post_id = data.get('post_id')
        notification_type = data.get('notification_type')
        
        if not post_id or not notification_type:
            return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)
        
        # Delete all notifications in this group
        deleted_count, _ = Notification.objects.filter(
            recipient=request.user,
            post_id=post_id,
            notification_type=notification_type
        ).delete()
        
        return JsonResponse({
            'status': 'success',
            'deleted_count': deleted_count,
            'message': f'Deleted {deleted_count} notifications'
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)
def error_404(request, exception):
    return render(request, '404.html', status=404)
def logout(request):
    auth.logout(request)
    messages.info(request, 'Logout Successfully')
    return redirect('/')

def spotlight_view(request):
    # Filter: (Has video) OR (Is a repost AND original has video)
    spotlight_posts = Post.objects.filter(
        Q(video_file__isnull=False) & ~Q(video_file='') | 
        Q(is_repost=True, original_post__video_file__isnull=False) & ~Q(original_post__video_file='')
    ).order_by('?').select_related('author', 'original_post')

    return render(request, 'spotlight.html', {'posts': spotlight_posts})



@require_POST
def track_share(request, post_id):
    # Fetch the post using the ID
    post = get_object_or_404(Post, post_id=post_id)
    
    # Increment the share count (handling None if field is null)
    if post.share is None:
        post.share = 0
    post.share += 1
    post.save()
    
    # Return the new count to the frontend
    return JsonResponse({
        'success': True, 
        'new_count': post.share
    })


def product_detail(request, product_id):
    product = get_object_or_404(Market, product_id=product_id)
    if product.views_count is None:
        product.views_count = 0
    product.views_count += 1
    product.save()
    # Get all images for this product
    images = product.images.all() 
    # Get related products (same category, excluding current)
    related_products = Market.objects.filter(
        product_category=product.product_category
    ).exclude(product_id=product_id)[:4]
    
    seller_profile = get_object_or_404(Profile, user=product.product_owner)

    context = {
        'product': product,
        'images': images,
        'related_products': related_products,
        'seller': seller_profile,
    }
    return render(request, 'product_details.html', context)

def get_location(request, username): 
    user = Profile.objects.get(user__username=username)
    return JsonResponse({
        'lat': user.latitude,
        'lng': user.longitude
    })

@csrf_exempt
def get_stories(request):
    if request.method == 'GET':
        profile = Profile.objects.get(user=request.user)
        following = profile.followings.values_list('user', flat=True)
        
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
        # Get all stories
        all_stories = Story.objects.filter(
            Q(author__in=following) | Q(author=request.user),
            created_at__gte=twenty_four_hours_ago,
            is_active=True
        ).order_by('-created_at')
        
        # Get only latest story per user for the initial viewer
        seen_authors = set()
        initial_stories = []
        all_user_stories = []  # For when user taps on a story
        
        # First, find current user's story
        user_story = None
        other_stories = []
        
        for story in all_stories:
            if story.author.id not in seen_authors:
                if story.author == request.user:
                    user_story = story
                else:
                    other_stories.append(story)
                seen_authors.add(story.author.id)
            
            # Collect all stories for the viewer
            all_user_stories.append(story)
        
        # Put user's story first
        if user_story:
            initial_stories = [user_story] + other_stories
        else:
            initial_stories = other_stories
        
        stories_data = []
        for story in all_user_stories:
            # Check if this user has multiple stories
            user_story_count = Story.objects.filter(
                author=story.author,
                created_at__gte=twenty_four_hours_ago,
                is_active=True
            ).count()
            
            # Display "You" for current user
            author_name = "You" if story.author == request.user else f"{story.author.first_name} {story.author.last_name}".strip() or story.author.username
            
            # Get viewer count for current user's stories
            viewer_count = 0
            if story.author == request.user:
                viewer_count = story.viewers.count()
            
            stories_data.append({
                'id': str(story.story_id),
                'author_id': story.author.id,
                'author_username': story.author.username,
                'author_name': author_name,  # This will show "You" for current user
                'author_profile_picture': story.author.profile.picture.url,
                'story_type': story.story_type,
                'content': story.content or '',
                'media_url': story.image.url if story.image else (story.video.url if story.video else ''),
                'background_color': story.background_color,
                'text_color': story.text_color,
                'font_family': story.font_family,
                'font_size': story.font_size,
                'created_at': story.created_at.isoformat(),
                'time_ago': story.created_at.strftime('%H:%M'),
                'duration': 10,  # Default 10 seconds per story
                'viewed': request.user in story.viewers.all(),
                'has_multiple_stories': user_story_count > 1,
                'story_index': user_story_count,  # Which story number this is
                'is_current_user': story.author == request.user,  # Add this flag for easier JS handling
                'viewer_count': viewer_count,  # Add viewer count for current user's stories
            })
        
        return JsonResponse({
            'success': True,
            'stories': stories_data,
            'initial_stories': [str(s.story_id) for s in initial_stories]  # User's story will be first
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})
@csrf_exempt
def mark_story_viewed(request, story_id):
    if request.method == 'POST':
        try:
            story = Story.objects.get(story_id=story_id)
            if request.user not in story.viewers.all():
                story.viewers.add(request.user)
                story.save()
            return JsonResponse({'success': True})
        except Story.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Story not found'})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@csrf_exempt
@login_required
def send_story_reply(request, story_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reply_text = data.get('message', '').strip()
            
            if not reply_text:
                return JsonResponse({'success': False, 'error': 'Message cannot be empty'})
            
            story = get_object_or_404(Story, story_id=story_id)
            
            # 1. Format the conversation text to provide context
            # Example: "Replying to your story: Nice picture!"
            context_prefix = "Replying to your story: "
            full_conversation = f"{context_prefix}{reply_text}"
            
            # 2. Create the Message object (DM)
            # Note: We use 'conversation' field based on your models.py
            message = Message.objects.create(
                sender=request.user,
                receiver=story.author,
                conversation=full_conversation,
                file_type='story_reply', # Custom type so frontend can style it differently if needed
                is_read=False
            )
            
            # 3. Real-time Broadcast via WebSockets (Django Channels)
            # This allows the receiver to see the DM instantly while chatting
            channel_layer = get_channel_layer()
            
            # Create consistent room name (Logic must match send_message view)
            user_ids = sorted([request.user.id, story.author.id])
            room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
            room_group_name = f"chat_{room_name}"
            
            # Prepare data for WebSocket
            # If the story has an image/video, we could technically pass that URL here 
            # for the preview, though the Message model stores it in 'file'.
            
            print(f"📤 Broadcasting story reply to room: {room_group_name}")
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'chat_message', 
                    'message_id': message.id,
                    'sender': request.user.username,
                    'receiver': story.author.username,
                    'message': full_conversation,
                    'file_type': 'story_reply',
                    'file_url': None, # We aren't attaching a file to the message object itself to save space
                    'time': message.chat_time,
                    'date_label': message.chat_date_label,
                    'created_at': message.created_at.isoformat(),
                    'reply_to': None # Could link to story info here if frontend supports it
                }
            )
            
            return JsonResponse({'success': True})
            
        except Story.DoesNotExist: 
            return JsonResponse({'success': False, 'error': 'Story not found or expired'})
        except Exception as e:
            print(f"Error in story reply: {e}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@csrf_exempt
def create_story(request):
    if request.method == 'POST':
        try:
            story_type = request.POST.get('story_type', 'text')
            
            if story_type == 'text':
                # Handle text story
                data = json.loads(request.body)
                
                story = Story.objects.create(
                    author=request.user,
                    story_type='text',
                    content=data.get('content', ''),
                    background_color=data.get('background_color', '#0095f6'),
                    text_color=data.get('text_color', '#ffffff'),
                    font_family=data.get('font_family', 'Arial'),
                    font_size=data.get('font_size', 24)
                )
                
            else:
                # Handle image/video story
                story = Story.objects.create(
                    author=request.user,
                    story_type=story_type,
                    content=request.POST.get('content', '')
                )
                
                if story_type == 'image' and 'story_media' in request.FILES:
                    story.image = request.FILES['story_media']
                elif story_type == 'video' and 'story_media' in request.FILES:
                    story.video = request.FILES['story_media']
                
                story.save()  
            
            # Add creator as viewer
            story.viewers.add(request.user)
            
            return JsonResponse({'success': True, 'story_id': str(story.story_id)})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@csrf_exempt
@login_required
def get_story_viewers(request, story_id):
    """Get the number of viewers for a specific story (only for story owner)"""
    if request.method == 'GET':
        try:
            story = Story.objects.get(story_id=story_id)
            
            # Only allow story owner to see viewer count
            if story.author != request.user:
                return JsonResponse({
                    'success': False, 
                    'error': 'Unauthorized access to viewer data'
                })
            
            # Get the count of unique viewers
            viewer_count = story.viewers.count()
            
            return JsonResponse({
                'success': True,
                'viewer_count': viewer_count,
                'story_id': str(story_id)
            })
            
        except Story.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Story not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})
