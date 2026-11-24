"""Configuración de Gunicorn para MotoSmart (Linux/contenedores).

Ejemplo:
    gunicorn -c gunicorn.conf.py wsgi:application
"""
import multiprocessing
import os


bind = os.environ.get('MOTOSMART_BIND', '127.0.0.1:8000')
workers = max(1, int(os.environ.get('MOTOSMART_WORKERS', multiprocessing.cpu_count() * 2 + 1)))
worker_class = 'gthread'
threads = max(1, int(os.environ.get('MOTOSMART_THREADS', '4')))
timeout = max(30, int(os.environ.get('MOTOSMART_GUNICORN_TIMEOUT', '120')))
graceful_timeout = 30
keepalive = 5
max_requests = max(100, int(os.environ.get('MOTOSMART_GUNICORN_MAX_REQUESTS', '2000')))
max_requests_jitter = 200
accesslog = os.environ.get('MOTOSMART_ACCESS_LOG', '-')
errorlog = os.environ.get('MOTOSMART_ERROR_LOG', '-')
loglevel = os.environ.get('MOTOSMART_LOG_LEVEL', 'info')
# No usar preload: cada worker debe crear su propio pool y no heredar conexiones.
preload_app = False
# El OCR y el correo no bloquean la respuesta, pero un worker sano debe reciclarse.
worker_tmp_dir = os.environ.get('MOTOSMART_GUNICORN_TMP', '/dev/shm')
