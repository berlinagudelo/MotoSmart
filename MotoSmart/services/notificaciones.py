"""Envío de avisos por correo sin exponer credenciales en el código."""

import logging
import os
import smtplib
from email.message import EmailMessage


logger = logging.getLogger(__name__)

ESTADOS = {
    'recibida': 'Recibida en el taller',
    'diagnostico': 'En diagnóstico',
    'reparacion': 'En reparación',
    'lista': 'Lista para entrega',
    'entregada': 'Entregada',
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
        with smtplib.SMTP(host, puerto, timeout=10) as servidor:
            if usar_tls:
                servidor.starttls()
            usuario = os.getenv('SMTP_USER')
            contrasena = os.getenv('SMTP_PASSWORD')
            if usuario and contrasena:
                servidor.login(usuario, contrasena)
            servidor.send_message(mensaje)
        return True
    except (OSError, ValueError, smtplib.SMTPException):
        logger.exception('No fue posible enviar un correo de MotoSmart.')
        return False


def enviar_actualizacion_orden(orden):
    """Notifica al propietario después de guardar el cambio de estado.

    La operación del taller no falla si el correo no está configurado o el
    proveedor SMTP no responde. Las credenciales se reciben por variables de
    entorno y nunca se almacenan en la base de datos.
    """
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
        '— Equipo MotoSmart'
    )
