
import re
from django import template
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.contrib.auth.models import User

register = template.Library()

@register.filter
def format_post_text(text):
    if not text:
        return ""
    
    # 1. Convert line breaks to <br> tags for paragraphs
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Process BB codes
    # Bold: [b]text[/b]
    text = re.sub(r'\[b\](.*?)\[/b\]', r'<strong>\1</strong>', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Italic: [i]text[/i]
    text = re.sub(r'\[i\](.*?)\[/i\]', r'<em>\1</em>', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Underline: [u]text[/u]
    text = re.sub(r'\[u\](.*?)\[/u\]', r'<u>\1</u>', text, flags=re.IGNORECASE | re.DOTALL)
    
    # 3. Process @mentions - find @username patterns
    # First, let's find all @mentions
    mention_pattern = r'@(\w+)'
    
    def replace_mention(match):
        username = match.group(1)
        try:
            user = User.objects.get(username=username)
            return f'<a href="/{username}/" class="kf-mention-link">@{username}</a>'
        except User.DoesNotExist:
            return match.group(0)  # Return original if user doesn't exist
    
    text = re.sub(mention_pattern, replace_mention, text)
    
    # 4. Process URLs - convert URLs to clickable links
    url_pattern = r'(https?://[^\s<>"\']+|www\.[^\s<>"\']+)'
    
    def replace_url(match):
        url = match.group(0)
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="kf-url-link">{match.group(0)}</a>'
    
    text = re.sub(url_pattern, replace_url, text)
    
    # 5. Split into paragraphs and wrap in <p> tags
    paragraphs = text.split('\n\n')
    formatted_paragraphs = []
    
    for para in paragraphs:
        if para.strip():
            # Process line breaks within paragraph
            para = para.replace('\n', '<br>')
            formatted_paragraphs.append(f'<p class="kf-post-paragraph">{para}</p>')
    
    # If no paragraphs were created (single line), create one
    if not formatted_paragraphs:
        text = text.replace('\n', '<br>')
        formatted_paragraphs.append(f'<p class="kf-post-paragraph">{text}</p>')
    
    return mark_safe(''.join(formatted_paragraphs))

@register.filter
def format_comment_text(text):
    """Simpler version for comments - just line breaks and URLs"""
    if not text:
        return ""
    
    # Convert line breaks
    text = text.replace('\n', '<br>')
    
    # Process URLs
    url_pattern = r'(https?://[^\s<>"\']+|www\.[^\s<>"\']+)'
    
    def replace_url(match):
        url = match.group(0)
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="kf-url-link">{match.group(0)}</a>'
    
    text = re.sub(url_pattern, replace_url, text)
    
    # Process @mentions
    mention_pattern = r'@(\w+)'
    
    def replace_mention(match):
        username = match.group(1)
        try:
            user = User.objects.get(username=username)
            return f'<a href="/profile/{username}/" class="kf-mention-link">@{username}</a>'
        except User.DoesNotExist:
            return match.group(0)
    
    text = re.sub(mention_pattern, replace_mention, text)
    
    return mark_safe(text)

@register.filter
def truncate_with_ellipsis(text, length=150):
    """Truncate text with ellipsis for show more/less functionality"""
    if not text:
        return ""
    
    if len(text) <= length:
        return text
    
    # Find the last space before the cutoff point
    truncated = text[:length]
    last_space = truncated.rfind(' ')
    
    if last_space > 0:
        truncated = truncated[:last_space]
    
    return truncated + '...'