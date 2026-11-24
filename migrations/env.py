"""Entorno de Alembic para MotoSmart.

Usa la misma metadata de SQLAlchemy que la aplicación para que las migraciones
reflejen exactamente los modelos. No crea tablas automáticamente: el esquema se
versiona con `alembic upgrade head`.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importar la app registra todos los modelos en db.metadata.
from app import app  # noqa: F401
from db import db


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get('MOTOSMART_DATABASE_URL', '').strip()
if not database_url:
    raise RuntimeError(
        'Define MOTOSMART_DATABASE_URL antes de ejecutar Alembic.'
    )
config.set_main_option('sqlalchemy.url', database_url.replace('%', '%%'))

target_metadata = db.metadata


def _configurar_contexto(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=database_url.startswith('sqlite'),
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configurar_contexto(
        url=database_url,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuracion = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        configuracion,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _configurar_contexto(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
