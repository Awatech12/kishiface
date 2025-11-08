from django.db import models
from django.contrib.auth.models import User
import uuid

# Create your models here.

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    followers = models.ManyToManyField(User, related_name='follower', blank=True)
    followings = models.ManyToManyField(User, related_name='following', blank=True)
    phone = models.CharField(max_length=20)
    full_name = models.CharField(max_length=200, blank=True)
    address = models.TextField()
    bio = models.CharField(max_length=300)
    location = models.TextField()
    picture = models.ImageField(upload_to='profile_image/', default='male.png')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.address = self.address.title()
        self.user.first_name=self.user.first_name.capitalize()
        self.user.last_name=self.user.last_name.capitalize()
        self.full_name = f'{self.user.first_name} {self.user.last_name}'
        self.user.save()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'Profile_Table'

    def __str__(self):
        return self.user.username


class Post(models.Model):
    post_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    likes = models.ManyToManyField(User, related_name='like_post', blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.author.username

class PostImage(models.Model):
    post=models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')


class PostComment(models.Model):
    comment_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    image = models.ImageField(upload_to='comment_image/', blank=True)
    file = models.FileField(upload_to='files', blank=True)
    like = models.ManyToManyField(User, related_name='comment_likes', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_receiver')
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_sender')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True)
    message=models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)



class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sender')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receiver')
    conversation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)


class Channel(models.Model):
    channel_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    channel_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_author')
    channel_name = models.CharField(max_length=200)
    about = models.TextField()
    subscriber = models.ManyToManyField(User, blank=True, related_name='channel_subscriber')
    image=models.ImageField(upload_to='channel_image', default='male.png')
    created_at = models.DateTimeField(auto_now_add=True)
class ChannelMessage(models.Model):
    channemessage_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='channel_messages')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    pictureUrl = models.TextField(blank=True)
    message = models.TextField()
    like = models.ManyToManyField(User, blank=True, related_name='message_likers')
    image = models.ImageField(upload_to='comment_image', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def like_count(self):
        return self.like.count()




