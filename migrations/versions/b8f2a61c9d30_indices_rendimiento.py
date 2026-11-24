"""índices de rendimiento y limpieza de índices redundantes

Revision ID: b8f2a61c9d30
Revises: c4d1f0a2b7e9
Create Date: 2026-11-23 10:00:00.000000+00:00

Añade índices para las consultas de mayor volumen (última orden por moto,
cola de prioridades, clientes por nombre, retención y recuperación de OCR) y
elimina índices de una sola columna que ya están cubiertos por índices
compuestos o restricciones únicas.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b8f2a61c9d30'
down_revision: Union[str, None] = 'c4d1f0a2b7e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDICES_NUEVOS = (
    ('ix_clientes_taller_nombre', 'clientes', ('taller_id', 'nombre')),
    (
        'ix_diagnosticos_taller_moto_fecha', 'diagnosticos',
        ('taller_id', 'moto_id', 'fecha', 'id'),
    ),
    (
        'ix_ordenes_taller_actualizada', 'ordenes_servicio',
        ('taller_id', 'actualizada_en'),
    ),
    (
        'ix_registros_pendientes_expira', 'registros_pendientes',
        ('expires_at',),
    ),
    (
        'ix_trabajos_ocr_estado_actualizado', 'trabajos_ocr',
        ('estado', 'actualizado_en'),
    ),
)

INDICES_REDUNDANTES = (
    'ix_citas_taller_id',
    'ix_citas_moto_id',
    'ix_diagnosticos_taller_id',
    'ix_diagnosticos_moto_id',
    'ix_facturas_taller_id',
    'ix_ordenes_servicio_taller_id',
    'ix_ordenes_repuestos_orden_id',
    'ix_usuarios_taller_id',
    'ix_inventario_taller_id',
    'ix_trabajos_ocr_taller_id',
    'ix_trabajos_ocr_estado',
    'ix_trabajos_ocr_creado_en',
    'ix_motos_taller_id',
    'ix_registros_pendientes_email',
    'ix_clientes_taller_id',
)


def upgrade() -> None:
    for nombre, tabla, columnas in INDICES_NUEVOS:
        op.create_index(nombre, tabla, list(columnas), unique=False)
    for nombre in INDICES_REDUNDANTES:
        op.execute(f'DROP INDEX IF EXISTS {nombre}')


def downgrade() -> None:
    for nombre in reversed(INDICES_REDUNDANTES):
        tabla, columna = _tabla_y_columna(nombre)
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {nombre} ON {tabla} ({columna})'
        )
    for nombre, _tabla, _columnas in reversed(INDICES_NUEVOS):
        op.execute(f'DROP INDEX IF EXISTS {nombre}')


def _tabla_y_columna(nombre):
    """Reconstruye tabla/columna de los índices simples eliminados."""
    casos = {
        'ix_citas_taller_id': ('citas', 'taller_id'),
        'ix_citas_moto_id': ('citas', 'moto_id'),
        'ix_diagnosticos_taller_id': ('diagnosticos', 'taller_id'),
        'ix_diagnosticos_moto_id': ('diagnosticos', 'moto_id'),
        'ix_facturas_taller_id': ('facturas', 'taller_id'),
        'ix_ordenes_servicio_taller_id': ('ordenes_servicio', 'taller_id'),
        'ix_ordenes_repuestos_orden_id': ('ordenes_repuestos', 'orden_id'),
        'ix_usuarios_taller_id': ('usuarios', 'taller_id'),
        'ix_inventario_taller_id': ('inventario', 'taller_id'),
        'ix_trabajos_ocr_taller_id': ('trabajos_ocr', 'taller_id'),
        'ix_trabajos_ocr_estado': ('trabajos_ocr', 'estado'),
        'ix_trabajos_ocr_creado_en': ('trabajos_ocr', 'creado_en'),
        'ix_motos_taller_id': ('motos', 'taller_id'),
        'ix_registros_pendientes_email': ('registros_pendientes', 'email'),
        'ix_clientes_taller_id': ('clientes', 'taller_id'),
    }
    return casos[nombre]
