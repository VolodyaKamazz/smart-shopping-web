import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Мини-загрузчик .env: строки КЛЮЧ=значение. Уже заданные переменные не трогает."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _flag(name, default=False):
    """Булева переменная окружения. Не задана или пустая — значение по умолчанию."""
    value = (os.environ.get(name) or "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


def _list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


_load_dotenv(BASE_DIR / ".env")

# По умолчанию режим отладки выключен: забытая переменная на сервере не откроет отладочные страницы.
# Для разработки в .env задаётся DJANGO_DEBUG=1.
DEBUG = _flag("DJANGO_DEBUG")

DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (DEV_SECRET_KEY if DEBUG else "")
if not SECRET_KEY or (not DEBUG and SECRET_KEY == DEV_SECRET_KEY):
    raise ImproperlyConfigured(
        "Не задан DJANGO_SECRET_KEY. Для локальной разработки скопируйте .env.example в .env "
        "(там включён DJANGO_DEBUG=1), на сервере задайте собственный секретный ключ.")

ALLOWED_HOSTS = _list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = _list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_q",
    "core",
    "accounts",
    "catalog",
    "importer",
    "delivery",
    "search",
    "recommender",
    "favorites",
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "search:home"
LOGOUT_REDIRECT_URL = "search:home"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite по умолчанию; для PostgreSQL задайте DATABASE_URL
DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60)}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {}).update({"transaction_mode": "IMMEDIATE", "timeout": 30})

CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache_table"}}

# Фоновые задачи: очередь и расписание в БД.
# Sync-режим: задачи выполняются сразу в запросе, расписание не срабатывает. По умолчанию он
# включён только при DEBUG; на сервере нужен DJANGO_Q_SYNC=0 и запущенный python manage.py qcluster
Q_CLUSTER = {
    "name": "smart_shopping",
    "orm": "default",
    "sync": _flag("DJANGO_Q_SYNC", default=DEBUG),
    "timeout": 120,
    "retry": 180,
    "workers": 2,
    "catch_up": False,
}

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DEMO_FEEDS_DIR = BASE_DIR / "static" / "demo_feeds"
DEMO_FEEDS_BASE_URL = os.environ.get("DEMO_FEEDS_BASE_URL", "http://127.0.0.1:8000/static/demo_feeds")

TESTING = sys.argv[1:2] == ["test"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.NullHandler" if TESTING else "logging.StreamHandler",
                             "formatter": "plain"}},
    "loggers": {
        name: {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"), "propagate": False}
        for name in ("importer", "catalog")
    },
}
