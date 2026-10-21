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

db = SQLAlchemy(app)
