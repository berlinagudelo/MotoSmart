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
6. Configura los secretos y el correo. MotoSmart no inicia si falta una clave JWT aleatoria de al menos 32 caracteres. Genera una clave una sola vez:

   ```powershell
   $bytes = New-Object byte[] 48
   $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
   $rng.GetBytes($bytes)
   [Convert]::ToBase64String($bytes)
   $rng.Dispose()
   ```

   Guarda el resultado como `MOTOSMART_JWT_SECRET_KEY` en tu archivo local `correo.configuracion.ps1` (copia `correo.configuracion.ps1.example`). Conserva la misma clave entre ejecuciones; cambiarla invalida los tokens existentes. Configura también `MOTOSMART_DATABASE_URL` con la conexión privada a PostgreSQL y las variables SMTP descritas en **Notificaciones por correo**: SMTP es necesario para verificar nuevas cuentas. En un despliegue remoto, establece `MOTOSMART_PUBLIC_URL` con la URL pública HTTPS de la aplicación. Para usar los comandos desde PowerShell, carga la configuración en esa misma ventana con `. .\correo.configuracion.ps1`.

7. Crea el titular del taller desde una consola local, nunca desde el registro público:

   ```powershell
   flask --app app crear-titular-taller
   ```

   El comando solicita el correo y la contraseña, y solo permite crear el titular si todavía no existe uno. Los mecánicos adicionales se crean desde **Mi equipo**.

8. Inicia la aplicación. En PowerShell, primero carga la configuración con `. .\correo.configuracion.ps1`; `iniciar_motosmart.bat` la carga automáticamente.

   ```bash
   python run_server.py
   ```

   También puedes ejecutar `python app.py` durante el desarrollo. La primera ejecución crea las tablas necesarias y agrega la columna de tecnología de las motos cuando hace falta.

9. Abre `http://127.0.0.1:5000` en el navegador. `run_server.py` intenta abrirla automáticamente.

## Flujo de uso recomendado

1. Crea el titular del taller con el comando local anterior. Los clientes se registran con su correo y deben abrir el enlace de verificación que se les envía antes de elegir una contraseña.
2. Registra una moto y define si es electrónica o no electrónica.
3. Para motos electrónicas, procesa una foto del escáner OCR. Para motos no electrónicas, registra la revisión manual.
4. Consulta la prioridad, el diagnóstico y la recomendación resultante.
5. El cliente puede revisar la ficha de estado de su moto, solicitar una cita y consultar sus facturas.

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
├── modelo/                # Entidades de base de datos
├── router/                # Endpoints y lógica de cada módulo
├── services/              # Priorización de diagnósticos
├── static/                # Estilos y JavaScript del cliente
├── templates/index.html   # Interfaz principal
└── run_server.py          # Lanzador local
```

## Notas de seguridad

- Configura una clave JWT privada, persistente y distinta por entorno antes de iniciar la aplicación.
- Las nuevas cuentas de cliente solo se crean después de verificar el correo. Configura SMTP antes de habilitar el registro.
- Los cambios de correo también requieren confirmar el enlace enviado a la nueva dirección; el historial del cliente se conserva al aplicar el cambio.
- El registro público no permite crear titulares; utiliza `flask --app app crear-titular-taller` en la máquina que administra la base de datos.
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
