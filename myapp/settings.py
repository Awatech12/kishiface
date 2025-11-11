
from pathlib import Path
import os
import cloudinary
import cloudinary_storage
import cloudinary.uploader
import cloudinary.api

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-y6p1od$soj&7wuuv8cz&4$t!n98(uun_f5621%bx5%#5t=ft=m'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False # ✅ Must be False for production
USE_CLOUDINARY = True # Set to True for production


ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'kishiface.onrender.com',
]

CSRF_TRUSTED_ORIGINS = [
    'https://kishiface.onrender.com',
]

# Application definition
INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'social',
]

# ✅ Cloudinary using Environment Variables
# --- Cloudinary Settings ---
if USE_CLOUDINARY:
    INSTALLED_APPS += [
        'cloudinary',
        'cloudinary_storage',
    ]

    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
        'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
        'SECURE': True,
    }

    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        }
    }

    # Remove local MEDIA_ROOT and MEDIA_URL
    MEDIA_URL = None
    MEDIA_ROOT = None
    
# --- End Cloudinary Settings ---

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',

    # ✅ Whitenoise middleware for static files
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'myapp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],  # Add your template dirs here if any
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'social.context_processors.unread_count_processor',
                'social.context_processors.information',
                'social.context_processors.user_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'myapp.wsgi.application'
ASGI_APPLICATION = 'myapp.asgi.application'

# Channels configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL", "redis://red-d3uim9ali9vc73c5a3i0:6379")],
        },
    },
}

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
