"""Punto de entrada WSGI para producción.

No ejecuta el servidor de desarrollo ni crea tablas: aplica primero las
migraciones (`alembic upgrade head`) y arranca con Gunicorn/Waitress.
"""
from app import app

application = app

__all__ = ['app', 'application']
