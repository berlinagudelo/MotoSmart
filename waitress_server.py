"""Servidor WSGI para Windows sin usar el servidor de desarrollo.

Ejemplo:
    waitress-serve --listen=127.0.0.1:8000 wsgi:application
    python waitress_server.py
"""
import os

from waitress import serve

from app import app


if __name__ == '__main__':
    host = os.environ.get('MOTOSMART_HOST', '127.0.0.1')
    port = int(os.environ.get('MOTOSMART_PORT', '8000'))
    threads = max(1, int(os.environ.get('MOTOSMART_THREADS', '8')))
    serve(app, host=host, port=port, threads=threads, channel_timeout=120)
