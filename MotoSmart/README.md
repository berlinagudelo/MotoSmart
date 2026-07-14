# MotoSmart - Sistema de Gestión de Diagnósticos para Motocicletas

MotoSmart es una aplicación web diseñada para modernizar y agilizar el proceso de diagnóstico en talleres de motocicletas. Permite a los mecánicos digitalizar los resultados de los escáneres OBD mediante OCR, priorizar automáticamente las reparaciones y gestionar la información de los clientes y sus vehículos.

## 🎯 Objetivo del Proyecto

El objetivo principal de MotoSmart es ofrecer una herramienta centralizada que optimice el flujo de trabajo en un taller mecánico. Esto se logra a través de:

- **Digitalización Rápida:** Convertir imágenes de escáneres de diagnóstico en datos digitales accionables usando reconocimiento óptico de caracteres (OCR).
- **Priorización Inteligente:** Un motor de reglas evalúa la criticidad de los códigos de error para ayudar a los mecánicos a atender los problemas más urgentes primero.
- **Gestión Centralizada:** Administrar un registro de motocicletas, clientes, y el historial de diagnósticos de cada vehículo.
- **Comunicación con el Cliente:** Ofrecer a los clientes una vista clara y accesible de los diagnósticos de sus motocicletas.

## ✨ Características Principales

- **Roles de Usuario:** Sistema con tres roles: Mecánico, Cliente y Administrador.
- **Escáner OCR:** Sube una foto del resultado de un escáner OBD y la aplicación extraerá los códigos de error automáticamente.
- **Motor de Priorización:** Clasifica los diagnósticos en niveles (Crítica, Alta, Media, Baja) y provee recomendaciones.
- **Gestión de Motos y Clientes:** CRUD completo para registrar y administrar la información de vehículos y sus dueños.
- **Gestión de Citas:** Permite a los clientes solicitar citas y a los mecánicos gestionarlas.
- **Dashboard Intuitivo:** Interfaces de usuario claras y adaptadas a cada rol para una fácil navegación y gestión.

## 🛠️ Requisitos de Instalación

Para ejecutar este proyecto en tu máquina local, necesitarás tener instalado lo siguiente:

1.  **Python:** Versión 3.10 o superior.
2.  **PostgreSQL:** Un servidor de base de datos PostgreSQL en ejecución.
3.  **Git:** Para clonar el repositorio (opcional, si ya lo descargaste).

## 🚀 Guía de Puesta en Marcha

Sigue estos pasos para configurar y ejecutar el proyecto localmente.

### 1. Clonar el Repositorio

Abre una terminal y clona el proyecto (o navega a la carpeta si ya lo descargaste).

```bash
git clone <URL_DEL_REPOSITORIO>
cd MotoSmart
```

### 2. Configuración de la Base de Datos

Asegúrate de que tu servidor de PostgreSQL esté activo. Luego, crea una base de datos para el proyecto.

```sql
-- Puedes usar un cliente de base de datos como DBeaver, pgAdmin o el comando psql.
CREATE DATABASE "MotoSmart";
```

La aplicación está configurada para conectarse con el usuario `postgres` y la contraseña `123` a la base de datos `MotoSmart` en `localhost:5432`. Si tu configuración es diferente, actualiza la cadena de conexión en el archivo `db.py`:

```python
# C:\Users\berli\Downloads\MotoSmart\MotoSmart\db.py
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://TU_USUARIO:TU_CONTRASENA@localhost:5432/MotoSmart'
```

### 3. Configuración del Entorno de Python

Es una buena práctica usar un entorno virtual para aislar las dependencias del proyecto.

```bash
# Crea un entorno virtual
python -m venv .venv

# Actívalo (en Windows)
.venv\Scripts\activate

# Instala las dependencias necesarias
pip install Flask Flask-SQLAlchemy Flask-JWT-Extended psycopg2-binary easyocr
```

### 4. Ejecutar la Aplicación

Una vez configurado todo, puedes iniciar el servidor. El script creará automáticamente las tablas en la base de datos la primera vez que se ejecute.

```bash
python run_server.py
```

¡Listo! Abre tu navegador y visita `http://127.0.0.1:5000` para ver la aplicación en funcionamiento.