"""
Seed the database with fictional but realistic Argentine PyME data.
Run with: python data/seed_data.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import init_db, get_connection
from database.repositorios import (
    upsert_empresa, insert_cuenta, log_auditoria, init_default_config,
    set_config,
)


def seed():
    init_db()
    conn = get_connection()

    with conn:
        # Empresa
        upsert_empresa(conn, {
            "razon_social": "TECNOLOGIA DEL SUR S.R.L.",
            "cuit": "30712345678",
            "email": "contabilidad@tecnologiadelsur.com.ar",
            "whatsapp": "+5491112345678",
            "domicilio": "Av. Corrientes 1234, CABA",
        })

        # Cuentas bancarias
        conn.execute("DELETE FROM cuentas_bancarias")
        ids = {}
        for banco_data in [
            {"banco": "Banco Santander", "tipo": "CC", "moneda": "ARS",
             "nro_cuenta": "040-123456/7", "cbu": "0720040888000012345670", "alias": "SANTANDER.CC.TECNOSUR"},
            {"banco": "Banco Galicia", "tipo": "CA", "moneda": "ARS",
             "nro_cuenta": "001-1234567-8", "cbu": "0070001230000012345678", "alias": "GALICIA.CA.TECNOSUR"},
        ]:
            ids[banco_data["banco"]] = insert_cuenta(conn, banco_data)

        santander_id = ids["Banco Santander"]
        galicia_id = ids["Banco Galicia"]

        # Clientes
        clientes = [
            ("30567890123", "DISTRIBUIDORA NORTE S.A.", "pagos@dnorte.com.ar", 30),
            ("30678901234", "COMERCIO EL PROGRESO S.R.L.", "admin@elprogreso.com.ar", 60),
            ("20234567890", "JUAN CARLOS RODRIGUEZ", "jcrodriguez@gmail.com", 30),
            ("30789012345", "SUPER MERCADOS BUENOS AIRES S.A.", "proveedores@smba.com.ar", 90),
            ("30890123456", "LOGISTICA PAMPEANA SRL", "cuentas@logpampeana.com.ar", 45),
        ]
        conn.execute("DELETE FROM clientes")
        for cuit, razon, email, dias in clientes:
            conn.execute("""
                INSERT INTO clientes (cuit, razon_social, email, condicion_pago)
                VALUES (?, ?, ?, ?)
            """, (cuit, razon, email, dias))

        # Proveedores
        proveedores = [
            ("30111222333", "ALQUILER OFICINA BELGRANO", 1, "mensual"),
            ("30222333444", "TELECOM ARGENTINA S.A.", 1, "mensual"),
            ("30333444555", "MICROSOFT ARGENTINA", 1, "mensual"),
            ("30444555666", "PROVEEDOR INSUMOS S.A.", 0, None),
        ]
        conn.execute("DELETE FROM proveedores")
        for cuit, razon, recurrente, periodo in proveedores:
            conn.execute("""
                INSERT INTO proveedores (cuit, razon_social, es_recurrente, periodo_factura)
                VALUES (?, ?, ?, ?)
            """, (cuit, razon, recurrente, periodo))

        # Movimientos bancarios (Santander)
        conn.execute("DELETE FROM movimientos")
        movimientos = [
            # Cobros de clientes
            (santander_id, "2024-03-05", "TRANSFERENCIA RECIBIDA 30567890123 DISTRIBUIDORA NORTE", 0, 121000.00, None, "MOV001"),
            (santander_id, "2024-03-08", "CREDITO CUIT 30678901234 COMERCIO PROGRESO", 0, 48400.00, None, "MOV002"),
            (santander_id, "2024-03-12", "PAGO JUAN CARLOS RODRIGUEZ DNI", 0, 24200.00, None, "MOV003"),
            (santander_id, "2024-03-15", "DEBITO IMPUESTO IVA AFIP", 45000.00, 0, None, "MOV004"),
            (santander_id, "2024-03-18", "TRANSFERENCIA RECIBIDA SUPER MERCADOS BUENOS AIRES", 0, 363000.00, None, "MOV005"),
            (santander_id, "2024-03-20", "PAGO ALQUILER BELGRANO", 85000.00, 0, None, "MOV006"),
            (santander_id, "2024-03-22", "DEBITO TELECOM FACTURA MARZO", 12500.00, 0, None, "MOV007"),
            (santander_id, "2024-03-25", "TRANSFERENCIA RECIBIDA 30890123456 LOGISTICA PAMPEANA", 0, 96800.00, None, "MOV008"),
            (santander_id, "2024-03-28", "DEBITO SUELDOS PERSONAL", 380000.00, 0, None, "MOV009"),
            (santander_id, "2024-04-02", "TRANSFERENCIA RECIBIDA DISTRIBUIDORA NORTE SA", 0, 60500.00, None, "MOV010"),
            # Unmatched movement
            (santander_id, "2024-04-05", "CREDITO VARIOS ORIGEN DESCONOCIDO", 0, 15000.00, None, "MOV011"),
        ]
        for m in movimientos:
            conn.execute("""
                INSERT INTO movimientos (cuenta_id, fecha, descripcion, debito, credito, saldo, referencia, archivo_origen)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'seed_extracto.csv')
            """, m)

        # Facturas emitidas
        conn.execute("DELETE FROM facturas_emitidas")
        facturas_e = [
            # (nro, tipo, fecha_emision, fecha_vto, cuit_cli, razon_cli, neto, iva, perc, total, cond, estado, cobrado)
            ("0001-00000001", "A", "2024-02-10", "2024-03-11", "30567890123", "DISTRIBUIDORA NORTE S.A.",
             100000, 21000, 0, 121000, 30, "cobrada", 121000),
            ("0001-00000002", "A", "2024-02-15", "2024-03-16", "30678901234", "COMERCIO EL PROGRESO S.R.L.",
             40000, 8400, 0, 48400, 30, "cobrada", 48400),
            ("0001-00000003", "B", "2024-02-20", "2024-03-21", "20234567890", "JUAN CARLOS RODRIGUEZ",
             20000, 4200, 0, 24200, 30, "cobrada", 24200),
            ("0001-00000004", "A", "2024-02-25", "2024-05-26", "30789012345", "SUPER MERCADOS BUENOS AIRES S.A.",
             300000, 63000, 0, 363000, 90, "cobrada", 363000),
            ("0001-00000005", "A", "2024-03-01", "2024-04-15", "30890123456", "LOGISTICA PAMPEANA SRL",
             80000, 16800, 0, 96800, 45, "cobrada", 96800),
            ("0001-00000006", "A", "2024-03-05", "2024-04-04", "30567890123", "DISTRIBUIDORA NORTE S.A.",
             50000, 10500, 0, 60500, 30, "cobrada", 60500),
            # Facturas pendientes (overdue)
            ("0001-00000007", "A", "2024-03-10", "2024-04-09", "30678901234", "COMERCIO EL PROGRESO S.R.L.",
             75000, 15750, 0, 90750, 30, "pendiente", 0),
            ("0001-00000008", "A", "2024-03-15", "2024-04-14", "30789012345", "SUPER MERCADOS BUENOS AIRES S.A.",
             200000, 42000, 0, 242000, 30, "pendiente", 0),
            # Very overdue
            ("0001-00000009", "A", "2024-01-15", "2024-02-14", "30890123456", "LOGISTICA PAMPEANA SRL",
             60000, 12600, 0, 72600, 30, "pendiente", 0),
            # Cobrada parcialmente
            ("0001-00000010", "A", "2024-03-20", "2024-04-19", "30567890123", "DISTRIBUIDORA NORTE S.A.",
             120000, 25200, 0, 145200, 30, "cobrada_parcial", 50000),
        ]
        for f in facturas_e:
            conn.execute("""
                INSERT INTO facturas_emitidas
                    (nro_factura, tipo, fecha_emision, fecha_vencimiento, cuit_cliente,
                     razon_social_cliente, neto, iva, percepciones, total, condicion_pago,
                     estado, monto_cobrado, archivo_origen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'seed_facturas.xlsx')
            """, f)

        # Facturas recibidas (proveedores)
        conn.execute("DELETE FROM facturas_recibidas")
        facturas_r = [
            ("FC-00001234", "B", "2024-03-01", "2024-03-31", "30111222333", "ALQUILER OFICINA BELGRANO",
             70248, 14752, 0, 85000, "pagada", 85000),
            ("FC-00004567", "A", "2024-03-05", "2024-04-04", "30222333444", "TELECOM ARGENTINA S.A.",
             10331, 2169, 0, 12500, "pagada", 12500),
            ("FC-00007890", "A", "2024-03-10", "2024-04-09", "30333444555", "MICROSOFT ARGENTINA",
             24793, 5207, 0, 30000, "pendiente", 0),
            ("FC-00002345", "A", "2024-02-15", "2024-03-16", "30444555666", "PROVEEDOR INSUMOS S.A.",
             50000, 10500, 0, 60500, "pendiente", 0),
        ]
        for f in facturas_r:
            conn.execute("""
                INSERT INTO facturas_recibidas
                    (nro_factura, tipo, fecha_emision, fecha_vencimiento, cuit_proveedor,
                     razon_social_proveedor, neto, iva, retenciones, total, estado, monto_pagado,
                     archivo_origen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'seed_proveedores.xlsx')
            """, f)

        # Cotizacion USD
        conn.execute("DELETE FROM cotizaciones_usd")
        for fecha, oficial, blue in [
            ("2024-03-01", 855.00, 1030.00),
            ("2024-03-15", 862.50, 1040.00),
            ("2024-04-01", 875.00, 1060.00),
        ]:
            conn.execute("""
                INSERT INTO cotizaciones_usd (fecha, oficial, blue) VALUES (?,?,?)
            """, (fecha, oficial, blue))

        # Config
        init_default_config(conn)
        set_config(conn, "saldo_minimo_alerta", "200000")

        log_auditoria(conn, "seed_ejecutado", detalle="Base de datos poblada con datos ficticios")

    conn.close()
    print("✓ Seed completado. Base de datos lista en:", end=" ")
    from database.db import DB_PATH
    print(DB_PATH)


if __name__ == "__main__":
    seed()
