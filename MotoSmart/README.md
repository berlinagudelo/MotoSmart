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
| Administrador | Vista administrativa de la información de la plataforma. |

La sección **Mis motos** incluye una ficha por vehículo que resume su último diagnóstico: nivel de atención, fecha de revisión, resultado y recomendación. Si la moto aún no tiene revisión, se propone agendar el servicio.

## Tecnologías

- Python y Flask
- SQLAlchemy y PostgreSQL
- Flask-JWT-Extended
- EasyOCR
- HTML, CSS y JavaScript sin framework
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
   pip install Flask Flask-SQLAlchemy Flask-JWT-Extended psycopg2-binary easyocr
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

Para ejecutar las pruebas de aislamiento en una base SQLite temporal:

```powershell
python -m unittest discover -s tests -v
```

## Ejecutable de Windows

El proyecto incluye `build_exe.bat` para generar una versión distribuible con PyInstaller.

```bat
build_exe.bat
```

El ejecutable se genera en `dist\MotoSmart\MotoSmart.exe`. Antes de compilar, verifica que el entorno virtual tenga todas las dependencias instaladas.

## Estructura relevante

```text
MotoSmart/
├── app.py                 # Configuración de Flask y rutas
├── db.py                  # Configuración de SQLAlchemy/PostgreSQL
├── modelo/                # Talleres y entidades de base de datos
├── router/                # Endpoints y lógica de cada módulo
├── services/              # Priorización de diagnósticos
├── static/                # Estilos y JavaScript del cliente
├── templates/index.html   # Interfaz principal
└── run_server.py          # Lanzador local
```

## Notas de seguridad

- Para conservar sesiones entre reinicios y en despliegues, configura una clave JWT privada, persistente y distinta por entorno. En modo local se genera automáticamente una clave temporal si no se define.
- Las cuentas nuevas se crean inmediatamente después de elegir un taller. Se verifica el correo antes de vincular datos preexistentes, cambiar una dirección o transferir motos a otro taller.
- Los cambios de correo también requieren confirmar el enlace enviado a la nueva dirección; el historial del cliente se conserva al aplicar el cambio.
- El registro de taller crea una cuenta de titular asociada al nuevo espacio. Los clientes y el personal quedan limitados a la información de su taller.
- El comando `reiniciar-base-talleres --confirmar` es destructivo; no lo ejecutes sobre una base con información que quieras conservar.
- Mantén las credenciales de PostgreSQL fuera del repositorio.
- Usa HTTPS, variables de entorno y un servidor de producción para publicar la aplicación.

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
