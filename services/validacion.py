"""Validación de entrada reutilizable para todas las rutas JSON.

Las rutas no deben acceder directamente a ``data['campo']`` ni confiar en el
tipo recibido: cualquier valor inesperado termina en una respuesta 400/409/415
controlada en lugar de un error 500.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request


RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RE_PLACA = re.compile(r"^[A-Z0-9]{5,10}$")
RE_TELEFONO = re.compile(r"^[0-9+()\-\s]{7,20}$")
RE_ENTERO = re.compile(r"^-?\d+$")


class ErrorValidacion(ValueError):
    """Error de entrada con un código HTTP asociado."""

    def __init__(self, mensaje, status=400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status


def cuerpo_json():
    """Devuelve un objeto JSON o lanza un error 400/415 consistente."""
    if not request.is_json:
        if request.data:
            raise ErrorValidacion('El cuerpo de la solicitud debe ser JSON.', 415)
        raise ErrorValidacion('Envía un cuerpo JSON.', 400)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ErrorValidacion('El cuerpo debe ser un objeto JSON.', 400)
    return data


def texto(data, campo, *, requerido=True, default=None, minimo=1, maximo=100,
          lower=False, upper=False, permitir_vacio=False):
    valor = data.get(campo, default)
    if valor is None:
        if requerido:
            raise ErrorValidacion(f'El campo {campo} es obligatorio.')
        return default
    if not isinstance(valor, str):
        raise ErrorValidacion(f'El campo {campo} debe ser texto.')
    valor = valor.strip()
    if not valor:
        if permitir_vacio:
            return default
        if requerido:
            raise ErrorValidacion(f'El campo {campo} no puede estar vacío.')
        return default
    if len(valor) < minimo or len(valor) > maximo:
        raise ErrorValidacion(
            f'El campo {campo} debe tener entre {minimo} y {maximo} caracteres.'
        )
    return valor.lower() if lower else valor.upper() if upper else valor


def email_valor(valor, campo='email'):
    if not isinstance(valor, str):
        raise ErrorValidacion(f'El campo {campo} debe ser un correo válido.')
    valor = valor.strip().lower()
    if len(valor) > 254 or not RE_EMAIL.match(valor):
        raise ErrorValidacion('Ingresa un correo electrónico válido.')
    return valor


def email(data, campo='email', *, requerido=True):
    valor = texto(data, campo, requerido=requerido, maximo=254, lower=True)
    if valor is None:
        return None
    return email_valor(valor, campo)


def telefono(data, campo='telefono', *, requerido=False):
    valor = texto(data, campo, requerido=requerido, maximo=20, permitir_vacio=True)
    if valor is None or valor == '':
        return None
    if not RE_TELEFONO.match(valor):
        raise ErrorValidacion('Ingresa un teléfono válido (7 a 20 caracteres).')
    return valor


def placa(data, campo='placa'):
    valor = texto(data, campo, maximo=10, upper=True)
    if not RE_PLACA.match(valor):
        raise ErrorValidacion('Ingresa una placa válida de 5 a 10 caracteres alfanuméricos.')
    return valor


def entero(data, campo, *, minimo=None, maximo=None, requerido=True, default=None):
    valor = data.get(campo, default)
    if valor is None:
        if requerido:
            raise ErrorValidacion(f'El campo {campo} es obligatorio.')
        return default
    if isinstance(valor, bool):
        raise ErrorValidacion(f'El campo {campo} debe ser un número entero.')
    if isinstance(valor, int):
        numero = valor
    elif isinstance(valor, str) and RE_ENTERO.match(valor.strip()):
        numero = int(valor.strip())
    else:
        raise ErrorValidacion(f'El campo {campo} debe ser un número entero.')
    if minimo is not None and numero < minimo:
        raise ErrorValidacion(f'El campo {campo} debe ser mayor o igual a {minimo}.')
    if maximo is not None and numero > maximo:
        raise ErrorValidacion(f'El campo {campo} no puede superar {maximo}.')
    return numero


def decimal_campo(data, campo, *, minimo=Decimal('0'), maximo=Decimal('9999999999.99'),
                  requerido=True, default=None, decimales='0.01'):
    valor = data.get(campo, default)
    if valor is None:
        if requerido:
            raise ErrorValidacion(f'El campo {campo} es obligatorio.')
        return default
    if isinstance(valor, bool):
        raise ErrorValidacion(f'El campo {campo} debe ser un número válido.')
    try:
        numero = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise ErrorValidacion(f'El campo {campo} debe ser un número válido.') from None
    if not numero.is_finite():
        raise ErrorValidacion(f'El campo {campo} debe ser un número finito.')
    if numero < minimo or numero > maximo:
        raise ErrorValidacion(f'El campo {campo} está fuera del rango permitido.')
    try:
        return numero.quantize(Decimal(decimales))
    except InvalidOperation:
        raise ErrorValidacion(f'El campo {campo} tiene demasiados decimales.') from None


def fecha_campo(data, campo='fecha', *, requerido=True, minimo=None, maximo=None):
    valor = data.get(campo)
    if valor is None or valor == '':
        if requerido:
            raise ErrorValidacion(f'El campo {campo} es obligatorio.')
        return None
    if not isinstance(valor, str):
        raise ErrorValidacion(f'El campo {campo} debe tener formato AAAA-MM-DD.')
    try:
        resultado = datetime.strptime(valor.strip(), '%Y-%m-%d').date()
    except ValueError:
        raise ErrorValidacion(f'El campo {campo} debe tener formato AAAA-MM-DD.') from None
    if minimo and resultado < minimo:
        raise ErrorValidacion(f'El campo {campo} no puede ser anterior a {minimo.isoformat()}.')
    if maximo and resultado > maximo:
        raise ErrorValidacion(f'El campo {campo} no puede ser posterior a {maximo.isoformat()}.')
    return resultado


def booleano(data, campo, *, default=False):
    valor = data.get(campo, default)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.strip().lower() in ('true', '1', 'si', 'sí'):
        return True
    if isinstance(valor, str) and valor.strip().lower() in ('false', '0', 'no'):
        return False
    return bool(valor)


def password(valor, *, campo='password'):
    if not isinstance(valor, str):
        raise ErrorValidacion('La contraseña debe ser texto.')
    if len(valor) < 8:
        raise ErrorValidacion('La contraseña debe tener al menos 8 caracteres.')
    if len(valor) > 128:
        raise ErrorValidacion('La contraseña no puede superar 128 caracteres.')
    if not re.search(r'[A-Za-zÁÉÍÓÚáéíóúÑñ]', valor) or not re.search(r'\d', valor):
        raise ErrorValidacion('La contraseña debe incluir al menos una letra y un número.')
    return valor


def fecha_hoy():
    return date.today()
