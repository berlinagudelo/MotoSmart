import os

from flask_sqlalchemy import SQLAlchemy
from flask import Flask

app = Flask(__name__)
database_url = os.environ.get('MOTOSMART_DATABASE_URL', '')
if not database_url:
    raise RuntimeError(
        'Define MOTOSMART_DATABASE_URL con la conexión privada a PostgreSQL.'
    )

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if database_url.startswith(('postgresql://', 'postgresql+', 'postgres://')):
    try:
        pool_size = max(1, min(int(os.environ.get('MOTOSMART_DB_POOL_SIZE', '5')), 50))
    except ValueError:
        pool_size = 5
    try:
        max_overflow = max(0, min(int(os.environ.get('MOTOSMART_DB_MAX_OVERFLOW', '10')), 100))
    except ValueError:
        max_overflow = 10
    try:
        timeout_ms = max(1000, int(os.environ.get('MOTOSMART_DB_TIMEOUT_MS', '15000')))
    except ValueError:
        timeout_ms = 15000
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_size': pool_size,
        'max_overflow': max_overflow,
        'pool_recycle': 1800,
        'connect_args': {
            'connect_timeout': 10,
            'options': f'-c statement_timeout={timeout_ms}',
        },
    }

db = SQLAlchemy(app)
