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
from db import db

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        db.session.execute(text('ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS descripcion TEXT'))
        db.session.execute(text('ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS detalle_codigos TEXT'))
        db.session.execute(text('ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS prioridad VARCHAR(20)'))
        db.session.execute(text('ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS motivo_prioridad TEXT'))
        db.session.execute(text('ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS recomendacion TEXT'))
        db.session.commit()
    app.run(debug=False)
