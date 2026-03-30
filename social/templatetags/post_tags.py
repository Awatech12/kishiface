import cloudinary
from django import template
from django.contrib.auth.models import User as DjangoUser

register = template.Library()

@register.filter
def total_media_count(post):
    count = 0
    try:
        if post.file: count += 1
        if post.video_file: count += 1
        count += post.images.count()
    except: pass
    return count

@register.filter(name='safe_pic_url')
def safe_pic_url(obj):
    """
    Bulletproof filter: Checks for picture in Profile, User, 
    and direct attributes to ensure it never returns a broken link.
    """
    try:
        if not obj:
            return 'https://placehold.co/40x40/dbdbdb/8e8e8e?text=?'

        # 1. Get the Profile object regardless of what was passed
        profile = None
        if hasattr(obj, 'picture'): # It's a Profile
            profile = obj
        elif hasattr(obj, 'profile'): # It's a User
            profile = obj.profile
        
        # 2. Extract the picture
        if profile and profile.picture:
            pic = profile.picture
            
            # Check for Cloudinary public_id (Production)
            if hasattr(pic, 'public_id') and pic.public_id:
                return cloudinary.CloudinaryImage(pic.public_id).build_url(secure=True)
            
            # Check for standard URL (Development)
            if hasattr(pic, 'url') and pic.url:
                url = pic.url
                return url.replace('http://', 'https://') if url.startswith('http://') else url

    except Exception as e:
        print(f"Error in safe_pic_url: {e}") # This will show in your terminal
    
    # 3. Fallback Placeholder
    return 'https://placehold.co/40x40/dbdbdb/8e8e8e?text=U'