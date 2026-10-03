"""WSGI entry point: gunicorn 'backend.wsgi:app'  /  flask --app backend.wsgi ..."""
from backend.app import create_app

app = create_app()
