"""Consultas agregadas compartidas por varios routers."""
from sqlalchemy import func

from db import db
from modelo.orden_servicio import OrdenServicio


def ultimas_ordenes_por_moto(moto_ids, taller_id):
    """Devuelve ``{moto_id: OrdenServicio}`` con la orden más reciente por moto.

    Usa ``ROW_NUMBER()`` para que la base de datos resuelva el "último por
    grupo" con un solo recorrido, en lugar de traer todo el historial de
    órdenes al proceso Python.
    """
    ids = sorted({int(moto_id) for moto_id in moto_ids if moto_id is not None})
    if not ids:
        return {}

    numeradas = (
        db.session.query(
            OrdenServicio.id.label('orden_id'),
            func.row_number().over(
                partition_by=OrdenServicio.moto_id,
                order_by=(
                    OrdenServicio.actualizada_en.desc(),
                    OrdenServicio.id.desc(),
                ),
            ).label('posicion'),
        )
        .filter(
            OrdenServicio.taller_id == taller_id,
            OrdenServicio.moto_id.in_(ids),
        )
        .subquery()
    )
    ordenes = (
        OrdenServicio.query
        .join(numeradas, OrdenServicio.id == numeradas.c.orden_id)
        .filter(numeradas.c.posicion == 1)
        .all()
    )
    return {orden.moto_id: orden for orden in ordenes}
