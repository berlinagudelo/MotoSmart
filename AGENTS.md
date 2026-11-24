# AGENTS.md — Guía de MotoSmart

Aplicación Flask para talleres de motocicletas: multi-taller, JWT, OCR, citas,
órdenes de servicio, inventario, facturación y auditoría.

## Comandos

```powershell
# Dependencias (entorno local)
pip install -r requirements.txt
pip install -r requirements-ocr.txt

# Configuración local (no subir este archivo)
Copy-Item correo.configuracion.ps1.example correo.configuracion.ps1
. .\correo.configuracion.ps1
python run_server.py

# Migraciones versionadas
alembic upgrade head

# Worker de OCR (proceso aparte en producción)
flask --app app procesar-ocr

# Pruebas (SQLite en memoria; CI las repite contra PostgreSQL)
python -m unittest discover -s tests -v

# Retención y derechos de datos
flask --app app aplicar-retencion --dry-run
flask --app app exportar-usuario --email cliente@example.com --salida datos.json
flask --app app anonimizar-usuario --email cliente@example.com

# Crear administrador de un taller existente
flask --app app crear-admin --email admin@taller.com --taller-id 1

# Reinicio destructivo (solo bases desechables)
flask --app app reiniciar-base-talleres --confirmar
```

Variables imprescindibles: `MOTOSMART_DATABASE_URL` y, en producción,
`MOTOSMART_JWT_SECRET_KEY` (≥ 32 caracteres) y `MOTOSMART_PUBLIC_URL` con HTTPS.
Revisa `correo.configuracion.ps1.example` para el resto (SMTP, pool, límites de
subida, notificaciones asíncronas y proxy).

## Arquitectura

- `app.py`: configuración, cabeceras, errores JSON, `/health`, CLI y migraciones ligeras.
- `wsgi.py`: punto de entrada WSGI; en producción se ejecuta con Gunicorn/Waitress y migraciones Alembic.
- `db.py`: SQLAlchemy/PostgreSQL; la app no arranca sin `MOTOSMART_DATABASE_URL`.
- `modelo/`: entidades con FK `ondelete`, índices, checks y unicidad por taller; incluye `TrabajoOCR`.
- `router/`: endpoints por módulo; toda consulta se filtra por `taller_id`.
- `services/validacion.py`: capa única de validación de cuerpos JSON.
- `services/seguridad.py`: rate limiting Redis/memoria y auditoría transaccional.
- `services/ocr_queue.py`: cola persistente y worker de OCR.
- `services/privacidad.py`: exportación, anonimización y retención de datos.
- `services/notificaciones.py`: SMTP con TLS verificado, reintentos y envío asíncrono.
- `migrations/`: revisiones Alembic; `.github/workflows/ci.yml` prueba contra PostgreSQL real.
- `tests/`: aislamiento multi-taller, regresión negativa y controles de producción.

## Invariantes que no se deben romper

1. Nunca leer `data['campo']` directamente: usar `services/validacion.py`.
2. Toda consulta de datos de taller filtra por `taller_id` del JWT.
3. Los errores previsibles responden JSON 400/401/403/404/405/409/413/415; nunca 500.
4. Las facturas pagadas y las órdenes entregadas son inmutables; los borrados con
   dependencias responden 409.
5. Cambiar contraseña o correo, o eliminar un usuario, incrementa
   `token_version` para revocar tokens.
6. Todo cambio sensible se registra con `registrar_auditoria` en la misma
   transacción.
7. Las cantidades de inventario y repuestos son enteras; los montos usan `Decimal`.
8. Los tokens de verificación se guardan hasheados, son de un solo uso y vencen
   en 30 minutos.
9. No introducir credenciales en código, README ni repositorio.
10. Los estáticos se referencian con `url_for`; las fuentes se sirven localmente.

## Estado de la auditoría (`INFORME_AUDITORIA_QA.md`)

Resuelto: CR-01, CR-02, AL-01 a AL-06 y AL-09 a AL-11; paginación/eager loading
en listados críticos; índices FK y `pool_pre_ping`; cabeceras de seguridad y CSP;
fechas de citas y máquina de estados; unique de inventario y talleres; códigos
HTTP/JSON; rol `admin` con CLI; reintentos de correo; timestamps UTC; HTTPS en
producción; validación de `None`; GET individuales y PATCH; numeración por taller;
limpieza de artefactos; fuentes locales; `/health` y versión; `escapeHtml`.

Resuelto en la iteración de producción robusta:

- Sesión en cookie `HttpOnly` + `SameSite=Strict` con CSRF; el frontend ya no usa `localStorage`.
- Rate limiting compartido mediante Redis cuando `MOTOSMART_REDIS_URL` está configurado.
- Alembic con migraciones versionadas y CI contra PostgreSQL 16.
- Cola persistente de OCR con worker independiente, reintentos y recuperación de trabajos atascados.
- Exportación, anonimización y retención de datos personales (API y CLI).
- WSGI de producción (Gunicorn/Waitress), servicios systemd de ejemplo y backups con verificación de restauración.

Pendiente de infraestructura (fuera del código de la aplicación):

- Pruebas de carga y concurrencia con volúmenes reales.
- Backups cifrados y almacenados fuera del servidor (la política/conexión depende del proveedor).
- Monitoreo/alertas externos y rotación de secretos.

Rendimiento y volumen (iteración P0):

- `/prioridades` devuelve solo el último diagnóstico por moto con `ROW_NUMBER()` y excluye motos transferidas.
- `/motos` y `/motos/detalle` resuelven la última orden por página con `ROW_NUMBER()` (`services/consultas.py`), sin cargar el historial completo.
- `/clientes/detalle` limita las citas a hoy en adelante.
- Índices nuevos: `ix_clientes_taller_nombre`, `ix_diagnosticos_taller_moto_fecha`, `ix_ordenes_taller_actualizada`, `ix_registros_pendientes_expira`, `ix_trabajos_ocr_estado_actualizado`; se eliminaron índices simples redundantes.
- Paginación: `per_page` máximo 200; `?total=0` omite el `COUNT(*)`.
- Retención por lotes de `MOTOSMART_RETENCION_LOTE` (5000 por defecto), con confirmación por lote.
- Límite restante: `/prioridades` y los listados sin parámetros siguen devolviendo conjuntos acotados por motos/500 elementos; para decenas de millones de filas hace falta paginar siempre, archivar y evaluar particionado.
