from django.shortcuts import render, redirect, get_object_or_404, HttpResponse 
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, Post, PostImage, PostComment, Message, Notification, ChannelMessage, Channel, Market, MarketImage, SearchHistory
from django.db.models import Q
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
import random

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
    
    # Get data
    posts = Post.objects.filter(Q(author__in=following) | Q(author=request.user)).order_by('?')
    products = list(Market.objects.order_by('?'))
    users = list(User.objects.exclude(id__in=following).exclude(id=request.user.id).order_by('?'))
    
    # Build feed
    feed = []
    
    if not following:  # New user
        feed = [{'type': 'user_suggestion', 'data': u} for u in users[:3]]
        feed += [{'type': 'product', 'data': p} for p in products[:2]]
        if not feed:
            feed.append({'type': 'welcome'})
    
    else:  # Existing user
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
    })




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
            else:
                # Follow
                current_profile.followings.add(target_profile)
                followed = True
            
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

login_required(login_url='/')
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

        if not content and not image and not audio:
            return

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

        return render(
            request,
            'snippet/comment_list.html',
            {'post': post, 'comment': comment}
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
        'total_view':total_view
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
    
def profile_popup(request, username):
    user = get_object_or_404(User, username=username)
    posts = Post.objects.filter(author=user)
    profile = user.profile

    context={
        'user':user,
        'posts':posts,
        'profile':profile,
        'current_profile': request.user.profile
    }

    return render(request, 'popup_profile.html', context)



@login_required(login_url='/')
def update_profile(request, username):
    user = request.user
    profile= request.user.profile
    if request.method =='POST':
        fname= request.POST.get('fname')
        lname = request.POST.get('lname')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        location = request.POST.get('location')
        image = request.FILES.get('image')
        bio = request.POST.get('bio')
        if fname and lname:
            user.first_name=fname
            user.last_name=lname
            user.save()
        if phone and address and location and bio:
            profile.phone = phone
            profile.address= address
            profile.location = location
            profile.bio = bio
            profile.save()
        if image:
            profile.picture = image
            profile.save()
        messages.info(request, 'Profile Updated Successfully')
        return redirect('profile', username=request.user.username)


    return render(request, 'update_profile.html', {'profile':profile})

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
    unread_message = Message.objects.filter(
        receiver=sender, sender=receiver, is_read=False
    )
    for msg in unread_message:
        msg.is_read = True
        msg.save()
   
    conversations = Message.objects.filter(
        Q(sender=sender, receiver=receiver) | Q(sender=receiver, receiver=sender)
    ).order_by('created_at')
    grouped_messages = {}
    for label, msgs in groupby(conversations, key=lambda m: m.chat_date_label):
        grouped_messages[label] = list(msgs)

    context = {
        'grouped_messages':grouped_messages,
        'receiver': receiver
        }
    return render(request, 'message.html', context )

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
    inbox_messages = Message.objects.filter(
        Q(sender=request.user) | Q(receiver=request.user)
    ).order_by('-created_at')
    conversations={}
    for message in inbox_messages:
        other_user=message.sender if message.sender != request.user else message.receiver
        conversations.setdefault(other_user, message)
    return render(request, 'inbox.html', {'messages':conversations.values(),})

login_required(login_url='/')
def notification_list(request):
    return render(request, 'notification.html')

login_required(login_url='/')
def channel_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        about = request.POST.get('about')
        icon = request.FILES.get('icon')
        if not name and not about and not icon:
            return
        channel=Channel.objects.create(channel_name=name, channel_owner=request.user, about=about, image=icon)
        messages.info(request, 'Channel Created Successfully')
        return redirect('channel_create')

    channels = Channel.objects.all().order_by('?')
    context = {
        'channels': channels
    }
    return render(request, 'channel_create.html', context)

def follow_channel(request, channel_id):
    channel = get_object_or_404(Channel, channel_id=channel_id)
    if request.user not in channel.subscriber.all():
        channel.subscriber.add(request.user)
    else:
        channel.subscriber.remove(request.user)
    return redirect(request.META.get('HTTP_REFERER'))
    
    
login_required(login_url='/')
def channel(request, channel_id):
    channel = get_object_or_404(Channel, channel_id=channel_id)

    messages = ChannelMessage.objects.filter(channel=channel) \
                                   .select_related('author') \
                                   .order_by('created_at')

    grouped_messages = {}
    message_list = list(messages)

    for label, msgs in groupby(message_list, key=lambda m: m.chat_date_label):
        grouped_messages[label] = list(msgs)

    context = {
        'channel': channel,
        'channel_id': channel_id,
        'grouped_messages': grouped_messages
    }

    return render(request, 'channel.html', context)

def channel_message(request, channel_id):
    channel = get_object_or_404(Channel, channel_id=channel_id)
    if request.method == 'POST':
        message = request.POST.get('message', '')
        file_upload = request.FILES.get('file_upload')

        file_type = None
        file_url = None
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
                    'message':'error in file selection'
                })

        channelMessage = ChannelMessage.objects.create(
            channel = channel,
            author = request.user,
            message = message if message else '',
            file_type = file_type if file_type else None,
            file= file_upload if file_upload else None
        )

        layer = get_channel_layer()
        group_name = f'channel_{channel_id}'
        file_url = channelMessage.file.url if channelMessage.file else None
        fileType = channelMessage.file_type if channelMessage.file_type else None

        async_to_sync(layer.group_send)(
            group_name,
            {
                'type': 'channel_message',
                'author': channelMessage.author.username,
                'message': channelMessage.message,
                'file_type': fileType,
                'file_url': file_url,
                "time": timezone.now().strftime("%I:%M %p")
            }
        )
        return JsonResponse({
            'status': 'success',
            'message': 'Message Sent'
        })
# ====== channelMessage Like =======
def channelmessage_like(request, channelmessage_id):
    channelmessage = get_object_or_404(ChannelMessage, channelmessage_id=channelmessage_id)
    if request.user not in channelmessage.like.all():
        channelmessage.like.add(request.user)
        liked = True
        return redirect(request.META.get('HTTP_REFERER'))
    else:
        channelmessage.like.remove(request.user)
        liked = False
        return redirect(request.META.get('HTTP_REFERER'))
    
    
# ======= Market Plce ======='


def market(request):
    products = Market.objects.all()

    print(f'Products no: {products.count()}')
    context = {
        'products': products
    }

    return render(request, 'marketplace.html', context)

# ======= market form ====
def marketForm(request):
    if request.method == 'POST':
        product_owner = request.user
        product_name = request.POST.get('product_name')
        product_price = request.POST.get('product_price')
        product_location = request.POST.get('location')
        product_description = request.POST.get('description')
        product_availability = request.POST.get('availability')
        product_category = request.POST.get('category')
        images = request.FILES.getlist('images')
        if not product_name and not product_availability and not product_category and not product_location:
            return
        product = Market.objects.create(
            product_owner=product_owner,
            product_name=product_name,
            product_price=product_price,
            product_location=product_location,
            product_description=product_description,
            product_availability=product_availability,
            product_category=product_category)
        
        for image in images:
            MarketImage.objects.create(product=product, product_image=image)
        messages.success(request, 'Product Added Successfully')
        return redirect('market')

    return render(request, 'marketform.html')


# ==== for Notification and inbox  updating =====
def notification_partial(request):
    return render(request, 'snippet/notification_count.html')

def inbox_partial(request):
    return render(request, 'snippet/inbox_count.html')
def error_404(request, exception):
    return render(request, '404.html', status=404)
def logout(request):
    auth.logout(request)
    messages.info(request, 'Logout Successfully')
    return redirect('/')