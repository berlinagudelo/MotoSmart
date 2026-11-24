# MotoSmart

MotoSmart es una aplicación web para administrar el servicio de motocicletas en un taller. Centraliza motos, citas, diagnósticos, inventario y facturación en una experiencia adaptada para clientes y mecánicos.

## Qué permite hacer

- Registrar cuentas de cliente y mecánico con acceso protegido mediante JWT.
- Registrar motos electrónicas y no electrónicas.
- Subir una imagen de un escáner para extraer códigos mediante OCR y guardar el diagnóstico.
- Registrar revisiones mecánicas manuales para motos no electrónicas.
- Priorizar diagnósticos por criticidad y sugerir una recomendación de servicio.
- Consultar resultados, historial y fichas visuales de estado por moto.
- Solicitar, editar y administrar citas de taller.
- Controlar inventario, alertas de stock y proveedores.
- Crear facturas y descargar el comprobante en PDF.

## Experiencia por rol

| Rol | Acceso principal |
| --- | --- |
| Cliente | Sus motos, ficha de estado, resultados de servicio, citas y facturas. |
| Mecánico | Registro de motos, OCR, revisión manual, prioridades, citas, inventario y facturación. |
| Administrador | Gestión completa del taller asignado: inventario, facturación y consulta de la información. Se crea con el comando `crear-admin`. |

La sección **Mis motos** incluye una ficha por vehículo que resume su último diagnóstico: nivel de atención, fecha de revisión, resultado y recomendación. Si la moto aún no tiene revisión, se propone agendar el servicio.

## Tecnologías

- Python y Flask
- SQLAlchemy, PostgreSQL y migraciones Alembic
- Flask-JWT-Extended con cookie HttpOnly y CSRF
- Redis opcional para rate limiting compartido
- EasyOCR con cola persistente
- HTML, CSS y JavaScript sin framework
- Gunicorn/Waitress para producción
- PyInstaller para la versión de escritorio de Windows

## Requisitos

- Python 3.10 o posterior
- PostgreSQL 14 o posterior
- `pip`

## Instalación local

1. Clona el repositorio o abre la carpeta del proyecto.

   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd MotoSmart
   ```

2. Crea y activa un entorno virtual.

   En Windows (PowerShell):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Instala las dependencias.

   ```bash
   pip install -r requirements.txt
   pip install -r requirements-ocr.txt   # solo en el equipo que procesa imágenes
   ```

4. Crea una base de datos en PostgreSQL.

   ```sql
   CREATE DATABASE "MotoSmart";
   ```

5. Configura PostgreSQL y guarda su cadena de conexión solo en `MOTOSMART_DATABASE_URL` dentro de tu archivo local `correo.configuracion.ps1`. No escribas credenciales de base de datos en `db.py` ni las publiques. Usa el formato de conexión SQLAlchemy de PostgreSQL compatible con `psycopg2`; la aplicación no inicia si falta esta variable.
6. Configura el correo y, opcionalmente, una clave JWT persistente. Si no defines `MOTOSMART_JWT_SECRET_KEY`, MotoSmart genera una clave temporal segura automáticamente para que puedas iniciar sin configurarla manualmente. Los tokens existentes dejarán de funcionar cuando se reinicie la aplicación. Para conservar las sesiones entre reinicios o desplegar en un servidor, genera una clave aleatoria de al menos 32 caracteres:

   ```powershell
   $bytes = New-Object byte[] 48
   $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
   $rng.GetBytes($bytes)
   [Convert]::ToBase64String($bytes)
   $rng.Dispose()
   ```

   Si decides usarla, guarda el resultado como `MOTOSMART_JWT_SECRET_KEY` en tu archivo local `correo.configuracion.ps1` (copia `correo.configuracion.ps1.example`) y consérvala entre ejecuciones. Configura `MOTOSMART_DATABASE_URL` con la conexión privada a PostgreSQL y las variables SMTP descritas en **Notificaciones por correo**. SMTP se necesita para reclamar datos previos, cambiar el correo o confirmar una mudanza de taller. En un despliegue remoto, establece `MOTOSMART_PUBLIC_URL` con la URL pública HTTPS de la aplicación. Para usar los comandos desde PowerShell, carga la configuración en esa misma ventana con `. .\correo.configuracion.ps1`.

7. Si la base contiene el esquema anterior a los talleres, reiníciala una sola vez desde la carpeta `MotoSmart`:

   ```powershell
   . .\correo.configuracion.ps1
   python -m flask --app app reiniciar-base-talleres --confirmar
   ```

   **Este comando elimina todas las tablas y todos sus datos.** Úsalo únicamente si confirmas que la base seleccionada puede vaciarse. Una base nueva crea el esquema automáticamente al iniciar, por lo que no requiere este comando.

   Para crear una cuenta administradora dentro de un taller existente:

   ```powershell
   flask --app app crear-admin --email admin@taller.com --taller-id 1
   ```

   El comando solicita la contraseña de forma interactiva (mínimo 8 caracteres, con letras y números) y deja el cambio registrado en la auditoría.

8. Inicia la aplicación. En PowerShell, carga la configuración con `. .\correo.configuracion.ps1`; `iniciar_motosmart.bat` la carga automáticamente y no exige una clave JWT.

   ```bash
   python run_server.py
   ```

   También puedes ejecutar `python app.py` durante el desarrollo. La primera ejecución crea las tablas necesarias y agrega la columna de tecnología de las motos cuando hace falta.

9. Abre `http://127.0.0.1:5000` en el navegador. `run_server.py` intenta abrirla automáticamente.

## Flujo de uso recomendado

1. Desde la portada, el titular puede registrar un taller con nombre, ciudad y teléfono. La cuenta que lo crea queda como titular y puede agregar mecánicos desde **Mi equipo**.
2. Los clientes crean su cuenta y eligen a qué taller pertenecer. Si su correo ya tiene datos previos en ese taller, deben verificarlo por correo para reclamarlos.
3. Registra una moto y define si es electrónica o no electrónica.
4. Para motos electrónicas, procesa una foto del escáner OCR. Para motos no electrónicas, registra la revisión manual.
5. Consulta la prioridad, el diagnóstico y la recomendación resultante.
6. Los clientes pueden solicitar citas, revisar servicios y cambiar de taller desde los ajustes de su cuenta. La mudanza se confirma por correo: crea una copia de cada moto y pasa sus tres diagnósticos más recientes al taller nuevo. Las citas, órdenes, facturas y el historial completo quedan en el taller de origen.

Cada taller tiene sus propias cuentas de personal, clientes, motos, diagnósticos, citas, facturación e inventario. Las rutas de la API aplican el taller de la cuenta autenticada; no se acepta elegir otro taller enviando un identificador desde el navegador.

Para ejecutar la suite de pruebas de aislamiento, validación, seguridad y regresión en una base SQLite temporal:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas cubren, entre otros: rechazo de datos vacíos o con tipos incorrectos, errores JSON consistentes (400/401/403/404/405/409/413/415), borrados con dependencias, facturas pagadas inmutables, cambio de contraseña con revocación de sesiones, recuperación de contraseña por correo, idempotencia, cantidades enteras, límites de subida, paginación, cookies HttpOnly/CSRF, cola OCR, retención y exportación/anonimización de datos. La suite se ejecuta en SQLite; el flujo de CI incluido en `.github/workflows/ci.yml` la repite contra PostgreSQL 16 y valida las migraciones Alembic.

## Ejecutable de Windows

El proyecto incluye `build_exe.bat` para generar una versión distribuible con PyInstaller.

```bat
build_exe.bat
```

El ejecutable se genera en `dist\MotoSmart\MotoSmart.exe`. Antes de compilar, verifica que el entorno virtual tenga todas las dependencias instaladas.

## Estructura relevante

```text
MotoSmart/
├── app.py                 # Configuración de Flask, CLI, cabeceras y errores
├── wsgi.py                # Entrada WSGI de producción
├── db.py                  # Configuración de SQLAlchemy/PostgreSQL
├── alembic.ini            # Migraciones versionadas
├── migrations/            # Revisiones Alembic
├── modelo/                # Talleres, entidades y cola OCR
├── router/                # Endpoints y lógica de cada módulo
├── services/              # Priorización, seguridad, OCR, privacidad, validación
├── static/                # Estilos y JavaScript del cliente
├── templates/index.html   # Interfaz principal
├── tests/                 # Pruebas de aislamiento, regresión y producción
├── scripts/               # Backup, restauración y verificación
├── deploy/                # Ejemplos systemd y Nginx
└── run_server.py          # Lanzador local de escritorio
```

## Notas de seguridad

- Para conservar sesiones entre reinicios y en despliegues, configura una clave JWT privada, persistente y distinta por entorno. En modo local se genera automáticamente una clave temporal si no se define.
- Las cuentas nuevas se crean inmediatamente después de elegir un taller. Se verifica el correo antes de vincular datos preexistentes, cambiar una dirección o transferir motos a otro taller. En producción, los registros nuevos, las invitaciones de mecánicos y la creación de talleres exigen verificar el correo (`MOTOSMART_REQUIRE_EMAIL_VERIFICATION`).
- Las contraseñas deben tener al menos 8 caracteres e incluir letras y números. Cambiarlas exige la contraseña actual y revoca todas las sesiones anteriores.
- La recuperación de contraseña se solicita desde el inicio de sesión. El enlace llega por correo, es de un solo uso y también revoca las sesiones abiertas.
- Los inicios de sesión, registros y recuperaciones tienen límite de intentos. Con `MOTOSMART_REDIS_URL` el límite es compartido entre procesos; sin Redis queda por proceso y `/health` lo indica.
- Las operaciones sensibles (facturación, inventario, equipo, cuenta y estados de orden) quedan en la tabla `auditoria`.
- Las facturas pagadas y las órdenes entregadas no se pueden editar ni borrar; los borrados con dependencias responden `409` y no dejan registros huérfanos.
- El comando `reiniciar-base-talleres --confirmar` es destructivo; no lo ejecutes sobre una base con información que quieras conservar.
- Mantén las credenciales de PostgreSQL fuera del repositorio.
- Usa HTTPS, variables de entorno y un servidor de producción para publicar la aplicación. En producción la aplicación exige HTTPS y una clave JWT persistente.
- Revisa `correo.configuracion.ps1.example` para las variables de entorno disponibles (pool de conexiones, límite de subida, notificaciones asíncronas y proxy).
- Las tipografías se sirven localmente desde `static/fonts` con licencia OFL, sin depender de Google Fonts ni de recursos externos.
- La sesión del navegador se guarda en una cookie `HttpOnly` con `SameSite=Strict` y protección CSRF; el token ya no se escribe en `localStorage`. La cabecera `Authorization: Bearer` se mantiene para integraciones.
- El rate limiting usa Redis cuando `MOTOSMART_REDIS_URL` está definido, de modo que el límite es compartido entre workers e instancias. Si Redis no está disponible, se degrada a memoria y `/health` lo reporta.
- Las imágenes del escáner se guardan fuera de `static/` y se procesan en una cola persistente. Un reinicio no pierde trabajos pendientes.
- La exportación y la anonimización de datos personales están disponibles en **Ajustes de cuenta** y por CLI. Las facturas/órdenes se conservan sin datos de contacto por obligación contable. Al anonimizar una cuenta de cliente también se eliminan sus imágenes OCR; la anonimización del personal del taller se limita a su propio taller salvo que se indique `--taller-id`.
- Ejecuta `flask --app app aplicar-retencion` periódicamente para eliminar tokens vencidos, trabajos OCR terminados (con sus imágenes) y auditoría antigua. El borrado se hace por lotes de `MOTOSMART_RETENCION_LOTE` (5000 por defecto) y se confirma cada lote para no mantener transacciones largas.

## Paginación y rendimiento

- Los listados aceptan `?page=1&per_page=50`. `per_page` se limita a **200**. Sin parámetros devuelven un arreglo de hasta 500 elementos para mantener la compatibilidad con la interfaz actual.
- `?total=0` omite el `COUNT(*)` y devuelve `total` y `pages` en `null`. Úsalo en tablas grandes cuando solo se necesita la página.
- `/motos` y `/motos/detalle` resuelven la última orden de cada moto con `ROW_NUMBER()` en una sola consulta por página; ya no cargan el historial completo de órdenes.
- `/prioridades` devuelve un único diagnóstico por moto, excluye motos transferidas y usa el índice `(taller_id, moto_id, fecha, id)`.
- `/clientes/detalle` carga solo las citas de hoy en adelante.
- Índices añadidos: clientes por taller/nombre, órdenes por taller/actualización, diagnósticos por taller/moto/fecha, vencimiento de registros pendientes y estado/actualización de OCR. Se eliminaron índices de una columna cubiertos por índices compuestos o restricciones únicas.
- Límites conocidos: `/prioridades` sigue devolviendo una fila por moto y los listados sin paginación tienen un tope de 500. Para volúmenes de decenas de millones de filas conviene paginar siempre, archivar auditoría/OCR y evaluar particionado por taller o fecha.

## Despliegue en producción

1. Configura `MOTOSMART_ENV=production`, `MOTOSMART_DATABASE_URL`, `MOTOSMART_JWT_SECRET_KEY` (≥ 32 caracteres) y `MOTOSMART_PUBLIC_URL` con HTTPS. La aplicación se niega a arrancar si falta la clave o la URL no es HTTPS.
2. Aplica las migraciones versionadas. En una base existente creada por la versión anterior (sin tabla `alembic_version`), marca la línea base y aplica la migración de la cola OCR:

   ```bash
   alembic stamp 7951685dc9ae  # solo si el esquema previo ya existe
   alembic upgrade head        # crea trabajos_ocr y aplica cambios futuros
   ```

   En instalaciones nuevas basta `alembic upgrade head`. No uses `reiniciar-base-talleres` sobre datos reales.
3. Arranca WSGI, nunca `flask run`:
   - Linux: `gunicorn -c gunicorn.conf.py wsgi:application`
   - Windows: `waitress-serve --listen=127.0.0.1:8000 wsgi:application`
   - El servicio de ejemplo está en `deploy/motosmart.service`.
4. Ejecuta el worker de OCR como proceso aparte (`deploy/motosmart-ocr.service`):

   ```bash
   flask --app app procesar-ocr
   ```

   En desarrollo/escritorio se puede usar `MOTOSMART_OCR_INLINE_WORKER=true`. En producción déjalo en `false`.
5. Configura Redis para rate limiting compartido:

   ```bash
   MOTOSMART_REDIS_URL=redis://127.0.0.1:6379/0
   ```

6. Publica detrás de un proxy TLS. El ejemplo de Nginx está en `deploy/nginx.conf.example`; activa `MOTOSMART_TRUST_PROXY=true` solo si el proxy reescribe `X-Forwarded-*`.
7. Programa backups y una prueba de restauración real:

   ```powershell
   .\scripts\backup_postgres.ps1 -Database MotoSmart -User motorsmart -RetentionDays 30
   .\scripts\verify_backup.ps1 -Backup .\backups\motorsmart-MotoSmart-AAAAMMDD-HHMMSS.dump
   ```

   En Linux: `PGDATABASE=MotoSmart PGUSER=motorsmart ./scripts/backup_postgres.sh` y `./scripts/verify_backup.sh backup.dump`. La verificación crea una base temporal, restaura el dump, consulta `talleres` y elimina la base temporal. Incluye también `MOTOSMART_OCR_DIR` en el mismo plan de backup: el dump solo cubre PostgreSQL y las imágenes pendientes viven en disco.
8. Programa `flask --app app aplicar-retencion` (por ejemplo, semanal) y revisa `/health`, que reporta base de datos y backend de límites.
9. Rota la clave JWT solo con una ventana de mantenimiento: al cambiarla se invalidan todas las sesiones.

## Notificaciones por correo

Cuando un mecánico cambia el estado de una orden, MotoSmart puede avisar automáticamente al correo del cliente. Configura estas variables de entorno antes de iniciar la aplicación; no se guardan credenciales en el proyecto.

```powershell
$env:SMTP_HOST = 'smtp.gmail.com'
$env:SMTP_PORT = '587'
$env:SMTP_TLS = 'true'
$env:SMTP_USER = 'tu_correo@gmail.com'
$env:SMTP_PASSWORD = 'TU_CLAVE_DE_APLICACION'
$env:SMTP_FROM = 'MotoSmart <tu_correo@gmail.com>'
```

### Configuración recomendada

Para no escribir secretos en el README ni en el código, usa la plantilla incluida:

```powershell
Copy-Item correo.configuracion.ps1.example correo.configuracion.ps1
# Edita correo.configuracion.ps1 únicamente en tu equipo.
.\correo.configuracion.ps1
python run_server.py
```

El archivo `correo.configuracion.ps1` está excluido de Git. Si la clave se compartió o escribió en algún archivo, revócala en Google y genera una nueva antes de usarla.

Con Gmail se debe usar una contraseña de aplicación, no la contraseña normal de la cuenta. Si estas variables no se configuran, el cambio de estado seguirá funcionando y no se enviará ningún correo.
