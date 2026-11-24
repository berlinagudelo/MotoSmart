"""Lanzador local para MotoSmart.

El entorno virtual incluido fue creado en otro perfil de Windows. Este archivo
permite reutilizar sus paquetes con la instalacion local de Python 3.14.
"""
from pathlib import Path
import site
import threading
import webbrowser

ROOT = Path(__file__).resolve().parent
# Permite ejecutar el proyecto con el entorno virtual incluido durante el
# desarrollo. En el .exe las dependencias ya las proporciona PyInstaller.
venv_site_packages = ROOT.parent / '.venv' / 'Lib' / 'site-packages'
if venv_site_packages.exists():
    site.addsitedir(str(venv_site_packages))

from app import app, inicializar_base
from services.ocr_queue import iniciar_trabajador_en_hilo

if __name__ == '__main__':
    if app.config.get('MOTOSMART_AUTO_MIGRATE'):
        with app.app_context():
            inicializar_base()
    if app.config.get('MOTOSMART_OCR_INLINE_WORKER'):
        iniciar_trabajador_en_hilo(app)
    url = 'http://127.0.0.1:5000'
    # Arranca Flask primero y abre la interfaz sin que el usuario tenga que
    # escribir la direccion en el navegador.
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
