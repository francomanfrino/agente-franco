"""
Lector del SQLite de gestion para el reporte diario.
Complementa el CONTROL DIARIO con datos del sistema de gestion.
"""

import gc
import gzip
import io
import logging
import sqlite3
import tempfile
import os
from datetime import date, datetime

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from tools.drive import _get_credentials

log = logging.getLogger(__name__)

BACKUP_FOLDER_ID = "1VB8482Pt-mvM1eAZi4H7gaDma9vh9l4q"


def _descargar_sqlite() -> str:
    """Descarga el backup mas reciente de Drive y retorna la ruta al archivo temporal."""
    drive = build("drive", "v3", credentials=_get_credentials())

    files = drive.files().list(
        q=f"'{BACKUP_FOLDER_ID}' in parents and trashed = false",
        fields="files(id, name)",
        orderBy="modifiedTime desc",
        pageSize=1
    ).execute().get("files", [])

    if not files:
        raise FileNotFoundError("No se encontro el backup SQLite en Drive.")

    archivo = files[0]
    log.info(f"Descargando backup: {archivo['name']}")

    request = drive.files().get_media(fileId=archivo["id"])
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    data = buf.getvalue()
    if archivo["name"].endswith(".gz"):
        data = gzip.decompress(data)

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def analizar_sistema(fecha: date = None) -> dict:
    """
    Lee el SQLite y retorna datos del dia para el reporte.
    """
    if fecha is None:
        fecha = date.today()

    fecha_str = fecha.strftime("%Y-%m-%d")

    db_path = _descargar_sqlite()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        resultado = {}

        # ── Ventas del dia ─────────────────────────────────────────────────────
        cur.execute("""
            SELECT id, total, estado, forma_pago
            FROM ventas
            WHERE date(created_at) = ?
            AND estado != 'ANULADA'
        """, (fecha_str,))
        ventas = cur.fetchall()
        resultado["ventas_count"] = len(ventas)
        resultado["ventas_total"] = sum(float(v["total"] or 0) for v in ventas)

        # ── Items de ventas (para detectar camiones completos) ─────────────────
        cur.execute("""
            SELECT vi.cantidad, vi.precio_unitario, vi.total_linea,
                   p.nombre as producto, v.id as venta_id
            FROM venta_items vi
            JOIN ventas v ON v.id = vi.venta_id
            JOIN productos p ON p.id = vi.producto_id
            WHERE date(v.created_at) = ?
            AND v.estado != 'ANULADA'
        """, (fecha_str,))
        items = cur.fetchall()

        camiones = [i for i in items if float(i["cantidad"] or 0) >= 25000]
        resultado["camiones_completos"] = [
            {
                "producto": i["producto"],
                "cantidad": int(float(i["cantidad"])),
                "total":    float(i["total_linea"] or 0),
            }
            for i in camiones
        ]

        # ── Gastos del dia ─────────────────────────────────────────────────────
        cur.execute("""
            SELECT g.monto, g.descripcion, g.fecha,
                   cg.nombre as categoria
            FROM gastos g
            LEFT JOIN categoria_gastos cg ON cg.id = g.categoria_gasto_id
            WHERE date(g.fecha) = ?
            ORDER BY g.monto DESC
        """, (fecha_str,))
        gastos = cur.fetchall()

        EXCLUIR_CAT = ["banco", "transport", "alquil", "impuest", "retenci"]
        gastos_alertas = []
        total_gastos = 0
        for g in gastos:
            monto = float(g["monto"] or 0)
            total_gastos += monto
            cat = (g["categoria"] or "").lower()
            if monto > 30_000_000 and not any(kw in cat for kw in EXCLUIR_CAT):
                gastos_alertas.append({
                    "descripcion": g["descripcion"] or g["categoria"] or "Sin descripcion",
                    "monto":       monto,
                    "categoria":   g["categoria"] or "Sin categoria",
                })

        resultado["gastos_total"]   = total_gastos
        resultado["gastos_alertas"] = gastos_alertas
        resultado["gastos_count"]   = len(gastos)

        # ── Cajas ──────────────────────────────────────────────────────────────
        cur.execute("SELECT nombre, saldo_actual, tipo FROM cajas ORDER BY saldo_actual DESC")
        cajas = cur.fetchall()
        resultado["cajas"] = [
            {"nombre": c["nombre"], "saldo": float(c["saldo_actual"] or 0), "tipo": c["tipo"]}
            for c in cajas
        ]
        resultado["cajas_total"] = sum(float(c["saldo_actual"] or 0) for c in cajas)

        # ── Pedidos del dia ────────────────────────────────────────────────────
        cur.execute("""
            SELECT COUNT(*) as total, estado
            FROM pedidos
            WHERE date(created_at) = ?
            GROUP BY estado
        """, (fecha_str,))
        pedidos = cur.fetchall()
        resultado["pedidos"] = {p["estado"]: p["total"] for p in pedidos}

        conn.close()
        conn = None
        return resultado

    finally:
        gc.collect()  # fuerza liberacion de handles en Windows
        try:
            os.unlink(db_path)
        except OSError:
            pass


def formatear_seccion_sistema(datos: dict) -> list[str]:
    """Formatea los datos del sistema para el reporte de Telegram."""
    def fmt(n):
        try:
            v = float(n)
            if abs(v) >= 1_000_000:
                return f"${v/1_000_000:.1f}M"
            return f"${v:,.0f}"
        except Exception:
            return str(n)

    lineas = ["\n🖥️ *Sistema de Gestión*"]

    lineas.append(f"📦 Ventas registradas: {datos['ventas_count']} | Total: {fmt(datos['ventas_total'])}")
    lineas.append(f"💸 Gastos del día: {datos['gastos_count']} | Total: {fmt(datos['gastos_total'])}")

    # Cajas top 3
    cajas_top = sorted(datos["cajas"], key=lambda x: abs(x["saldo"]), reverse=True)[:3]
    if cajas_top:
        lineas.append(f"\n🏦 *Cajas principales:*")
        for c in cajas_top:
            lineas.append(f"  • {c['nombre']}: {fmt(c['saldo'])}")
        lineas.append(f"  *Total cajas: {fmt(datos['cajas_total'])}*")

    # Camiones completos
    if datos["camiones_completos"]:
        lineas.append(f"\n🚛 *Camiones completos ({len(datos['camiones_completos'])}):*")
        for c in datos["camiones_completos"][:5]:
            lineas.append(f"  • {c['producto'][:35]} — {c['cantidad']:,} u → {fmt(c['total'])}")
    else:
        lineas.append("\n🚛 *Camiones completos:* Ninguno")

    # Pedidos
    if datos["pedidos"]:
        lineas.append(f"\n📋 *Pedidos del día:*")
        for estado, count in datos["pedidos"].items():
            lineas.append(f"  • {estado}: {count}")

    # Alertas de gastos
    if datos["gastos_alertas"]:
        lineas.append(f"\n⚠️ *Gastos inusuales (>{'>'}$30M):*")
        for g in datos["gastos_alertas"][:5]:
            lineas.append(f"  • {g['descripcion'][:50]} — {fmt(g['monto'])} ({g['categoria']})")

    return lineas
