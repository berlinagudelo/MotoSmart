"""Lanzador local para MotoSmart.

El entorno virtual incluido fue creado en otro perfil de Windows. Este archivo
permite reutilizar sus paquetes con la instalacion local de Python 3.14.
"""
from pathlib import Path
import site
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
site.addsitedir(str(ROOT / '.venv' / 'Lib' / 'site-packages'))

from app import app
from db import db # Import db after site.addsitedir to ensure SQLAlchemy is found
from modelo.diagnostico import Diagnostico # Import your models

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
