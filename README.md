# Support IT Management Platform

Proyecto de portafolio basado en una aplicación web interna para centralizar procesos de soporte e infraestructura de TI.

> **Aviso:** esta edición pública utiliza nombres, configuraciones y datos demostrativos. No contiene credenciales, bases de datos, información operativa ni identificadores reales de la organización para la que se diseñó el sistema.

## Autora

**Jazmin Lopez Zamora**

## Objetivo

Centralizar en una sola aplicación web tareas que normalmente terminan dispersas entre hojas de cálculo, exportaciones y archivos independientes: análisis de tickets, inventario, asignaciones, responsivas, usuarios y configuración operativa.

## Funcionalidades destacadas

- Dashboard de soporte con métricas, filtros y comparativas por periodo.
- Importación y análisis de tickets de Helpdesk.
- Seguimiento de inventario y asignaciones de equipo.
- Generación y consulta de responsivas.
- Perfiles de acceso: usuario, administrador y superadministrador.
- Autenticación, sesiones y auditoría de acciones relevantes.
- Calendario laboral y cálculo de tiempos considerando días no laborables.
- Persistencia compatible con SQLite para demostración y PostgreSQL para una instalación centralizada.
- Capas de integración preparadas para Odoo y Google Workspace mediante variables de entorno.

## Arquitectura

```text
Navegador
   |
   v
Servidor Python (app.py)
   |
   +-- Autenticación y permisos
   +-- Dashboard / API
   +-- Inventario y responsivas
   +-- Calendario laboral
   +-- Conectores externos (configuración demo)
   |
   +-- SQLite / PostgreSQL
```

## Estructura principal

```text
app.py                       Servidor y API
 auth.py                     Usuarios, sesiones y contraseñas
 database.py                 Acceso a SQLite/PostgreSQL
 holiday_service.py          Calendario y feriados
 odoo_connector.py           Capa de integración demostrativa
 google_calendar_connector.py
 google_drive_connector.py
 static/                     Interfaz web
 schema.sql                  Esquema SQLite
 schema_postgresql.sql       Esquema PostgreSQL
 .env.example                Plantilla sin secretos
```

## Ejecutar la demo localmente

### Opción sencilla: SQLite

1. Instala Python 3.
2. Clona o descarga este repositorio.
3. No es necesario crear `.env` para la configuración básica de demostración.
4. Ejecuta en Windows:

```bash
py app.py
```

5. Abre en el navegador:

```text
http://localhost:8000
```

La aplicación puede crear una base SQLite local dentro de `data/`. Esa carpeta está excluida de Git para evitar publicar datos generados durante las pruebas.

## Configuración opcional

Para probar PostgreSQL o los conectores externos, copia `.env.example` como `.env` y utiliza únicamente credenciales de prueba propias.

```bash
cp .env.example .env
```

En Windows también puedes copiar el archivo desde el Explorador y renombrarlo a `.env`.

**Nunca publiques `.env`, bases de datos, service accounts, API keys o archivos de usuarios.**

## Seguridad implementada

- Contraseñas almacenadas mediante PBKDF2 y salt individual.
- Sesiones persistidas mediante hashes de tokens.
- Cookies de sesión con controles de seguridad.
- Permisos comprobados desde el servidor.
- Bloqueo temporal ante intentos fallidos repetidos.
- Auditoría de acciones relevantes sin almacenar contraseñas.

## Privacidad de esta versión

Este repositorio fue preparado específicamente para portafolio. Se eliminaron datos de producción, documentación interna, base de datos local, nombres de colaboradores y referencias operativas de la organización. Las configuraciones de Odoo y Google Workspace son ejemplos y requieren credenciales propias para funcionar.

## Alcance

Este proyecto demuestra diseño de aplicaciones internas, automatización de procesos, modelado de datos, control de acceso, análisis de información y preparación de integraciones. No representa una distribución oficial del sistema utilizado por ninguna organización.
