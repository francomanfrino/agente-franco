# ContabilidadAR — Gestión Contable para PyMEs Argentinas

App de escritorio 100% local para conciliación bancaria, cuentas por cobrar/pagar y alertas de vencimientos.

## Stack

- Python 3.11+, PyQt6, SQLite, pandas, rapidfuzz, reportlab

## Instalación

```bash
cd contabilidad_pyme
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Primer uso

```bash
# Cargar datos ficticios de ejemplo
python data/seed_data.py

# Iniciar la app
python main.py
```

## Estructura

```
contabilidad_pyme/
├── main.py                  # Entry point
├── database/
│   ├── db.py                # Conexión SQLite (WAL mode)
│   ├── models.py            # Schema + CREATE statements
│   └── repositorios.py      # CRUD layer
├── core/
│   ├── conciliacion.py      # Algoritmo de matching (5 pasadas)
│   ├── importador.py        # Parseo de Excel/CSV con mapeo flexible
│   └── alertas.py           # Lógica de vencimientos, gaps, anomalías
├── ui/
│   ├── main_window.py       # Ventana principal + sidebar alertas
│   ├── dashboard.py         # KPI cards superiores
│   ├── tab_conciliacion.py  # Pestaña de conciliación automática
│   ├── tab_cxc.py           # Cuentas por cobrar con semáforo
│   ├── tab_cxp.py           # Cuentas por pagar
│   └── wizard_upload.py     # Wizard paso a paso para subir archivos
├── services/
│   ├── exportador.py        # Export a Excel y PDF (ReportLab)
│   └── backup.py            # ZIP cifrado semanal
├── tests/
│   └── test_conciliacion.py # Tests del algoritmo de conciliación
└── data/
    └── seed_data.py         # Datos ficticios para testing
```

## Ejecutar tests

```bash
python -m pytest tests/ -v
```

## Generar ejecutable .exe

```bash
pyinstaller build.spec
# El ejecutable queda en dist/ContabilidadAR.exe
```

## Algoritmo de conciliación (5 pasadas)

1. **Exacto**: importe exacto + fecha dentro de ±5 días del vencimiento
2. **CUIT**: importe exacto + CUIT del cliente en la descripción del movimiento
3. **Fuzzy**: importe exacto + nombre con similitud ≥85% (rapidfuzz)
4. **Parcial**: suma de N movimientos = total factura (hasta 4 movimientos)
5. **Neto**: movimiento hasta 35% menor que factura (retenciones) → probable

Los matches de baja confianza se marcan como "probable" para revisión del contador.

## Base de datos

La base SQLite se guarda en `~/.contabilidad_pyme/contabilidad.db`.
Los backups se generan en `~/.contabilidad_pyme/backups/`.

Para cambiar la ubicación:
```bash
set CONTAB_DB_PATH=D:\datos\mi_empresa.db
python main.py
```

## Columnas soportadas por banco

El wizard de importación detecta automáticamente columnas de:
Santander, Galicia, BBVA, Macro, Nación, ICBC y cualquier exportación de AFIP/ARCA.
Si no detecta alguna columna, muestra un selector para mapearla manualmente.
