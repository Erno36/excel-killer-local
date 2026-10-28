# Cruzador Excel — Banco Piano

Herramienta de escritorio para la coordinadora de productos de la Gerencia Comercial de Consumo (GCC).
Automatiza el cruce manual de columnas entre multiples archivos Excel.

## Decision de stack

**GUI: PySide6 (Qt6)**
Se eligio PySide6 sobre Tkinter por:
- `QAbstractTableModel` permite scroll virtual para hasta 100.000 filas sin degradar la UI.
- `QThread` evita congelamiento de la UI durante el cruce.
- Aspecto nativo en Windows 10/11 con QStyle Fusion.
- Extensibilidad hacia futuras funciones (analisis, exportacion a CSV/PDF) sin reescribir.
- Licencia LGPL v3 — libre para uso interno.

**Motor: pandas + openpyxl/xlrd**
El cruce se realiza en memoria con `pandas.merge()`. No se carga nada en SQLite
(menor riesgo de datos sensibles en archivos temporales en disco).

**Base de datos: SQLite**
Solo para usuarios y log de intentos de login. Migraciones escritas
para facilitar migration futura a PostgreSQL sin reescribir logica.

**Auditoria: JSONL propio**
Handler separado del `logging` estandar de Python para garantizar
inmutabilidad del formato (RN-021) ante reconfiguraciones de librerias.

## Instalacion

```bash
# Crear entorno virtual
python -m venv .venv

# Activar (Linux/macOS)
source .venv/bin/activate
# Activar (Windows)
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

## Configuracion

```bash
cp .env.example .env
# Editar .env si se necesita cambiar DB_PATH, LOG_DIR, o APP_ENV
```

## Deteccion de encabezados Excel

El lector inspecciona las primeras 20 filas para sugerir la fila de encabezado.
La pantalla de carga permite conservar la deteccion automatica o elegir otra
fila para una hoja especifica. Al cargar todas las hojas, el lector detecta el
encabezado por separado en cada una. La sugerencia es heuristica: revisa los
nombres de columnas antes de ejecutar el cruce. No valida el significado de los
campos ni reemplaza la revision operativa.

## Generar datos sinteticos

```bash
python dev_data/generar_datos.py
```
Crea `dev_data/seguros.xlsx`, `dev_data/bajas.xlsx`, `dev_data/pagos_broker.xlsx`
con CUILes ficticios y datos inventados. Sin datos reales.

## Iniciar la aplicacion

```bash
python main.py
```

En modo development (APP_ENV=development), el usuario de prueba disponible es:
- Usuario: `dev`
- Contrasena: `dev1234`

## Crear ejecutable

El ejecutable incluye Python y las dependencias de la aplicacion. Se genera para
el sistema operativo donde se ejecuta el script; no es un binario universal.

```bash
# Instalar primero las dependencias de la aplicacion y del empaquetador.
python -m pip install -r requirements.txt -r requirements-build.txt

# Linux: genera ../../salidas/exes/CruzadorExcel-Linux
./build_linux.sh

# Windows: crea el instalador wizard ..\..\salidas\exes\CruzadorExcel-Setup.exe
build_windows.bat
```

La compilacion para Windows debe ejecutarse en Windows con Inno Setup 6
instalado (el comando `ISCC.exe` debe estar en `PATH`, o en su ruta de
instalacion habitual). El paquete crea un instalador wizard por usuario,
accesos directos y una opcion para abrir la aplicacion al finalizar. La base de
usuarios y los logs se guardan en `%LOCALAPPDATA%\BancoPiano\CruzadorExcel`;
se conservan al desinstalar.

El instalador es una demo y advierte que incluye `dev` / `dev1234`. Usar
exclusivamente con datos sinteticos, nunca con datos reales o de clientes.
La compilacion y validacion final del instalador requiere Windows; este
repositorio no incluye un instalador Windows ya generado.

## Administracion de usuarios

```bash
# Crear usuario de produccion
python scripts/create_user.py create <username> <password>

# Desactivar
python scripts/create_user.py deactivate <username>

# Resetear contrasena
python scripts/create_user.py reset <username> <new_password>
```

## Ejecutar tests

```bash
pytest tests/ -v
```

## Estructura

```
cruzador_excel/
├── main.py              # Punto de entrada
├── config.py            # Variables de entorno
├── ui/                  # Pantallas PySide6
├── engine/              # Motor de cruce (sin GUI — testeable)
├── auth/                # Autenticacion y sesion
├── data/                # SQLite y dataclasses
├── audit/               # Logger JSONL de auditoria
├── tests/               # Pruebas unitarias y de integracion
├── scripts/             # Administracion de usuarios por consola
└── dev_data/            # Generador de datos sinteticos
```

## Notas de cumplimiento

- Los logs NO contienen valores de celdas, CUILes, nombres ni importes (RN-019).
- Las contrasenas se almacenan con bcrypt factor >= 12 (RN-001).
- El usuario `dev` solo existe con APP_ENV=development (RN-003).
- Sin conexion a sistemas externos (RN-024, RT-08).
- VERIFICAR con Compliance antes de puesta en produccion (PC-01 a PC-04 del documento de requisitos).
