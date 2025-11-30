from django.shortcuts import render, redirect, get_object_or_404, HttpResponse 
from django.contrib.auth.models import User, auth
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from social.models import Profile, Post, PostImage, PostComment, Message, Notification, ChannelMessage, Channel, Market, MarketImage
from django.db.models import Q
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from itertools import groupby
from django.contrib.humanize.templatetags.humanize import naturaltime
import time
from django.http import JsonResponse
from openai import OpenAI
from django.conf import settings
client = OpenAI(api_key=settings.OPENAI_API_KEY)

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
    posts = Post.objects.all().order_by('?')
    products = Market.objects.all().order_by('?')
    members = User.objects.all().order_by('?')
    context = {
        'posts':posts,
        'members': members,
        'user': request.user,
        'products': products}
    return render(request, 'home.html', context)


    
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
    if request.user not in post.likes.all():
        post.likes.add(request.user)
        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                actor = request.user,
                post=post,
                message=f' Liked your post {post.content}')
    else:
        post.likes.remove(request.user)
    return render(request, 'snippet/post_like.html', {'post':post, 'post_id':post_id})  
       

@login_required(login_url='/')
def post_comment(request, post_id):
    post=get_object_or_404(Post, post_id=post_id)
    
    comments=PostComment.objects.filter(post=post).order_by('-created_at')
    return render(request, 'postcomment.html', {'post':post, 'comments': comments})


@login_required(login_url='/')
def commentpopup(request, post_id):
    post=get_object_or_404(Post, post_id=post_id)
    
    comments=PostComment.objects.filter(post=post).order_by('-created_at')
    return render(request, 'commentpopup.html', {'post':post, 'comments': comments})
@login_required(login_url='/')
def postcomment(request, post_id):
    post=get_object_or_404(Post, post_id=post_id)
    if request.method == 'POST':
        content = request.POST.get('comment')
        image = request.FILES.get('image')
        audio = request.FILES.get('audio_file')
        if not content and not image and not audio:
            return
        comment = PostComment.objects.create(
            post=post,
            author=request.user,
            comment=content if content else "",
            image=image if image else None,
            file=audio if audio else None
        )
        # send Real-time update
        created_at = naturaltime(comment.created_at)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'post_{post_id}',
            {
            'type': 'new_comment',
            'comment_id': str(comment.comment_id),
            'author_username': comment.author.username,
            'author_first':str( comment.author.first_name),
            'author_last': str(comment.author.last_name),
            'is_verify': comment.author.profile.is_verify,
            'profile_pic': comment.author.profile.picture.url,
            'comment': comment.comment if comment.comment else '',
            'image_url': comment.image.url if comment.image else '',
            'file_url': comment.file.url if comment.file else '',
            'post_id': str(post_id),
            'created_at': str(created_at),
            'user_id': comment.author.id
            }
        )
        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                actor = request.user,
                 message=f"  commented on your post {post.content}",
                 post=post)
        return render(request, 'snippet/comment_list.html', {'post':post, 'comment': comment})
    

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
    posts = Post.objects.filter(author=user)
    profile = user.profile

    context={
        'user':user,
        'posts':posts,
        'profile':profile,
        'current_profile': request.user.profile
    }
    
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
    quary = request.GET.get('q')
    if quary:
        users = User.objects.filter(
            Q(username__icontains=quary) | Q(email__icontains=quary) | Q(first_name__icontains=quary) | Q(last_name__icontains=quary)
        )
        return render(request, 'search.html', {'quary': quary, 'users':users})
    return render(request, 'search.html')

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
def open_notification(request, pk):
    notifications =get_object_or_404(Notification, pk=pk, recipient=request.user)
    notifications.is_read=True
    notifications.save()
    if notifications.post: 
        return redirect('post_comment', post_id=notifications.post.post_id)
   
    return render(request, 'home.html')
    
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
    messages = ChannelMessage.objects.filter(channel=channel)
    grouped_messages = {}
    for label, msgs in groupby(messages, key=lambda m: m.chat_date_label):
        grouped_messages[label] = list(msgs)

    context = {
        'channel': channel,
        'channel_id': channel_id,
        'grouped_messages': grouped_messages
    }
    return render(request, 'channel.html', context)

# ======= Market Plce =======

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


# ======== AI Mood ======
@login_required
def generate_ai_text(request):
    mood = request.GET.get("mood")
    if not mood:
        return JsonResponse({"error": "Mood is required"}, status=400)

    prompt = f"Write a short social media caption based on the mood: {mood}. Make it human-like with emojis."

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    caption = response.choices[0].message["content"].strip()
    return JsonResponse({"caption": caption})
    

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