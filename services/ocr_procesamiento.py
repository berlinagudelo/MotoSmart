"""Procesamiento OCR puro, sin acceso a la base de datos."""
from __future__ import annotations

import re
import threading


CODIGO_OBD = re.compile(r'\b([PBCU])\s*([0-9A-F]{3,5})\b', re.IGNORECASE)
_reader = None
_reader_lock = threading.Lock()
_ocr_semaphore = threading.Semaphore(1)


class ErrorOCRNoLegible(ValueError):
    """La imagen no contiene un código OBD reconocible; no vale la pena reintentar."""


def obtener_reader():
    """Carga EasyOCR solo en el proceso trabajador."""
    global _reader
    if _reader is None:
        with _reader_lock:
            if _reader is None:
                import easyocr
                _reader = easyocr.Reader(['es', 'en'])
    return _reader


def separar_lectura_ocr(lineas):
    """Relaciona cada código con la descripción que aparece después en la foto."""
    if isinstance(lineas, str):
        lineas = lineas.splitlines() or [lineas]

    detalles = []
    actual = None

    def guardar_actual():
        if not actual:
            return
        descripcion = ' '.join(actual['fragmentos']).strip(' -:|')
        detalles.append({
            'codigo': actual['codigo'],
            'descripcion': descripcion or 'Requiere revisión del mecánico.',
        })

    for linea_original in lineas:
        linea = ' '.join(linea_original.strip().split())
        if not linea:
            continue
        coincidencias = list(CODIGO_OBD.finditer(linea))
        if not coincidencias:
            if actual:
                actual['fragmentos'].append(linea)
            continue

        for indice, coincidencia in enumerate(coincidencias):
            guardar_actual()
            codigo = f"{coincidencia.group(1).upper()}{coincidencia.group(2).upper()}"
            final = coincidencias[indice + 1].start() if indice + 1 < len(coincidencias) else len(linea)
            resto = linea[coincidencia.end():final].strip(' -:|')
            actual = {'codigo': codigo, 'fragmentos': [resto] if resto else []}

    guardar_actual()
    if not detalles:
        lectura = ' '.join(' '.join(linea.split()) for linea in lineas).strip()
        detalles = [{
            'codigo': 'SIN_CODIGO',
            'descripcion': lectura or 'No se detectó un código de error legible.',
        }]

    codigo = ', '.join(item['codigo'] for item in detalles)
    descripcion = '\n'.join(f"{item['codigo']} - {item['descripcion']}" for item in detalles)
    return codigo, descripcion, detalles


def procesar_imagen(ruta):
    """Ejecuta OCR y devuelve (codigo, descripcion, detalles)."""
    try:
        with _ocr_semaphore:
            resultados = obtener_reader().readtext(ruta)
        lineas = [resultado[1] for resultado in resultados]
    except Exception as error:
        raise RuntimeError(f'No fue posible procesar la imagen: {error}') from error
    codigo, descripcion, detalles = separar_lectura_ocr(lineas)
    if codigo == 'SIN_CODIGO':
        raise ErrorOCRNoLegible(
            'No se detectó ningún código OBD legible. Toma una foto más nítida '
            'o registra una revisión manual.'
        )
    return codigo, descripcion, detalles
