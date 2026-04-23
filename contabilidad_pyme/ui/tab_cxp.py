"""Accounts Payable tab."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QFileDialog,
)

from database.db import get_connection
from database.repositorios import get_facturas_recibidas
from core.alertas import get_facturas_vencidas
from services.exportador import export_to_excel

SEMAFORO_COLORS = {
    "verde": ("#1a3a1a", "#4caf50"),
    "amarillo": ("#3a3a00", "#ffeb3b"),
    "naranja": ("#3a2000", "#ff9800"),
    "rojo": ("#3a0000", "#f44336"),
}


class TabCuentasPorPagar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        ctrl = QHBoxLayout()
        self.lbl_total = QLabel("Total a pagar: —")
        self.lbl_total.setStyleSheet("font-weight: bold; font-size: 14px; color: #ff8a65;")
        ctrl.addWidget(self.lbl_total)
        ctrl.addStretch()

        btn_excel = QPushButton("⬇  Exportar Excel")
        btn_excel.clicked.connect(self._export_excel)
        ctrl.addWidget(btn_excel)
        layout.addLayout(ctrl)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Nro Factura", "Tipo", "Proveedor", "CUIT",
            "Fecha Vto", "Total", "Días mora",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

    def reload(self):
        conn = get_connection()
        facturas = get_facturas_recibidas(conn)
        conn.close()

        # Adapt to alertas function (uses cuit_cliente key internally for display)
        for f in facturas:
            f.setdefault("cuit_cliente", f.get("cuit_proveedor", ""))
            f.setdefault("razon_social_cliente", f.get("razon_social_proveedor", ""))
            f.setdefault("monto_cobrado", f.get("monto_pagado", 0))

        vencidas = get_facturas_vencidas(facturas)
        all_pending = [f for f in facturas if f.get("estado") in ("pendiente", "pagada_parcial")]
        overdue_ids = {v["id"] for v in vencidas}
        for f in all_pending:
            if f["id"] not in overdue_ids:
                f["dias_mora"] = 0
                f["bucket"] = "0-30"
                f["semaforo"] = "verde"

        self._data = vencidas + [f for f in all_pending if f["id"] not in overdue_ids]
        self._data.sort(key=lambda x: x.get("dias_mora", 0), reverse=True)

        total = sum(f.get("total", 0) - f.get("monto_pagado", 0) for f in all_pending)
        self.lbl_total.setText(f"Total a pagar: ${total:,.0f}")
        self._populate_table()

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for i, f in enumerate(self._data):
            self.table.insertRow(i)
            sem = f.get("semaforo", "verde")
            bg, fg = SEMAFORO_COLORS.get(sem, ("#1a1a2e", "#e0e0e0"))
            for j, val in enumerate([
                f.get("nro_factura", ""),
                f.get("tipo", ""),
                f.get("razon_social_proveedor", f.get("razon_social_cliente", ""))[:35],
                f.get("cuit_proveedor", f.get("cuit_cliente", "")),
                f.get("fecha_vencimiento", ""),
                f"${f.get('total', 0):,.2f}",
                str(f.get("dias_mora", 0)),
            ]):
                item = QTableWidgetItem(val)
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)

    def _export_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", "cuentas_por_pagar.xlsx", "Excel (*.xlsx)"
        )
        if path:
            export_to_excel({"Cuentas por Pagar": self._data}, path)
