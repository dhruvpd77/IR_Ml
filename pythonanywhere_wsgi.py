"""PythonAnywhere web app entry.

On the Web tab, open the WSGI file and replace its contents with this file.
Change USERNAME to your PythonAnywhere username, and set a real SECRET_KEY.
"""

import os
import sys

USERNAME = "USERNAME"
PROJECT = f"/home/{USERNAME}/IR_Ml"

if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("SECRET_KEY", "replace-this-with-a-long-random-string")
os.environ.setdefault("ALLOWED_HOSTS", f"{USERNAME}.pythonanywhere.com")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", f"https://{USERNAME}.pythonanywhere.com")
os.environ.setdefault("DB_ENGINE", "sqlite")
os.environ.setdefault("SERVE_MEDIA", "true")
os.environ.setdefault("SECURE_SSL", "false")

from config.wsgi import application  # noqa: E402
