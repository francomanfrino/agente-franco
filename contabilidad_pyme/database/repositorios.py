"""
Data access layer — thin wrappers around raw SQLite queries.
All methods receive an open sqlite3.Connection and return dicts / lists.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Empresa ──────────────────────────────────────────────────────────────────

def get_empresa(conn: sqlite3.Connection) -> dict | None:
    return _row_to_dict(conn.execute("SELECT * FROM empresa WHERE id=1").fetchone())


def upsert_empresa(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute("""
        INSERT INTO empresa (id, razon_social, cuit, email, whatsapp, domicilio)
        VALUES (1, :razon_social, :cuit, :email, :whatsapp, :domicilio)
        ON CONFLICT(id) DO UPDATE SET
            razon_social=excluded.razon_social,
            cuit=excluded.cuit,
            email=excluded.email,
            whatsapp=excluded.whatsapp,
            domicilio=excluded.domicilio
    """, data)


# ── Cuentas bancarias ────────────────────────────────────────────────────────

def get_cuentas(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM cuentas_bancarias WHERE activa=1").fetchall())


def insert_cuenta(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute("""
        INSERT INTO cuentas_bancarias (banco, tipo, moneda, nro_cuenta, cbu, alias)
        VALUES (:banco, :tipo, :moneda, :nro_cuenta, :cbu, :alias)
    """, data)
    return cur.lastrowid


# ── Movimientos ──────────────────────────────────────────────────────────────

def insert_movimientos_bulk(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert multiple movements, skip duplicates by (cuenta_id, fecha, descripcion, credito, debito)."""
    inserted = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT INTO movimientos
                    (cuenta_id, fecha, descripcion, debito, credito, saldo,
                     referencia, archivo_origen, conciliado)
                VALUES
                    (:cuenta_id, :fecha, :descripcion, :debito, :credito, :saldo,
                     :referencia, :archivo_origen, :conciliado)
            """, row)
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    return inserted


def get_movimientos(conn: sqlite3.Connection, cuenta_id: int | None = None,
                    solo_no_conciliados: bool = False) -> list[dict]:
    q = "SELECT * FROM movimientos"
    params: list[Any] = []
    conditions = []
    if cuenta_id:
        conditions.append("cuenta_id=?")
        params.append(cuenta_id)
    if solo_no_conciliados:
        conditions.append("conciliado=0")
    if conditions:
        q += " WHERE " + " AND ".join(conditions)
    q += " ORDER BY fecha DESC"
    return _rows_to_dicts(conn.execute(q, params).fetchall())


def marcar_movimiento_conciliado(conn: sqlite3.Connection, mov_id: int) -> None:
    conn.execute("UPDATE movimientos SET conciliado=1 WHERE id=?", (mov_id,))


# ── Facturas emitidas ────────────────────────────────────────────────────────

def insert_facturas_emitidas_bulk(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT INTO facturas_emitidas
                    (nro_factura, tipo, fecha_emision, fecha_vencimiento,
                     cuit_cliente, razon_social_cliente, neto, iva, percepciones,
                     total, condicion_pago, estado, monto_cobrado, archivo_origen)
                VALUES
                    (:nro_factura, :tipo, :fecha_emision, :fecha_vencimiento,
                     :cuit_cliente, :razon_social_cliente, :neto, :iva, :percepciones,
                     :total, :condicion_pago, :estado, :monto_cobrado, :archivo_origen)
            """, row)
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    return inserted


def get_facturas_emitidas(conn: sqlite3.Connection,
                          estado: str | None = None) -> list[dict]:
    q = "SELECT * FROM facturas_emitidas"
    params: list[Any] = []
    if estado:
        q += " WHERE estado=?"
        params.append(estado)
    q += " ORDER BY fecha_emision DESC"
    return _rows_to_dicts(conn.execute(q, params).fetchall())


def update_factura_emitida_cobro(conn: sqlite3.Connection, fac_id: int,
                                  monto_adicional: float) -> None:
    conn.execute("""
        UPDATE facturas_emitidas
        SET monto_cobrado = monto_cobrado + ?,
            estado = CASE
                WHEN monto_cobrado + ? >= total THEN 'cobrada'
                ELSE 'cobrada_parcial'
            END
        WHERE id=?
    """, (monto_adicional, monto_adicional, fac_id))


# ── Facturas recibidas ───────────────────────────────────────────────────────

def insert_facturas_recibidas_bulk(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT INTO facturas_recibidas
                    (nro_factura, tipo, fecha_emision, fecha_vencimiento,
                     cuit_proveedor, razon_social_proveedor, neto, iva,
                     retenciones, total, estado, monto_pagado, archivo_origen)
                VALUES
                    (:nro_factura, :tipo, :fecha_emision, :fecha_vencimiento,
                     :cuit_proveedor, :razon_social_proveedor, :neto, :iva,
                     :retenciones, :total, :estado, :monto_pagado, :archivo_origen)
            """, row)
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    return inserted


def get_facturas_recibidas(conn: sqlite3.Connection,
                            estado: str | None = None) -> list[dict]:
    q = "SELECT * FROM facturas_recibidas"
    params: list[Any] = []
    if estado:
        q += " WHERE estado=?"
        params.append(estado)
    q += " ORDER BY fecha_emision DESC"
    return _rows_to_dicts(conn.execute(q, params).fetchall())


# ── Conciliaciones ───────────────────────────────────────────────────────────

def insert_conciliacion(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute("""
        INSERT INTO conciliaciones
            (movimiento_id, factura_tipo, factura_id, monto_aplicado, metodo, confianza, notas)
        VALUES
            (:movimiento_id, :factura_tipo, :factura_id, :monto_aplicado, :metodo, :confianza, :notas)
    """, data)
    return cur.lastrowid


def get_conciliaciones(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM conciliaciones ORDER BY created_at DESC").fetchall())


def delete_conciliacion(conn: sqlite3.Connection, conc_id: int) -> None:
    """Remove a reconciliation (user overrides it manually)."""
    row = _row_to_dict(conn.execute("SELECT * FROM conciliaciones WHERE id=?", (conc_id,)).fetchone())
    if not row:
        return
    # Revert movement and invoice state
    conn.execute("UPDATE movimientos SET conciliado=0 WHERE id=?", (row["movimiento_id"],))
    if row["factura_tipo"] == "emitida":
        conn.execute("""
            UPDATE facturas_emitidas
            SET monto_cobrado = MAX(0, monto_cobrado - ?),
                estado = 'pendiente'
            WHERE id=?
        """, (row["monto_aplicado"], row["factura_id"]))
    conn.execute("DELETE FROM conciliaciones WHERE id=?", (conc_id,))


# ── Clientes / Proveedores ───────────────────────────────────────────────────

def upsert_cliente(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute("""
        INSERT INTO clientes (cuit, razon_social, email, condicion_pago)
        VALUES (:cuit, :razon_social, :email, :condicion_pago)
        ON CONFLICT(cuit) DO UPDATE SET
            razon_social=excluded.razon_social,
            email=COALESCE(excluded.email, clientes.email)
    """, data)


def get_clientes(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM clientes ORDER BY razon_social").fetchall())


def get_proveedores(conn: sqlite3.Connection, solo_recurrentes: bool = False) -> list[dict]:
    q = "SELECT * FROM proveedores"
    if solo_recurrentes:
        q += " WHERE es_recurrente=1"
    return _rows_to_dicts(conn.execute(q).fetchall())


# ── Config ───────────────────────────────────────────────────────────────────

def get_config(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT clave, valor FROM config").fetchall()
    return {r["clave"]: r["valor"] for r in rows}


def set_config(conn: sqlite3.Connection, clave: str, valor: str) -> None:
    conn.execute("""
        INSERT INTO config (clave, valor)
        VALUES (?, ?)
        ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor
    """, (clave, valor))


def init_default_config(conn: sqlite3.Connection) -> None:
    from database.models import DEFAULT_CONFIG
    for k, v in DEFAULT_CONFIG.items():
        conn.execute("""
            INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)
        """, (k, v))


# ── Auditoria ────────────────────────────────────────────────────────────────

def log_auditoria(conn: sqlite3.Connection, accion: str,
                   tabla: str | None = None, registro_id: int | None = None,
                   detalle: str | None = None) -> None:
    conn.execute("""
        INSERT INTO auditoria (accion, tabla_afectada, registro_id, detalle)
        VALUES (?, ?, ?, ?)
    """, (accion, tabla, registro_id, detalle))


# ── Dashboard summary ────────────────────────────────────────────────────────

def get_resumen_dashboard(conn: sqlite3.Connection) -> dict:
    """Single query bundle for the dashboard header."""
    saldo = conn.execute("""
        SELECT SUM(credito) - SUM(debito) as saldo
        FROM movimientos
    """).fetchone()["saldo"] or 0

    total_cobrar = conn.execute("""
        SELECT COALESCE(SUM(total - monto_cobrado), 0) as total
        FROM facturas_emitidas
        WHERE estado IN ('pendiente','cobrada_parcial')
    """).fetchone()["total"]

    total_pagar = conn.execute("""
        SELECT COALESCE(SUM(total - monto_pagado), 0) as total
        FROM facturas_recibidas
        WHERE estado IN ('pendiente','pagada_parcial')
    """).fetchone()["total"]

    return {
        "saldo_bancario": saldo,
        "total_cobrar": total_cobrar,
        "total_pagar": total_pagar,
        "saldo_neto": total_cobrar - total_pagar,
    }
