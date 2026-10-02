"""Entry point for gunicorn: `gunicorn orderflow.wsgi:app`."""

from . import create_app

app = create_app()
