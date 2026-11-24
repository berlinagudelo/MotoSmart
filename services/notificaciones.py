"""Envío de avisos por correo sin exponer credenciales en el código."""

import logging
import os
import smtplib
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage


logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='motorsmart-mail')

ESTADOS = {
    'recibida': 'Recibida en el taller',
    'diagnostico': 'En diagnóstico',
    'reparacion': 'En reparación',
    'lista': 'Lista para entrega',
    'entregada': 'Entregada',
    'cancelada': 'Cancelada',
}


def enviar_correo(destinatario, asunto, contenido):
    """Envía un correo usando la configuración SMTP del entorno."""
    host = os.getenv('SMTP_HOST')
    remitente = os.getenv('SMTP_FROM')
    if not destinatario or not host or not remitente:
        logger.error('El correo no se envió porque falta la configuración SMTP.')
        return False

    mensaje = EmailMessage()
    mensaje['Subject'] = asunto
    mensaje['From'] = remitente
    mensaje['To'] = destinatario
    mensaje.set_content(contenido)

    try:
        puerto = int(os.getenv('SMTP_PORT', '587'))
        usar_tls = os.getenv('SMTP_TLS', 'true').lower() not in ('0', 'false', 'no')
        usar_ssl = os.getenv('SMTP_SSL', 'false').lower() in ('1', 'true', 'yes') or puerto == 465
        contexto = ssl.create_default_context()
        try:
            intentos = max(1, min(int(os.getenv('SMTP_MAX_ATTEMPTS', '3')), 5))
        except ValueError:
            intentos = 3
        for intento in range(1, intentos + 1):
            try:
                if usar_ssl:
                    with smtplib.SMTP_SSL(host, puerto, timeout=10, context=contexto) as servidor:
                        _autenticar_y_enviar(servidor, mensaje)
                else:
                    with smtplib.SMTP(host, puerto, timeout=10) as servidor:
                        if usar_tls:
                            servidor.starttls(context=contexto)
                        _autenticar_y_enviar(servidor, mensaje)
                return True
            except smtplib.SMTPAuthenticationError:
                # Reintentar con credenciales inválidas solo retrasa el fallo.
                logger.exception('El servidor SMTP rechazó las credenciales de MotoSmart.')
                return False
            except (OSError, smtplib.SMTPException) as error:
                if intento >= intentos:
                    logger.exception('No fue posible enviar un correo de MotoSmart.')
                    return False
                logger.warning(
                    'Fallo temporal al enviar correo (intento %s/%s): %s',
                    intento, intentos, error,
                )
                time.sleep(min(2 ** (intento - 1), 4))
        return False
    except (OSError, ValueError, smtplib.SMTPException):
        logger.exception('No fue posible enviar un correo de MotoSmart.')
        return False


def _autenticar_y_enviar(servidor, mensaje):
    usuario = os.getenv('SMTP_USER')
    contrasena = os.getenv('SMTP_PASSWORD')
    if usuario and contrasena:
        servidor.login(usuario, contrasena)
    servidor.send_message(mensaje)


def enviar_actualizacion_orden(orden):
    """Notifica al propietario después de guardar el cambio de estado."""
    cliente = orden.moto.cliente if orden.moto else None
    destinatario = cliente.email if cliente else None
    if not destinatario:
        return False

    estado = ESTADOS.get(orden.estado, orden.estado.capitalize())
    return enviar_correo(
        destinatario,
        f'MotoSmart: orden {orden.numero} — {estado}',
        f'Hola {cliente.nombre},\n\n'
        f'La orden {orden.numero} de tu {orden.moto.marca} {orden.moto.modelo} '
        f'ahora está: {estado}.\n\n'
        f'Trabajo registrado: {orden.descripcion}\n\n'
        'Puedes consultar el estado actualizado desde MotoSmart.\n\n'
        '— Equipo MotoSmart',
    )


def _enviar_actualizacion_en_contexto(app, orden_id):
    from db import db
    from modelo.orden_servicio import OrdenServicio

    with app.app_context():
        try:
            orden = db.session.get(OrdenServicio, orden_id)
            if orden:
                enviar_actualizacion_orden(orden)
        finally:
            db.session.remove()


def enviar_actualizacion_orden_async(orden_id):
    """Programa el correo fuera del ciclo de la petición.

    El envío SMTP no debe bloquear la respuesta ni consumir un worker durante
    diez segundos. En un despliegue grande, sustituir por una cola dedicada.
    """
    from flask import current_app

    if not current_app.config.get('MOTOSMART_NOTIFICACIONES_ASYNC', True):
        return False
    app = current_app._get_current_object()
    _executor.submit(_enviar_actualizacion_en_contexto, app, orden_id)
    return True
