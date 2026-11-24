# Informe de Auditoría Técnica y QA — MotoSmart

**Tipo de auditoría:** Backend, APIs REST, base de datos, validación de datos, seguridad y rendimiento  
**Versión auditada:** copia local `MotoSmart-v_escritorio\MotoSmart`  
**Fecha del informe:** 04/11/2026  
**Rol del auditor:** QA Engineer Senior — Backend / APIs / DB / Security  
**Stack identificado:** Python + Flask 3.x, Flask-SQLAlchemy / SQLAlchemy 2.x, PostgreSQL 14, Flask-JWT-Extended, EasyOCR, HTML/CSS/JS sin framework, PyInstaller.

---

## 0. Resumen ejecutivo

MotoSmart es una aplicación Flask con autenticación JWT, aislamiento multi-taller y módulos de motos, citas, diagnósticos OCR, revisiones mecánicas, inventario, órdenes de servicio y facturación. La arquitectura general es coherente y el aislamiento por taller está bien planteado: las consultas de listado y detalle filtran por `taller_id`, y las pruebas oficiales de aislamiento multi-taller pasan.

Sin embargo, **el sistema no está listo para producción**. La capa de validación de entrada es insuficiente y permite que datos vacíos, nulos, con tipos incorrectos o con formatos inválidos provoquen respuestas HTTP 500 no controladas. Se reprodujeron **16 escenarios distintos con error 500**. Los borrados de motos, clientes e ítems de inventario no respetan la integridad referencial: pueden devolver 500, dejar diagnósticos huérfanos o romper por completo el panel de órdenes. La facturación no tiene trazabilidad ni control de integridad: cualquier mecánico puede editar o eliminar facturas, incluidas las pagadas, sin auditoría.

En seguridad, **no se encontraron SQL Injection, RCE ni fugas de datos entre talleres** en los escenarios probados. Sí se encontraron riesgos altos: creación de cuentas sin verificación de correo y con `username` global (permite ocupar la identidad de un correo ajeno y bloquear al titular legítimo), cambio de contraseña sin solicitar la contraseña actual, tokens que siguen válidos tras cambiar la contraseña o eliminar al usuario, ausencia total de rate limiting, y SMTP con STARTTLS sin validación de certificado.

En rendimiento, el patrón N+1 es severo: **`/motos/detalle` ejecutó 92 consultas SQL para 30 motos** y **`/clientes/detalle` ejecutó 112 consultas para 50 clientes**. No existe paginación en ningún listado. El OCR se ejecuta de forma sincrónica y sin límite de tamaño en servidor.

### Métricas de la auditoría

| Métrica | Resultado |
|---|---:|
| Pruebas oficiales ejecutadas | 5 |
| Pruebas oficiales aprobadas | 5 / 5 |
| Escenarios adversarios ejecutados | 60+ |
| Respuestas HTTP 500 no controladas reproducidas | 16 |
| Consultas SQL en `/motos/detalle` con 30 motos | 92 |
| Consultas SQL en `/clientes/detalle` con 50 clientes | 112 |
| Consultas SQL en `/panel-taller` con 30 órdenes | 21 |
| Hallazgos Críticos | 2 |
| Hallazgos Altos | 12 |
| Hallazgos Medios | 16 |
| Hallazgos Bajos | 12 |

### Veredicto

**No aprobado para producción.** Se requiere corregir los hallazgos Críticos y Altos, agregar una capa de validación y manejo global de errores, implementar controles de integridad referencial y auditoría, y ejecutar la suite contra PostgreSQL real antes de un despliegue.

---

## 1. Alcance, metodología y limitaciones

### 1.1 Alcance revisado

- 10 routers Flask y 40+ endpoints.
- 10 modelos SQLAlchemy y el esquema generado.
- Autenticación, autorización por rol y aislamiento multi-taller.
- Validación de datos de entrada y reglas de negocio.
- Integridad referencial, unicidad, índices y consultas.
- Seguridad backend: JWT, autorización, exposición de datos, uploads, SMTP, errores.
- Rendimiento: N+1, consultas sin paginación, procesos sincrónicos.
- Frontend: consumo de APIs, manejo de token, renderizado dinámico.

### 1.2 Metodología

1. Revisión estática de código y esquema.
2. Ejecución de la suite oficial (`python -m unittest discover -s tests -v`).
3. Construcción de una suite adversaria con `Flask test_client` sobre SQLite en memoria.
4. Verificación de códigos HTTP, cuerpos de respuesta y efectos en base de datos.
5. Medición de consultas SQL con `before_cursor_execute`.
6. Revisión de seguridad de dependencias y flujos de autenticación.
7. Análisis de código para comportamientos específicos de PostgreSQL no reproducibles en SQLite.

### 1.3 Limitaciones

- **No se tuvo acceso a la base PostgreSQL de producción** (sin credenciales); las pruebas dinámicas se ejecutaron sobre SQLite en memoria. Los comportamientos que dependen de PostgreSQL (tipos estrictos, `VARCHAR(n)`, `NUMERIC(12,2)`, claves foráneas activas) se marcan como **riesgo inferido por código**.
- EasyOCR se reemplazó por un mock para las pruebas; no se evaluó la calidad del OCR ni el rendimiento real del modelo.
- SMTP no estaba configurado; los envíos se simularon. No se probó entrega real de correo.
- No se ejecutaron pruebas E2E de navegador ni pruebas de carga con concurrencia real; los hallazgos de concurrencia son análisis de código.
- El frontend se revisó estáticamente, no con un navegador automatizado.

---

## 2. Pruebas funcionales

### 2.1 Resultado general

Los flujos principales de registro, login, creación de taller, carga de motos, citas, facturación, inventario, órdenes y transferencia entre talleres funcionan en el camino feliz. La suite oficial valida correctamente:

- Registro de taller y cliente.
- Aislamiento de inventario y citas por taller.
- Reclamación de datos históricos previa verificación por correo.
- Transferencia de motos y de los tres diagnósticos más recientes.
- Renderizado de la landing y del formulario de registro.

**Pero** el camino no feliz está deficientemente cubierto. Los principales fallos funcionales son:

1. **Citas en fechas pasadas y duplicadas**: se aceptan sin validación.
2. **Borrados destructivos**: eliminar una moto, un cliente o un repuesto en uso produce 500 o deja datos huérfanos.
3. **Estados de orden sin máquina de estados**: una orden entregada puede volver a “recibida”.
4. **Facturación sin control**: cualquier mecánico puede alterar o eliminar facturas pagadas.
5. **OCR sin confirmación**: se guarda un diagnóstico `SIN_CODIGO` aunque no se detecte ningún código.
6. **Inventario sin control de duplicados**: se permiten dos ítems con el mismo nombre.
7. **Cantidades decimales truncadas**: `1.5` se convierte silenciosamente en `1`.

### 2.2 Casos funcionales

| ID | Escenario | Datos de entrada | Resultado esperado | Resultado actual | Estado | Prioridad |
|---|---|---|---|---|---|---|
| F-01 | Crear taller válido | nombre, ciudad, teléfono, titular, email, password | 201 + token + taller | 201 + token | Pass | Alta |
| F-02 | Registrar cliente nuevo y login | email, password, nombre, taller_id | 201 y login 200 | 201 y login 200 | Pass | Alta |
| F-03 | Cliente histórico reclama datos | email con `Cliente` previo | 202 + correo de verificación | 202 + token de un solo uso | Pass | Alta |
| F-04 | Transferir taller A→B | token de verificación | Mueve motos y 3 diagnósticos | Mueve motos y 3 diagnósticos | Pass | Alta |
| F-05 | Aislamiento multi-taller | cliente A intenta moto/cita de B | 404 / lista vacía | 404 / lista vacía | Pass | Crítica |
| F-06 | Cita en fecha pasada | `fecha=2020-01-01` | 400 validación | 201 cita creada | **Fail** | Alta |
| F-07 | Cita duplicada misma moto/fecha | dos POST con misma fecha | 409 / validación | 201 duplicada | **Fail** | Media |
| F-08 | Eliminar moto con citas/facturas | `DELETE /motos/1` | 409 o borrado lógico | 500 `NOT NULL citas.moto_id` | **Fail** | Alta |
| F-09 | Eliminar cliente con motos | `DELETE /clientes/1` | 409 o cascada controlada | 500 `NOT NULL motos.cliente_id` | **Fail** | Alta |
| F-10 | Eliminar repuesto usado en orden | `DELETE /inventario/1` | 409 “en uso” | 200 y posterior 500 en órdenes/panel | **Fail** | Crítica |
| F-11 | Retroceder estado de orden | `entregada → recibida` | 409 transición inválida | 200 estado cambiado | **Fail** | Media |
| F-12 | Revisión mecánica en moto electrónica | moto `electronica` | 400 | 400 | Pass | Media |
| F-13 | Cálculo de factura | subtotal 100, IVA 19 | total 119.00 | total 119.00 | Pass | Alta |
| F-14 | PDF de factura | dueño / otro cliente / otro taller | 200 / 403 / 404 | 200 / 403 / 404 | Pass | Alta |
| F-15 | Panel del taller | 30 órdenes, 20 ítems | 200 con métricas | 200 con métricas | Pass | Media |
| F-16 | OCR sin códigos detectados | imagen sin texto OBD | 422 / requerir revisión | 201 guarda `SIN_CODIGO` | **Fail** | Media |

---

## 3. Testing de APIs

### 3.1 Inventario de endpoints y control de acceso

| Método | Ruta | Autenticación | Rol permitido | Observación |
|---|---|---|---|---|
| GET | `/` | Pública | — | Landing HTML |
| GET | `/talleres` | Pública | — | Lista todos los talleres |
| POST | `/talleres` | Pública | — | Crea taller y titular; sin verificación de correo |
| POST | `/register` | Pública | — | Crea cliente o inicia reclamación |
| GET | `/verificar-registro` | Pública | — | Página HTML |
| POST | `/register/verify` | Token | — | Verifica y crea cuenta / transfiere |
| POST | `/mi-cuenta/verificar-email` | Token | — | Confirma cambio de correo |
| POST | `/login` | Pública | — | Sin rate limiting |
| GET/PUT | `/mi-cuenta` | JWT | Cualquiera | PUT cambia password sin password actual |
| POST | `/mi-cuenta/cambiar-taller` | JWT | Cliente | Envía verificación |
| GET/POST | `/clientes` | JWT | Staff | POST sin validación; 500 en duplicados/nulos |
| PUT/DELETE | `/clientes/<id>` | JWT | Cliente/Admin/Staff | Cliente ignora el id y edita su propio perfil |
| GET | `/clientes/detalle` | JWT | Staff | N+1 |
| GET/POST | `/motos` | JWT | Cliente/Mecánico | POST con accesos directos a claves; 500 |
| GET | `/motos/detalle` | JWT | Staff | N+1 severo |
| DELETE | `/motos/<id>` | JWT | Mecánico | 500 con historial;orfanda diagnósticos |
| POST/GET | `/citas` | JWT | Cliente | Acepta fechas pasadas y duplicadas |
| GET | `/citas/detalle` | JWT | Mecánico | — |
| GET | `/mis_citas` | JWT | Cliente | — |
| PUT/DELETE | `/citas/<id>` | JWT | Mecánico | Cliente no puede cancelar su cita |
| POST | `/upload_scanner` | JWT | Mecánico | OCR sincrónico, sin límite de tamaño |
| GET | `/diagnosticos` | JWT | Staff | Sin paginación |
| GET | `/prioridades` | JWT | Mecánico | Carga y ordena en memoria |
| GET | `/mis_diagnosticos` | JWT | Cliente | — |
| DELETE | `/diagnosticos/<id>` | JWT | Mecánico | Borrado físico sin auditoría |
| POST | `/revisiones-mecanicas` | JWT | Mecánico | — |
| GET/POST | `/inventario` | JWT | Staff/Titular | Titular administra; sin unique de nombre |
| PUT/DELETE | `/inventario/<id>` | JWT | Titular | DELETE en uso rompe órdenes |
| GET/POST | `/facturas` | JWT | Mecánico | Sin idempotencia; `PENDIENTE` concurrente |
| GET | `/mis_facturas` | JWT | Cliente | — |
| PUT/DELETE | `/facturas/<id>` | JWT | Mecánico | Edición/borrado sin auditoría |
| GET | `/facturas/<id>/pdf` | JWT | Staff/Cliente dueño | Autorización correcta |
| GET/POST | `/mecanicos` | JWT | Titular | Crea cuentas sin verificación |
| DELETE | `/mecanicos/<id>` | JWT | Titular | Token sigue válido hasta 1 h |
| GET/POST | `/ordenes-servicio` | JWT | Staff | Descuenta stock al crear; sin cancelación |
| PUT | `/ordenes-servicio/<id>/estado` | JWT | Staff | Sin máquina de estados; SMTP sincrónico |
| GET | `/panel-taller` | JWT | Staff | Agrega en Python y con N+1 |

### 3.2 Hallazgos de API

- **Métodos y semántica inconsistentes**: faltan `GET /motos/<id>`, `GET /clientes/<id>`, `GET /facturas/<id>` y `GET /ordenes-servicio/<id>`. No hay `PATCH`. No existe endpoint para cancelar una orden ni para que un cliente cancele su cita.
- **Códigos HTTP incorrectos**: duplicados y datos nulos devuelven 500 en lugar de 400/409; los 404 y 405 devuelven HTML, no JSON.
- **`PUT /clientes/<id>` ignora el `id` cuando el solicitante es cliente**: devuelve 200 y modifica el perfil propio, lo que rompe el contrato REST y puede confundir a integraciones.
- **`request.get_json()` sin `silent=True`** en varios endpoints devuelve 415 HTML ante `Content-Type` incorrecto.
- **Acceso directo a claves** (`data['placa']`, `data['marca']`, `data['modelo']`, `data['fecha']`) genera `KeyError` → 500.
- **`str(None)` se convierte en `"None"`** en nombres de taller, cliente y mecánico, generando datos basura.
- **Sin cabeceras de seguridad** ni contrato OpenAPI. No hay versión de API (`/api/v1`).

### 3.3 Casos de API y validación

| ID | Escenario | Datos de entrada | Resultado esperado | Resultado actual | Estado | Prioridad |
|---|---|---|---|---|---|---|
| A-01 | POST /motos sin placa | `{marca, modelo}` | 400 | 500 `KeyError: 'placa'` | **Fail** | Alta |
| A-02 | POST /motos placa numérica | `placa=123` | 400 | 500 `AttributeError` | **Fail** | Alta |
| A-03 | POST /motos tipo null | `tipo_tecnologia=null` | 400 | 500 `NoneType.strip` | **Fail** | Alta |
| A-04 | POST /motos marca/modelo vacíos | `""`, `""` | 400 | 201 moto creada | **Fail** | Alta |
| A-05 | POST /motos body array | `[]` | 400 | 500 `list indices` | **Fail** | Media |
| A-06 | POST /motos text/plain | `"hola"` | 415 JSON | 415 HTML | **Fail** | Baja |
| A-07 | POST /clientes nombre null | `nombre=null` | 400 | 500 `NoneType.strip` | **Fail** | Alta |
| A-08 | POST /clientes email duplicado | email existente | 409 | 500 `UNIQUE constraint` | **Fail** | Alta |
| A-09 | POST /clientes email inválido | `sin-arroba` | 400 | 201 cliente creado | **Fail** | Media |
| A-10 | PUT /citas fecha null | `fecha=null` | 400 | 500 `strptime(None)` | **Fail** | Alta |
| A-11 | PUT /citas body vacío | `{}` | 200 sin cambios | 200 sin cambios | Pass | Baja |
| A-12 | PUT /clientes/9999 como cliente | `{nombre:"Hackeado"}` | 403/404 | 200 y modifica perfil propio | **Fail** | Media |
| A-13 | 404 de recurso | `/citas/99999` | JSON 404 | HTML 404 | **Fail** | Baja |
| A-14 | 405 método no permitido | `DELETE /citas` | JSON 405 | HTML 405 | **Fail** | Baja |
| A-15 | Endpoint protegido sin token | `/facturas` | 401 JSON | 401 JSON | Pass | Alta |
| A-16 | Cliente consulta /clientes y /diagnosticos | JWT cliente | 403 | 403 | Pass | Alta |
| A-17 | Upload sin archivo | solo `moto_id` | 400 | 400 | Pass | Media |
| A-18 | Upload archivo `.php` | imagen falsa `.php` | 400 tipo inválido | 201 diagnóstico guardado | **Fail** | Alta |
| A-19 | Cita con `moto_id="abc"` | string no numérico | 400 | 404 en SQLite; riesgo 500 en PostgreSQL | **Fail** | Media |
| A-20 | Registro con taller inexistente | `taller_id=999999` | 404 | 404 | Pass | Media |
| A-21 | Registro con email existente | email ya registrado | 409 | 409 | Pass | Media |
| A-22 | Factura subtotal NaN | `subtotal="NaN"` | 400 | 500 `InvalidOperation` | **Fail** | Alta |
| A-23 | Factura subtotal Infinity | `subtotal="Infinity"` | 400 | 500 `InvalidOperation` | **Fail** | Alta |
| A-24 | Factura subtotal 1e15 | `subtotal="1000000000000000"` | 400/422 | 201 en SQLite; overflow en PostgreSQL | **Fail** | Alta |
| A-25 | Inventario cantidad 1.5 | `cantidad=1.5` | 400 | 201 con cantidad 1 | **Fail** | Media |
| A-26 | Orden cantidad 1.5 | `cantidad=1.5` | 400 | 201 y descuenta 1 | **Fail** | Media |

---

## 4. Validación de datos

### 4.1 Matriz de validación actual vs. esperada

| Campo | Regla esperada | Implementación actual | Riesgo |
|---|---|---|---|
| Email | Formato RFC, ≤254, normalizado, verificado | Solo contiene `@`, ≤50, sin verificación | Alto |
| Password | ≥8/12, complejidad, máximo, bloqueo | ≥6, sin máximo ni complejidad | Medio |
| Nombre | 1–100, sin nulos, sin `"None"` | `str(None)` → `"None"`; sin tipo | Medio |
| Teléfono | 7–20 dígitos | ≤20 caracteres cualesquiera | Bajo |
| Placa | 5–10 alfanumérico, no vacía | `strip().upper()`, sin formato; vacía permitida | Alta |
| Marca/modelo | 1–50, no vacío | `data['marca']` directo; vacío aceptado | Alta |
| Tipo tecnología | `electronica` / `no_electronica` | Validado, pero `null` → 500 | Media |
| Fecha cita | ≥ hoy, rango máximo, no duplicada | Cualquier fecha, duplicados | Alta |
| Descripción cita | ≤200 | Sin límite; 300 aceptados en SQLite | Media |
| Prioridad manual | `BAJA/MEDIA/ALTA` | Validado | Pass |
| Categoría/unidad inventario | Enumerados | Validado | Pass |
| Cantidad inventario | Entero ≥0, cota máxima | `int()` trunca decimales; sin cota | Media |
| Cantidad repuesto | Entero ≥1, ≤stock | `int()` trunca decimales | Media |
| Subtotal factura | Decimal ≥0, ≤ límite DB | Sin cota; NaN/Infinity → 500 | Alta |
| IVA | 0–100 | Validado | Pass |
| Estado factura | `pendiente/pagada` | Validado | Pass |
| Estado orden | Enum + transiciones | Enum, pero sin transiciones | Media |
| IDs | Entero, existente, del taller | Parcial; strings no numéricos dependen del motor | Media |
| Descripción orden | ≤800 | `str()` acepta listas/dicts | Baja |

### 4.2 Hallazgos de validación

- **Validación por lista blanca solo en inventario y facturas**; el resto usa accesos directos y coercion implícita.
- **No hay validación de tipo** antes de `.strip()`, `.upper()` o `strptime()`.
- **No hay validación de longitud** en nombre de cliente/moto/cita antes de la DB; PostgreSQL devolverá error 500 por `VARCHAR(n)`.
- **No hay validación de rango** en fechas ni en montos.
- **No hay validación de formato** de email, teléfono, placa ni coordenadas.
- **No hay validación de unicidad funcional** en inventario (`taller_id, nombre`) ni en citas (`moto_id, fecha`).
- **No hay validación de estado** en transiciones de orden.
- **No hay sanitización de tipos**: `int(1.5)` trunca, `int(True)=1`, `str(None)="None"`.

---

## 5. Testing de base de datos

### 5.1 Esquema observado

Se inspeccionaron las tablas generadas con SQLAlchemy. Puntos relevantes:

| Tabla | PK | Unique | Índices | FK / integridad |
|---|---|---|---|---|
| `talleres` | id | — | — | — |
| `usuarios` | id | `username` | `taller_id` | `taller_id`, `creado_por_id` (self) |
| `clientes` | id | `(taller_id, email)` | `taller_id` | `taller_id` |
| `motos` | id | `(taller_id, placa) WHERE transferida=false` | `taller_id` | `cliente_id`, `taller_id`; **sin índice en `cliente_id`** |
| `citas` | id | — | `taller_id` | `moto_id` **sin índice** |
| `diagnosticos` | id | — | `taller_id` | `moto_id` **nullable** y sin índice |
| `inventario` | id | — | `taller_id` | `taller_id`; sin unique `(taller_id, nombre)` |
| `facturas` | id | `(taller_id, numero)` | `taller_id` | `moto_id` **sin índice** |
| `ordenes_servicio` | id | `(taller_id, numero)` | `taller_id` | `moto_id` **sin índice** |
| `ordenes_repuestos` | id | — | **ninguno** | `orden_id`, `inventario_id` sin índice |

### 5.2 Hallazgos de base de datos

1. **Integridad referencial destructiva**:
   - `DELETE /motos/<id>` con citas/facturas/órdenes devuelve 500.
   - Si la moto solo tiene diagnósticos, el borrado devuelve 200 y los diagnósticos quedan con `moto_id = NULL` (huérfanos). Verificado: el diagnóstico sigue en `/diagnosticos` con `moto: null`, pero desaparece de `/prioridades`.
   - `DELETE /clientes/<id>` con motos devuelve 500.
   - `DELETE /inventario/<id>` referenciado por una orden devuelve 200 en SQLite y luego rompe `/ordenes-servicio` y `/panel-taller` con 500. En PostgreSQL el `DELETE` probablemente falla con `ForeignKeyViolation` no controlada (500).
2. **Sin reglas `ON DELETE`**: SQLAlchemy intenta poner `NULL` en FKs no anulables, lo que produce violaciones `NOT NULL`. No hay `RESTRICT`, `CASCADE` ni borrado lógico.
3. **Índices faltantes en FKs**: `motos.cliente_id`, `citas.moto_id`, `diagnosticos.moto_id`, `facturas.moto_id`, `ordenes_servicio.moto_id`, `ordenes_repuestos.orden_id`, `ordenes_repuestos.inventario_id`. Esto agrava los N+1 y los joins.
4. **Sin `CHECK CONSTRAINT`** para cantidades ≥0, IVA 0–100, estados enumerados, prioridad, tipo de tecnología o rol.
5. **Sin migraciones**: `db.create_all()` y comprobaciones manuales en `inicializar_base()`. No hay Alembic ni control de versiones de esquema. Los cambios de columnas no detectados pueden pasar desapercibidos.
6. **Duplicados funcionales**: dos ítems de inventario con el mismo nombre son aceptados (verificado, 201). Dos talleres con el mismo nombre también.
7. **Diagnósticos huérfanos**: `diagnosticos.moto_id` es nullable. No debería serlo si un diagnóstico siempre pertenece a una moto.
8. **Numeración**: `FAC-<id>` y `OS-<id>` se generan a partir del id global, con huecos al borrar. No son secuencias por taller.
9. **Concurrencia**: `numero='PENDIENTE'` se inserta temporalmente con un unique `(taller_id, numero)`. Dos facturas u órdenes concurrentes en el mismo taller pueden colisionar en el flush y devolver 500.
10. **Fechas**: mezcla de `datetime.utcnow()` (naive), `db.func.current_timestamp()` y `date.today()` local. Ordenamientos y cortes de “mes” pueden desfasarse.
11. **Sin auditoría**: no hay tablas de historial para facturas, órdenes, inventario ni accesos. Los `DELETE` son físicos.

### 5.3 Casos de base de datos

| ID | Escenario | Datos de entrada | Resultado esperado | Resultado actual | Estado | Prioridad |
|---|---|---|---|---|---|---|
| D-01 | Placa duplicada activa en taller | misma placa | 400/409 | 400 | Pass | Alta |
| D-02 | Email duplicado en taller | mismo email | 409 | 500 | **Fail** | Alta |
| D-03 | Borrar moto con citas | moto con cita | 409 / cascada controlada | 500 | **Fail** | Alta |
| D-04 | Borrar moto solo con diagnóstico | moto + diagnóstico | 409 / soft delete | 200 y diagnóstico huérfano | **Fail** | Crítica |
| D-05 | Borrar cliente con motos | cliente + moto | 409 / cascada | 500 | **Fail** | Alta |
| D-06 | Borrar ítem usado en orden | ítem + orden | 409 | 200 y posteriores 500 | **Fail** | Crítica |
| D-07 | Duplicar nombre de inventario | dos “Aceite” | 409 | 201 duplicado | **Fail** | Media |
| D-08 | Índices FK | inspección de esquema | Índices en todas las FK | Faltan 7 | **Fail** | Alta |
| D-09 | Check constraints | cantidad=-1 vía DB | Rechazo | Aceptado | **Fail** | Media |
| D-10 | Diagnóstico sin moto | `moto_id=NULL` | Rechazo | Permitido | **Fail** | Media |
| D-11 | Migraciones | cambio de columna | Migración versionada | `create_all` + chequeo manual | **Fail** | Alta |
| D-12 | Numeración concurrente | dos POST simultáneos | Números únicos | Riesgo de colisión `PENDIENTE` | **Fail** | Media |

---

## 6. Pruebas negativas

Se ejecutaron escenarios de datos vacíos, tipos incorrectos, formatos inválidos, duplicados, IDs inexistentes, autenticación incorrecta y permisos insuficientes.

| ID | Escenario negativo | Resultado esperado | Resultado actual | Estado |
|---|---|---|---|---|
| N-01 | Body vacío en POST /motos | 400 JSON | 500 `KeyError` | **Fail** |
| N-02 | `null` en campos de texto | 400 JSON | 500 `AttributeError` | **Fail** |
| N-03 | Array JSON donde se espera objeto | 400 JSON | 500 | **Fail** |
| N-04 | Email sin `@` en `/clientes` | 400 | 201 | **Fail** |
| N-05 | Email duplicado en `/clientes` | 409 | 500 | **Fail** |
| N-06 | Fecha inválida `2026-13-40` | 400 | 400 | Pass |
| N-07 | Fecha pasada en cita | 400 | 201 | **Fail** |
| N-08 | Cita duplicada | 409 | 201 | **Fail** |
| N-09 | ID inexistente en PUT /citas | 404 JSON | 404 HTML | **Fail** |
| N-10 | ID de otra moto/taller | 404 | 404 | Pass |
| N-11 | Token ausente | 401 JSON | 401 JSON | Pass |
| N-12 | Token inválido/firmado con otra clave | 422/401 | 422/401 (librería) | Pass |
| N-13 | Token de usuario eliminado | 401 | 200 en `/inventario`, `/ordenes-servicio`, `/citas/detalle` (vacío) | **Fail** |
| N-14 | Rol cliente en endpoints de staff | 403 | 403 | Pass |
| N-15 | Rol mecánico no titular en `/mecanicos` | 403 | 403 | Pass |
| N-16 | Password incorrecta | 401 | 401 | Pass |
| N-17 | SQLi en login | 401 sin error SQL | 401 | Pass |
| N-18 | SQLi en filtros | Sin inyección | ORM parametrizado | Pass |
| N-19 | Upload sin archivo | 400 | 400 | Pass |
| N-20 | Upload `.php` | 400 | 201 | **Fail** |
| N-21 | Upload >10 MB | 413 | Sin límite en servidor | **Fail** |
| N-22 | Reuso de token de verificación | 400 | 400 | Pass |
| N-23 | Token de verificación falso | 400 | 400 | Pass |
| N-24 | Registro con taller inexistente | 404 | 404 | Pass |
| N-25 | Registro con email ya usado | 409 | 409 | Pass |
| N-26 | Cambio de contraseña sin contraseña actual | 401/400 | 200 | **Fail** |
| N-27 | Uso de token antiguo tras cambiar contraseña | 401 | 200 | **Fail** |
| N-28 | Cuenta de mecánico con email de un tercero | 400/202 verificación | 201 y login con contraseña del atacante | **Fail** |
| N-29 | Taller creado con email de un cliente histórico | 202 verificación | 201 y consumo del email | **Fail** |
| N-30 | Cantidad decimal en inventario/orden | 400 | 201 con truncamiento | **Fail** |

---

## 7. Seguridad backend

### 7.1 Controles positivos encontrados

- **SQL Injection**: no se encontraron consultas concatenadas ni SQL crudo con entrada de usuario. Todas las consultas usan el ORM y parámetros vinculados. La única cláusula `text()` es estática (`transferida = false`).
- **Aislamiento multi-taller**: las consultas de listado y detalle filtran por `taller_id`; las pruebas de acceso cruzado devolvieron 404/403. No se confirmaron fugas entre talleres.
- **Hashing de contraseñas**: Werkzeug `generate_password_hash` / `check_password_hash` (scrypt por defecto en Flask 3).
- **JWT firmado**: secreto de al menos 32 caracteres; `create_access_token` con claims; algoritmo por defecto HS256.
- **Tokens de verificación**: 32 bytes aleatorios, hash SHA-256 en base, un solo uso, expiración 30 minutos, enlace en fragmento (`#token`) y `referrer: no-referrer`.
- **Autorización de PDF**: un cliente solo descarga facturas de sus propias motos en su taller; verificado 403/404.
- **Bloqueo de stock**: `with_for_update()` al crear órdenes, lo que evita sobreventa en concurrencia.
- **Cálculo de totales**: `Decimal`, `ROUND_HALF_UP`; el total se recalcula en servidor.
- **Secretos**: no hay credenciales hardcodeadas; la conexión se exige por variable de entorno.

### 7.2 Hallazgos de seguridad

| ID | Hallazgo | Severidad | Evidencia | Impacto | CWE/OWASP |
|---|---|---|---|---|---|
| CR-01 | Facturas editables/eliminables por cualquier mecánico, sin auditoría ni bloqueo de pagadas | **Crítico** | `router/facturas.py:180-207`; verificado con mecánico no titular: PUT 200 y DELETE 200 | Fraude, repudio, pérdida de ingresos, imposibilidad de conciliar | CWE-284 / A01 |
| CR-02 | Borrados destructivos y sin integridad referencial | **Crítico** | `router/motos.py:147-157`, `router/clientes.py:106-116`, `router/inventario.py:96-106`; 500 y diagnósticos huérfanos verificados | Pérdida de historial, indisponibilidad del panel, datos inconsistentes | CWE-20 / A04 |
| AL-01 | Validación de entrada ausente; 16 respuestas 500 | **Alto** | `motos.py:55-110`, `clientes.py:14-26`, `citas.py:59-80`, `facturas.py:35-62` | DoS lógico, errores filtrados, datos basura | CWE-20 / A03 |
| AL-02 | Registro y creación de mecánicos sin verificación de correo; `username` global | **Alto** | `auth.py:142-199`, `mecanicos.py:37-62`; verificado: mecánico con email de tercero 201, login 200, registro legítimo 409 | Ocupación de identidad, bloqueo de reclamo de datos, suplantación | CWE-287 / A07 |
| AL-03 | Cambio de contraseña sin contraseña actual y sin revocación de tokens | **Alto** | `auth.py:504-539`; verificado 200 sin password actual y token antiguo 200 | Takeover persistente si se roba un token | CWE-620 / A07 |
| AL-04 | Sin rate limiting, sin lockout y contraseña mínima de 6 | **Alto** | `auth.py:441-451`; no hay Flask-Limiter | Fuerza bruta, credential stuffing, spam de registros | CWE-307 / A07 |
| AL-05 | SMTP STARTTLS sin validación de certificado | **Alto** | `services/notificaciones.py:37-39`; `smtplib.starttls()` sin `context` usa `ssl._create_stdlib_context` con `CERT_NONE` | MITM de credenciales SMTP y tokens de verificación | CWE-295 / A02 |
| AL-06 | Upload/OCR sin límite de tamaño en servidor, sin validación de MIME y sincrónico | **Alto** | `router/scanner.py:18,67-118`; no hay `MAX_CONTENT_LENGTH` | DoS por CPU/RAM/disco; agotamiento de workers | CWE-770 / A05 |
| AL-07 | N+1 y ausencia de paginación | **Alto** | Medición: 92 consultas / 30 motos; 112 / 50 clientes | Degradación lineal; timeouts con volumen | CWE-400 / A04 |
| AL-08 | Sin migraciones; `create_all` + chequeos manuales | **Alto** | `app.py:59-90`, `db.py:16` | Drift de esquema, despliegues fallidos, pérdida de datos | CWE-1059 |
| AL-09 | Órdenes sin idempotencia, cancelación ni restauración de stock | **Alto** | `ordenes_servicio.py:62-109`; stock se descuenta al crear y no se devuelve | Doble descuento por reintento; inventario irreal | CWE-837 |
| AL-10 | Falta de auditoría de cambios | **Alto** | No hay tablas de historial; `DELETE` físicos | No repudio, imposible investigar fraude o errores | CWE-778 / A09 |
| AL-11 | Secreto JWT efímero si falta la variable | **Alto** | `app.py:23-33`; warning y clave aleatoria por proceso | Sesiones inválidas al reiniciar; tokens incompatibles entre workers | CWE-522 |
| AL-12 | Suite de pruebas solo SQLite + mocks | **Alto** | `tests/test_multi_tenant.py:13-18`; 5 tests | Falsa confianza; no detecta FKs, longitudes ni tipos de PostgreSQL | CWE-1059 |
| ME-01 | Citas en pasado, duplicadas y sin cancelación por cliente | **Medio** | `citas.py:53-80,106-145` | Agenda inconsistente; clientes no pueden cancelar | CWE-20 |
| ME-02 | Transiciones de estado de orden libres | **Medio** | `ordenes_servicio.py:112-130`; verificado entregada→recibida 200 | Estados imposibles, métricas erróneas | CWE-20 |
| ME-03 | Truncamiento numérico y falta de cotas | **Medio** | `inventario.py:36`, `ordenes_servicio.py:42`; `int(1.5)=1` | Inventario y cobros incorrectos | CWE-681 |
| ME-04 | Duplicados funcionales | **Medio** | `inventario.py` sin unique; verificado 201 | Compras/stock duplicados | CWE-20 |
| ME-05 | Enumeración de usuarios y de datos históricos | **Medio** | `register` 409/202; `login` timing | Reconocimiento para ataques dirigidos | CWE-204 |
| ME-06 | Token en `localStorage`, sin CSP ni cabeceras de seguridad | **Medio** | `static/js/app.js:2,128,1070`; `templates/partials/head.html` | Robo de token ante XSS; clickjacking/MIME sniffing | CWE-79/CWE-1021 |
| ME-07 | Manejo de errores inconsistente | **Medio** | 500/404/405/415 HTML; `app.py` sin error handlers | Mala UX, filtración de stack traces en debug | CWE-209 |
| ME-08 | Rol `admin` documentado pero inalcanzable e inconsistente | **Medio** | `README.md:23`; no hay endpoint que cree admin; `admin` permitido en unos módulos y no en otros | Funcionalidad documentada inexistente; deuda de autorización | CWE-284 |
| ME-09 | SMTP sincrónico con timeout de 10 s | **Medio** | `notificaciones.py:37`; llamado en `actualizar_estado` | Latencia y agotamiento de workers si SMTP falla | CWE-400 |
| ME-10 | Índices FK faltantes | **Medio** | Inspección de esquema | Consultas lentas, locks más amplios | CWE-400 |
| ME-11 | Fechas naive/mezcladas | **Medio** | `datetime.utcnow`, `current_timestamp`, `date.today()` | Cortes de mes y ordenamientos incorrectos | CWE-1059 |
| ME-12 | `RegistroPendiente.email` único global | **Medio** | `modelo/registro_pendiente.py:8`; `auth.py:54-61` | Bloquea verificaciones paralelas entre talleres/tipos | CWE-20 |
| ME-13 | Sin recuperación de contraseña; titular fija contraseña de mecánicos | **Medio** | No hay endpoint de reset; `mecanicos.py:44-60` | Bloqueo de cuentas; impersonación por el titular | CWE-640 |
| ME-14 | PII en JWT y logs; sin retención/exportación/borrado | **Medio** | `auth.py:36-47`; `logger.exception` en notificaciones | Privacidad y cumplimiento (Habeas Data/GDPR) | CWE-312 |
| ME-15 | `MOTOSMART_PUBLIC_URL` HTTP por defecto y sin HTTPS forzado | **Medio** | `app.py:37-39`; README | Tokens de verificación viajan por HTTP si se despliega mal | CWE-319 |
| ME-16 | Servidor de desarrollo y sin pool/healthcheck | **Medio** | `run_server.py:29`; `db.py` sin `engine_options` | No apto para producción; conexiones obsoletas | CWE-1059 |
| BE-01 | `str(None)` → `"None"` | **Bajo** | `auth.py:103-119`; verificado taller “None” 201 | Datos basura | CWE-20 |
| BE-02 | `PUT /clientes/<id>` ignora el id para clientes | **Bajo** | `clientes.py:55-62`; verificado 200 | Contrato REST confuso | CWE-20 |
| BE-03 | Faltan GET individuales/PATCH; cliente no puede borrar su moto | **Bajo** | Rutas inexistentes | API incompleta | — |
| BE-04 | Numeración global con huecos | **Bajo** | `facturas.py:175`, `ordenes_servicio.py:103` | Reportes y secuencias poco profesionales | — |
| BE-05 | Artefactos y `.gitignore` incompleto | **Bajo** | `temp.png`; `.gitignore` solo 4 líneas | Ruido y riesgo de subir artefactos | — |
| BE-06 | Código muerto e imports sin uso | **Bajo** | `roles.py` no se importa; `Diagnostico` en `run_server.py` | Mantenibilidad | — |
| BE-07 | Fuentes externas sin SRI y rutas `../static` | **Bajo** | `head.html:5-8`, `index.html:33-34` | Privacidad y rotura fuera de `/` | — |
| BE-08 | `datetime.utcnow` deprecado | **Bajo** | `factura.py:21`, `orden_servicio.py:17-18` | Deuda técnica | — |
| BE-09 | `temp_uploads` relativo al CWD y extensión original | **Bajo** | `scanner.py:85-88` | Dependencia del directorio de ejecución | — |
| BE-10 | Sin `/health` ni versión de API | **Bajo** | — | Operación/observabilidad | — |
| BE-11 | `escapeHtml` no escapa comillas | **Bajo** | `app.js:64-68` | XSS latente en atributos HTML | CWE-79 |
| BE-12 | Talleres duplicados por nombre | **Bajo** | `modelo/taller.py` sin unique | Confusión operativa | — |

### 7.3 Análisis específico de los vectores solicitados

| Vector | Resultado | Detalle |
|---|---|---|
| SQL Injection | **No encontrado** | ORM parametrizado; no hay concatenación de SQL con entrada. |
| JWT mal implementado | **Parcial** | Firma y expiración correctas; faltan revocación, rotación, verificación de rol en DB y secreto persistente. |
| Autorización incorrecta | **Hallazgos** | Facturas editables/borrables por cualquier mecánico; admin inconsistente; tokens de eliminados siguen aceptándose. |
| Exposición de datos sensibles | **Hallazgos** | PII en JWT/logs; emails/teléfonos a todo el staff; enlaces HTTP por defecto. |
| Validaciones faltantes | **Crítico/Alto** | 16 respuestas 500; tipos, longitudes, rangos y formatos sin validar. |
| Endpoints inseguros | **Hallazgos** | Upload sin límite/tipo; OCR sincrónico; sin rate limiting; SMTP sin verificación de certificado. |

---

## 8. Rendimiento

### 8.1 Medición de consultas SQL

Se instrumentó SQLAlchemy con `before_cursor_execute` y se ejecutaron los endpoints con datos de prueba:

| Endpoint | Datos | Consultas SQL | Evaluación |
|---|---:|---:|---|
| `GET /motos/detalle` | 30 motos, 30 órdenes | **92** | N+1 severo (~3 por moto) |
| `GET /motos` | 30 motos | 32 | N+1 por órdenes |
| `GET /clientes/detalle` | 50 clientes, 30 motos, 30 citas | **112** | N+1 por motos y citas |
| `GET /diagnosticos` | 30 diagnósticos | 32 | N+1 por `diagnostico.moto` |
| `GET /prioridades` | 30 diagnósticos | 32 | N+1 + carga total |
| `GET /panel-taller` | 30 órdenes, 20 ítems | 21 | Agrega en Python |
| `GET /ordenes-servicio` | 30 órdenes | **92** | N+1 por moto, cliente, repuestos e ítems |
| `GET /inventario` | 20 ítems | 2 | Correcto |

### 8.2 Cuellos de botella identificados

1. **N+1 en serializadores**: `serializar_moto()` recorre `moto.ordenes_servicio`; `serializar()` de órdenes recorre `moto`, `moto.cliente`, `orden.repuestos` y `repuesto.item`; `serializar_diagnostico()` accede a `diagnostico.moto`.
2. **Sin paginación**: `/motos`, `/motos/detalle`, `/clientes`, `/clientes/detalle`, `/diagnosticos`, `/prioridades`, `/facturas`, `/ordenes-servicio`, `/inventario` cargan todos los registros.
3. **Agregaciones en Python**: `/panel-taller` carga todas las órdenes y facturas para sumar; debería usar `SUM`, `COUNT`, `FILTER` en SQL.
4. **Ordenamiento en memoria**: `/prioridades` carga todos los diagnósticos, los agrupa en un dict y ordena en Python; PostgreSQL puede hacerlo con `DISTINCT ON` o window functions.
5. **Índices faltantes** en FKs, lo que penaliza joins y borrados.
6. **OCR en el request**: `easyocr.Reader` se instancia al importar el módulo y `readtext()` se ejecuta de forma sincrónica; cada imagen bloquea un worker.
7. **SMTP en el request**: el cambio de estado espera hasta 10 s por el envío de correo.
8. **Sin caché** para `/talleres`, que se consulta en cada carga del formulario de registro.
9. **Pool por defecto**: sin `pool_pre_ping`, `pool_size` ni `max_overflow`; los procesos lentos pueden agotar conexiones.
10. **Frontend**: `boot()` dispara `loadMotos()` y `loadDiagnostics()` en paralelo (bien), pero cada vista vuelve a cargar datos sin caché.

### 8.3 Oportunidades de optimización

- `selectinload`/`joinedload` para motos→órdenes, órdenes→repuestos→ítem, clientes→motos→citas, diagnósticos→moto.
- Paginación cursor/offset con límite máximo (por ejemplo, 50–100).
- `COUNT`/`SUM` en SQL para el panel.
- `DISTINCT ON (moto_id)` en PostgreSQL para la última prioridad.
- Índices compuestos: `(taller_id, fecha)`, `(taller_id, estado)`, `(moto_id, fecha)`.
- Mover OCR y correo a una cola (Celery/RQ) o a un `ThreadPoolExecutor` con límite.
- Cachear talleres con TTL corto.
- Añadir `pool_pre_ping=True`, `pool_size`, `max_overflow` y timeouts.
- Pruebas de carga con k6/Locust y `EXPLAIN (ANALYZE, BUFFERS)` en PostgreSQL.

---

## 9. Informe final

### 9.1 Hallazgos críticos

#### CR-01 — Facturación sin control de integridad ni trazabilidad

- **Descripción:** cualquier usuario con rol `mecanico` (titular o no) puede crear, editar y eliminar facturas. Se puede cambiar el subtotal, el IVA, el total, la moto, la descripción y el estado, incluso de una factura pagada. El borrado es físico y no queda registro.
- **Evidencia:** `router/facturas.py:180-207`. Verificado con un mecánico no titular: `PUT /facturas/1` → 200 con total alterado; `DELETE /facturas/1` → 200; `GET /facturas` → `[]`.
- **Impacto:** fraude interno, repudio, imposibilidad de conciliar ingresos, incumplimiento fiscal/contable.
- **Recomendación:** separar roles (quien factura no debería poder borrar), prohibir el borrado físico, implementar `estado` inmutable tras “pagada” (notas de crédito en su lugar), auditar cada cambio con usuario/fecha/valores anteriores y nuevos, y bloquear la edición de campos monetarios después de emitir.

#### CR-02 — Borrados destructivos e integridad referencial

- **Descripción:** los endpoints de borrado no verifican dependencias. `DELETE /motos/<id>` con citas/facturas/órdenes devuelve 500; con solo diagnósticos devuelve 200 y deja los diagnósticos huérfanos (`moto_id=NULL`). `DELETE /clientes/<id>` con motos devuelve 500. `DELETE /inventario/<id>` usado en una orden devuelve 200 en SQLite y luego rompe `/ordenes-servicio` y `/panel-taller`.
- **Evidencia:** `router/motos.py:147-157`, `router/clientes.py:106-116`, `router/inventario.py:96-106`; `ordenes_servicio.py:30-32` (desreferencia `repuesto.item` sin comprobar `None`). Verificado: 500, 200 + diagnóstico huérfano, 200 + 500 posterior.
- **Impacto:** pérdida de historial de servicio, corrupción de datos, indisponibilidad del panel, imposibilidad de auditar.
- **Recomendación:** definir política de borrado (`RESTRICT` por defecto, `CASCADE` solo donde corresponda), usar soft delete para motos/clientes/facturas, impedir borrar ítems con movimientos, hacer `moto_id` no nullable, y devolver 409 con detalle en lugar de 500.

### 9.2 Hallazgos altos

| ID | Hallazgo | Impacto | Corrección mínima |
|---|---|---|---|
| AL-01 | 16 respuestas 500 por validación ausente | DoS lógico, datos basura, mala UX | Esquemas de validación + error handlers globales |
| AL-02 | Cuentas sin verificación de correo y username global | Ocupación de identidad y bloqueo de reclamo | Verificación obligatoria o período de gracia + rate limit + reclamo seguro |
| AL-03 | Cambio de contraseña sin password actual y sin revocación | Takeover persistente | Exigir password actual; `token_version`/blocklist; invalidar sesiones |
| AL-04 | Sin rate limiting ni lockout; password de 6 | Fuerza bruta/credential stuffing | Flask-Limiter, lockout progresivo, política ≥12 |
| AL-05 | SMTP sin validación de certificado | MITM de credenciales/tokens | `ssl.create_default_context()` en `starttls()` |
| AL-06 | Upload/OCR sin límite, tipo ni cola | DoS de CPU/RAM/workers | `MAX_CONTENT_LENGTH`, MIME/magic bytes, cola, límites por usuario |
| AL-07 | N+1 y sin paginación | Timeouts con volumen | Eager loading, paginación, agregaciones SQL |
| AL-08 | Sin migraciones | Drift y despliegues frágiles | Alembic + CI de migraciones |
| AL-09 | Órdenes sin idempotencia/cancelación/restauración | Stock irreal, doble descuento | Idempotency-Key, endpoint de cancelación, movimientos de stock |
| AL-10 | Sin auditoría | No repudio | Tabla `audit_log` y triggers/servicio |
| AL-11 | Secreto JWT efímero | Sesiones rotas/multi-worker | Exigir secreto persistente en producción |
| AL-12 | Tests solo SQLite/mocks | Falsa confianza | Testcontainers PostgreSQL + pruebas negativas |

### 9.3 Hallazgos medios

- Citas en pasado/duplicadas y sin cancelación por cliente.
- Transiciones de estado de orden sin máquina de estados.
- Truncamiento de cantidades decimales y falta de cotas.
- Duplicados de inventario y de talleres.
- Enumeración de usuarios y de datos históricos.
- Token en `localStorage`, sin CSP ni cabeceras de seguridad.
- Errores HTML 404/405/415 y stack traces en debug.
- Rol `admin` documentado pero inalcanzable e inconsistente.
- SMTP sincrónico sin cola ni reintentos.
- Índices FK faltantes.
- Fechas naive/mezcladas.
- `RegistroPendiente.email` único global.
- Sin recuperación de contraseña; titular fija password de mecánicos.
- PII en JWT/logs y sin retención/exportación/borrado.
- `MOTOSMART_PUBLIC_URL` HTTP por defecto y sin HTTPS forzado.
- Servidor de desarrollo y sin pool/healthcheck.

### 9.4 Hallazgos bajos

- `str(None)` → `"None"`.
- `PUT /clientes/<id>` ignora el id para clientes.
- Faltan GET individuales/PATCH y borrado de moto por cliente.
- Numeración global con huecos.
- `temp.png` y `.gitignore` incompleto.
- Código muerto (`roles.py`) e imports sin uso.
- Fuentes externas sin SRI y rutas `../static`.
- `datetime.utcnow` deprecado.
- `temp_uploads` relativo al CWD y extensión original aceptada.
- Sin `/health` ni versión de API.
- `escapeHtml` no escapa comillas.
- Talleres duplicados por nombre.

### 9.5 Recomendaciones técnicas

#### Inmediatas (0–7 días)

1. Crear una capa de validación única (Marshmallow/Pydantic) para todos los endpoints: tipos, longitudes, rangos, enums, fechas, emails, placas y montos.
2. Añadir `@app.errorhandler` para `HTTPException`, `IntegrityError`, `ValueError` y `Exception`, devolviendo JSON consistente y haciendo `rollback`.
3. Corregir borrados: `RESTRICT`/soft delete, `moto_id` no nullable, bloquear ítems con movimientos y devolver 409.
4. Exigir la contraseña actual para cambiarla y añadir `token_version` o blocklist JWT; invalidar tokens al cambiar contraseña, correo o eliminar usuario.
5. Implementar rate limiting en `/login`, `/register`, `/talleres`, `/upload_scanner` y `/mi-cuenta/*`.
6. Configurar `MAX_CONTENT_LENGTH`, validar MIME/magic bytes y mover OCR a una cola.
7. Usar `ssl.create_default_context()` en SMTP y exigir `MOTOSMART_PUBLIC_URL` HTTPS en producción.
8. Añadir `audit_log` y bloquear edición/borrado de facturas pagadas.
9. Añadir índices FK y `pool_pre_ping`.

#### Corto plazo (2–4 semanas)

1. Introducir Alembic y un pipeline de migraciones.
2. Paginación y eager loading en todos los listados; reescribir `/panel-taller` y `/prioridades` con SQL agregado.
3. Verificación de correo obligatoria para nuevas cuentas o mecanismo de reclamación seguro; revisar el modelo de `username` global.
4. Máquina de estados para órdenes y movimientos de stock con compensación.
5. Rol `admin` real o eliminar la promesa del README; centralizar autorización con `rol_required`/políticas.
6. Tests de integración con PostgreSQL (Testcontainers), pruebas negativas para cada 500, pruebas de concurrencia y de carga.
7. CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, HSTS y revisión de `localStorage`.
8. Recuperación de contraseña con token de un solo uso y verificación; no permitir que el titular fije la contraseña del mecánico sin invitación.

#### Mediano plazo

1. Observabilidad: logs estructurados, métricas, trazas, alertas de 5xx y latencia.
2. Backups automáticos y prueba de restauración.
3. Revisión de privacidad: retención, exportación y borrado de datos; minimización de PII.
4. Endurecimiento de despliegue: WSGI de producción, HTTPS, secretos gestionados, WAF.
5. Pruebas de seguridad automatizadas (SAST/DAST) y escaneo de dependencias.

### 9.6 Checklist de correcciones

#### Bloqueantes

- [ ] CR-01: bloquear edición/borrado de facturas pagadas; auditoría inmutable.
- [ ] CR-02: `RESTRICT`/soft delete; `diagnosticos.moto_id NOT NULL`; 409 en dependencias.
- [ ] AL-01: validación + error handlers; 0 respuestas 500 en suite negativa.
- [ ] AL-02: verificación de correo o reclamo seguro; revisar `username` global.
- [ ] AL-03: password actual + revocación de tokens.
- [ ] AL-04: rate limiting y política de contraseñas.
- [ ] AL-05: SMTP con `create_default_context`.
- [ ] AL-06: límite de upload, validación de tipo y cola OCR.
- [ ] AL-09: idempotencia y cancelación de órdenes con restauración de stock.
- [ ] AL-10: `audit_log` para facturas, órdenes, inventario y accesos.

#### Altas

- [ ] AL-07: paginación y eager loading; medir consultas por endpoint.
- [ ] AL-08: Alembic y migraciones versionadas.
- [ ] AL-11: secreto JWT persistente obligatorio en producción.
- [ ] AL-12: suite PostgreSQL + pruebas negativas + concurrencia.
- [ ] Índices FK y `pool_pre_ping`.
- [ ] Cabeceras de seguridad y CSP.
- [ ] Recuperación de contraseña.

#### Medias

- [ ] Validar fechas de citas (≥ hoy, rango, duplicados).
- [ ] Máquina de estados de órdenes.
- [ ] Unique `(taller_id, nombre)` en inventario.
- [ ] Rechazar decimales en cantidades; cotas máximas.
- [ ] Unificar códigos HTTP y JSON en 404/405/415.
- [ ] Implementar o eliminar el rol `admin`.
- [ ] Cola/reintentos para correo.
- [ ] Normalizar timestamps a UTC con zona.
- [ ] Revisar PII en JWT/logs.
- [ ] Forzar HTTPS y `MOTOSMART_PUBLIC_URL`.

#### Bajas

- [ ] Rechazar `None` en nombres; no usar `str(None)`.
- [ ] Respetar el `id` en `PUT /clientes/<id>` o cambiar el contrato.
- [ ] Añadir GET individuales y PATCH.
- [ ] Numeración por taller sin huecos.
- [ ] Limpiar `temp.png` y completar `.gitignore`.
- [ ] Eliminar código muerto e imports sin uso.
- [ ] Añadir SRI o autohospedar fuentes; usar `url_for` para estáticos.
- [ ] Reemplazar `datetime.utcnow`.
- [ ] Hacer `temp_uploads` configurable y validar extensión.
- [ ] Añadir `/health` y versión de API.
- [ ] Escapar comillas en `escapeHtml`.
- [ ] Unique de nombre de taller o advertencia.

### 9.7 Criterios de salida (Definition of Done)

- 0 respuestas HTTP 500 en la suite de casos negativos.
- Todas las dependencias de borrado devuelven 409 o aplican soft delete.
- 100 % de los endpoints con validación de esquema y errores JSON.
- Facturas pagadas inmutables y con auditoría.
- Tokens invalidados al cambiar contraseña/correo/eliminar usuario.
- Rate limiting activo y probado.
- Suite de integración contra PostgreSQL real en CI.
- N+1 eliminado en endpoints críticos; consultas por debajo de un umbral acordado (por ejemplo, < 15 por request).
- Paginación en todos los listados.
- Cabeceras de seguridad y CSP configuradas.
- Pruebas de carga con p95 aceptable y sin agotamiento de pool.
- Backups y restauración probados.

---

## 10. Anexo: evidencia y reproducción

### 10.1 Comandos ejecutados

```powershell
# Suite oficial
python -m unittest discover -s tests -v
# Resultado: Ran 5 tests ... OK

# Suite adversaria (scripts de auditoría en %TEMP%\opencode)
python qa_audit.py
python qa_extra.py
python qa_perf.py
python qa_orphan.py
python qa_invoice.py
python qa_squat.py
```

### 10.2 Ejemplos de respuestas observadas

```text
POST /motos  {"marca":"X","modelo":"Y"}
→ 500 Internal Server Error (KeyError: 'placa')

POST /clientes {"nombre":null,"email":"x@test"}
→ 500 Internal Server Error (AttributeError: 'NoneType' object has no attribute 'strip')

POST /clientes {"nombre":"Dup","email":"cliente-b@qa.test"}
→ 500 Internal Server Error (UNIQUE constraint failed: clientes.taller_id, clientes.email)

POST /citas {"moto_id":1,"fecha":"2020-01-01"}
→ 201 {"mensaje":"Cita agendada con exito"}

DELETE /motos/1  (con citas)
→ 500 Internal Server Error (NOT NULL constraint failed: citas.moto_id)

DELETE /motos/1  (solo con diagnóstico)
→ 200 {"mensaje":"Moto eliminada con exito"}
   diagnóstico posterior: moto_id=None; /prioridades = []

DELETE /inventario/1 (usado en orden)
→ 200 {"mensaje":"Ítem eliminado del inventario."}
   GET /ordenes-servicio → 500 (AttributeError: 'NoneType' object has no attribute 'id')
   GET /panel-taller → 500

PUT /ordenes-servicio/1/estado {"estado":"recibida"}
→ 200 (desde "entregada"; sin validación de transición)

PUT /mi-cuenta {"password":"nueva-clave-123"}
→ 200 (sin contraseña actual)
   token anterior → 200 en /mi-cuenta

POST /facturas {"subtotal":"NaN", ...}
→ 500 Internal Server Error (decimal.InvalidOperation)

POST /facturas {"subtotal":"Infinity", ...}
→ 500 Internal Server Error (decimal.InvalidOperation)

POST /facturas {"subtotal":"100", "iva":"19"}
→ 201 {"total":"119.00"}  ✔
```

### 10.3 Medición de consultas

```text
QUERIES /motos/detalle: 92 (HTTP 200)      # 30 motos
QUERIES /motos: 32
QUERIES /clientes/detalle: 112 (HTTP 200)  # 50 clientes
QUERIES /diagnosticos: 32
QUERIES /prioridades: 32
QUERIES /panel-taller: 21
QUERIES /ordenes-servicio: 92
QUERIES /inventario: 2
```

### 10.4 Conclusión

MotoSmart tiene una base funcional sólida y un aislamiento multi-taller correcto, pero la ausencia de validación, los borrados sin integridad referencial, la falta de controles de facturación y auditoría, y las debilidades de sesión/rate limiting impiden considerarlo listo para producción. Las correcciones críticas y altas son acotadas y pueden abordarse en un ciclo de endurecimiento de 2–4 semanas, seguidas de pruebas de integración contra PostgreSQL y una suite negativa automatizada.

---

**Fin del informe original.**

---

## Anexo: cierre de pendientes de producción robusta (2026-11-17)

Se implementaron los seis pendientes que quedaban abiertos:

| Pendiente | Implementación | Evidencia |
| --- | --- | --- |
| Token en `localStorage` | Cookie `HttpOnly`, `SameSite=Strict`, CSRF de doble envío y `/sesion`; el JS ya no lee ni escribe el token | `tests/test_produccion.py::SesionCookieTests` |
| Rate limiting en memoria | Backend Redis con ventana deslizante atómica (Lua) y degradación controlada a memoria; `/health` reporta el backend | `tests/test_produccion.py::RateLimitTests` |
| Sin Alembic ni CI PostgreSQL | `alembic.ini`, `migrations/`, revisión inicial + cola OCR, workflow con PostgreSQL 16 y `alembic check` | `tests/test_produccion.py::MigracionesTests` y `.github/workflows/ci.yml` |
| OCR síncrono | Cola persistente `trabajos_ocr`, worker `flask --app app procesar-ocr`, reintentos, timeout y recuperación de trabajos atascados | `tests/test_produccion.py::ColaOCRTests` |
| Sin retención/exportación/borrado | `GET /mi-cuenta/exportar`, `DELETE /mi-cuenta`, CLI `exportar-usuario`, `anonimizar-usuario`, `aplicar-retencion`; facturas/órdenes se conservan sin datos de contacto | `tests/test_produccion.py::PrivacidadTests` y `RetencionTests` |
| Servidor de desarrollo y backups | `wsgi.py`, `gunicorn.conf.py`, `waitress_server.py`, servicios systemd, Nginx de ejemplo y scripts de backup/restauración con verificación real | `scripts/backup_postgres.*`, `scripts/verify_backup.*` |

Comando de validación ejecutado:

```text
python -m unittest discover -s tests -v
Ran 29 tests ... OK
```

Los pendientes que permanecen son operativos y dependen del proveedor: pruebas de carga, almacenamiento externo/cifrado de backups, monitoreo y rotación de secretos.

