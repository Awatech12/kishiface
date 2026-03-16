from django import template
from django.conf import settings

register = template.Library()

@register.filter
def total_media_count(post):
    """Count all media items in a post"""
    count = 0
    if post.file:  # Audio file
        count += 1
    if post.video_file:  # Video file
        count += 1
    count += post.images.count()  # Images
    return count


@register.filter(name='safe_pic_url')
def safe_pic_url(user_obj):
    """
    Returns a full profile picture URL for a User or Profile object.
    Delegates to Profile.get_picture_url which handles both
    Cloudinary (production) and ImageField (debug) correctly.

    Usage:
      {{ user|safe_pic_url }}           ← User object (post author)
      {{ item.data.author|safe_pic_url }}
      {{ item.data|safe_pic_url }}       ← suggestion cards (User object)
    """
    from django.contrib.auth.models import User as DjangoUser
    try:
        # Case 1: Django User object — access .profile explicitly
        if isinstance(user_obj, DjangoUser):
            return user_obj.profile.get_picture_url

        # Case 2: Profile object — has get_picture_url directly
        if hasattr(user_obj, 'get_picture_url'):
            return user_obj.get_picture_url

    except Exception:
        pass
    return 'https://placehold.co/40x40/dbdbdb/8e8e8e?text=U'
