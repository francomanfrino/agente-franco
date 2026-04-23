"""
SQLite schema definitions.

Tables:
  empresa            — datos de la empresa (una sola fila)
  cuentas_bancarias  — cuentas propias
  clientes           — clientes con historial de plazo de pago
  proveedores        — proveedores recurrentes
  movimientos        — líneas de extracto bancario
  facturas_emitidas  — facturas a clientes
  facturas_recibidas — facturas de proveedores
  conciliaciones     — relación N:M movimiento ↔ factura
  cotizaciones_usd   — tipo de cambio por fecha
  auditoria          — log de acciones del contador
  config             — pares clave-valor de configuración
"""

CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS empresa (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        razon_social    TEXT NOT NULL,
        cuit            TEXT NOT NULL,
        email           TEXT,
        whatsapp        TEXT,
        domicilio       TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS cuentas_bancarias (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        banco           TEXT NOT NULL,
        tipo            TEXT NOT NULL CHECK (tipo IN ('CC','CA','USD')),
        moneda          TEXT NOT NULL DEFAULT 'ARS',
        nro_cuenta      TEXT,
        cbu             TEXT,
        alias           TEXT,
        activa          INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS clientes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cuit            TEXT UNIQUE NOT NULL,
        razon_social    TEXT NOT NULL,
        email           TEXT,
        telefono        TEXT,
        condicion_pago  INTEGER NOT NULL DEFAULT 30,
        dias_pago_real  REAL,
        activo          INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS proveedores (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cuit            TEXT UNIQUE NOT NULL,
        razon_social    TEXT NOT NULL,
        email           TEXT,
        es_recurrente   INTEGER NOT NULL DEFAULT 0,
        periodo_factura TEXT CHECK (periodo_factura IN ('mensual','bimestral','trimestral','anual',NULL)),
        activo          INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS movimientos (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cuenta_id       INTEGER NOT NULL REFERENCES cuentas_bancarias(id),
        fecha           TEXT NOT NULL,
        fecha_valor     TEXT,
        descripcion     TEXT NOT NULL,
        debito          REAL NOT NULL DEFAULT 0,
        credito         REAL NOT NULL DEFAULT 0,
        saldo           REAL,
        referencia      TEXT,
        moneda          TEXT NOT NULL DEFAULT 'ARS',
        es_transferencia_interna INTEGER NOT NULL DEFAULT 0,
        archivo_origen  TEXT,
        conciliado      INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS facturas_emitidas (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nro_factura     TEXT NOT NULL,
        punto_venta     TEXT NOT NULL DEFAULT '0001',
        tipo            TEXT NOT NULL CHECK (tipo IN ('A','B','C','E','M','X')),
        fecha_emision   TEXT NOT NULL,
        fecha_vencimiento TEXT,
        cliente_id      INTEGER REFERENCES clientes(id),
        cuit_cliente    TEXT NOT NULL,
        razon_social_cliente TEXT NOT NULL,
        neto            REAL NOT NULL DEFAULT 0,
        iva             REAL NOT NULL DEFAULT 0,
        percepciones    REAL NOT NULL DEFAULT 0,
        otros_impuestos REAL NOT NULL DEFAULT 0,
        total           REAL NOT NULL DEFAULT 0,
        moneda          TEXT NOT NULL DEFAULT 'ARS',
        condicion_pago  INTEGER NOT NULL DEFAULT 30,
        estado          TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','cobrada','cobrada_parcial','anulada')),
        monto_cobrado   REAL NOT NULL DEFAULT 0,
        archivo_origen  TEXT,
        notas           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS facturas_recibidas (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nro_factura     TEXT NOT NULL,
        tipo            TEXT NOT NULL,
        fecha_emision   TEXT NOT NULL,
        fecha_vencimiento TEXT,
        proveedor_id    INTEGER REFERENCES proveedores(id),
        cuit_proveedor  TEXT NOT NULL,
        razon_social_proveedor TEXT NOT NULL,
        neto            REAL NOT NULL DEFAULT 0,
        iva             REAL NOT NULL DEFAULT 0,
        retenciones     REAL NOT NULL DEFAULT 0,
        total           REAL NOT NULL DEFAULT 0,
        moneda          TEXT NOT NULL DEFAULT 'ARS',
        estado          TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','pagada','pagada_parcial','anulada')),
        monto_pagado    REAL NOT NULL DEFAULT 0,
        archivo_origen  TEXT,
        notas           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS conciliaciones (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        movimiento_id   INTEGER NOT NULL REFERENCES movimientos(id),
        factura_tipo    TEXT NOT NULL CHECK (factura_tipo IN ('emitida','recibida')),
        factura_id      INTEGER NOT NULL,
        monto_aplicado  REAL NOT NULL,
        metodo          TEXT NOT NULL
                        CHECK (metodo IN ('automatico_exacto','automatico_cuit',
                                          'automatico_fuzzy','automatico_parcial',
                                          'manual')),
        confianza       REAL NOT NULL DEFAULT 1.0,
        notas           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS cotizaciones_usd (
        fecha           TEXT PRIMARY KEY,
        oficial         REAL NOT NULL,
        blue            REAL,
        mep             REAL,
        fuente          TEXT DEFAULT 'manual'
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS auditoria (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        accion          TEXT NOT NULL,
        tabla_afectada  TEXT,
        registro_id     INTEGER,
        detalle         TEXT,
        usuario         TEXT DEFAULT 'contador',
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS config (
        clave           TEXT PRIMARY KEY,
        valor           TEXT NOT NULL,
        descripcion     TEXT
    )
    """,

    # Índices para consultas frecuentes
    "CREATE INDEX IF NOT EXISTS idx_mov_fecha ON movimientos(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_mov_conciliado ON movimientos(conciliado)",
    "CREATE INDEX IF NOT EXISTS idx_fe_estado ON facturas_emitidas(estado)",
    "CREATE INDEX IF NOT EXISTS idx_fe_cuit ON facturas_emitidas(cuit_cliente)",
    "CREATE INDEX IF NOT EXISTS idx_fe_vto ON facturas_emitidas(fecha_vencimiento)",
    "CREATE INDEX IF NOT EXISTS idx_fr_estado ON facturas_recibidas(estado)",
]

# Configuración por defecto
DEFAULT_CONFIG = {
    "saldo_minimo_alerta": "100000",
    "hora_reporte_diario": "18:00",
    "backup_dia_semana": "1",
    "tolerancia_dias_conciliacion": "5",
    "umbral_fuzzy_match": "85",
    "moneda_base": "ARS",
    "reporte_email_activo": "0",
    "reporte_whatsapp_activo": "0",
}
