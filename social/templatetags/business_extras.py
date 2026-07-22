from datetime import datetime

from django import template

register = template.Library()


@register.filter
def hhmm12(value):
    """
    Convert a 24-hour 'HH:MM' string (as stored by _parse_business_hours_from_post)
    into a 12-hour display string, e.g. '09:00' -> '9:00 AM', '18:30' -> '6:30 PM'.
    Returns the original value unchanged if it can't be parsed.
    """
    if not value:
        return value
    try:
        parsed = datetime.strptime(value, '%H:%M')
    except (ValueError, TypeError):
        return value
    # %-I isn't portable on Windows; strip a leading zero manually instead.
    formatted = parsed.strftime('%I:%M %p')
    if formatted.startswith('0'):
        formatted = formatted[1:]
    return formatted
