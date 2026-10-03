"""Gunicorn config: gunicorn -c deploy/gunicorn.conf.py backend.wsgi:app"""
import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = "gthread"
timeout = 60            # PDF/export requests can take a few seconds
graceful_timeout = 30
keepalive = 5
max_requests = 2000     # recycle workers to bound memory growth
max_requests_jitter = 200
accesslog = "-"
errorlog = "-"
# Access log without query strings (patient search terms must not be logged).
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(B)s %(M)sms'
forwarded_allow_ips = "127.0.0.1"
