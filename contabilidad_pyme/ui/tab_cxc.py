"""Accounts Receivable tab — aging, semáforo, overdue list."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QFrame, QFileDialog, QComboBox,
)

from database.db import get_connection
from database.repositorios import get_facturas_emitidas
from core.alertas import get_facturas_vencidas
from services.exportador import export_to_excel, export_cxc_to_pdf
from database.repositorios import get_empresa


SEMAFORO_COLORS = {
    "verde": ("#1a3a1a", "#4caf50"),
    "amarillo": ("#3a3a00", "#ffeb3b"),
    "naranja": ("#3a2000", "#ff9800"),
    "rojo": ("#3a0000", "#f44336"),
}


class TabCuentasPorCobrar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Controls row
        ctrl = QHBoxLayout()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["Todas", "Solo vencidas", "0-30 días", "31-60 días", "61-90 días", "+90 días"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        ctrl.addWidget(QLabel("Filtrar:"))
        ctrl.addWidget(self.filter_combo)
        ctrl.addStretch()

        self.lbl_total = QLabel("Total pendiente: —")
        self.lbl_total.setStyleSheet("font-weight: bold; font-size: 14px; color: #81c784;")
        ctrl.addWidget(self.lbl_total)

        btn_excel = QPushButton("⬇  Exportar Excel")
        btn_excel.clicked.connect(self._export_excel)
        ctrl.addWidget(btn_excel)

        btn_pdf = QPushButton("⬇  Exportar PDF")
        btn_pdf.clicked.connect(self._export_pdf)
        ctrl.addWidget(btn_pdf)

        layout.addLayout(ctrl)

        # Summary cards row
        cards_row = QHBoxLayout()
        self.cards = {}
        for bucket, label in [("0-30","0-30 días"),("31-60","31-60 días"),("61-90","61-90 días"),("+90","+90 días")]:
            frame = QFrame()
            frame.setObjectName("card")
            fl = QVBoxLayout(frame)
            lbl_name = QLabel(label)
            lbl_name.setStyleSheet("font-size: 11px; color: #888;")
            lbl_val = QLabel("$0")
            lbl_val.setStyleSheet("font-size: 16px; font-weight: bold;")
            fl.addWidget(lbl_name)
            fl.addWidget(lbl_val)
            self.cards[bucket] = lbl_val
            cards_row.addWidget(frame)
        layout.addLayout(cards_row)

        # Table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Nro Factura", "Tipo", "Cliente", "CUIT",
            "Fecha Vto", "Total", "Pendiente", "Días mora"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

    def reload(self):
        conn = get_connection()
        facturas = get_facturas_emitidas(conn)
        conn.close()

        vencidas = get_facturas_vencidas(facturas)
        # Also include non-overdue pending invoices
        all_pending = [f for f in facturas if f.get("estado") in ("pendiente", "cobrada_parcial")]
        # Add overdue metadata to pending-but-not-yet-due
        overdue_ids = {v["id"] for v in vencidas}
        for f in all_pending:
            if f["id"] not in overdue_ids:
                f["dias_mora"] = 0
                f["bucket"] = "0-30"
                f["semaforo"] = "verde"

        self._data = vencidas + [f for f in all_pending if f["id"] not in overdue_ids]
        self._data.sort(key=lambda x: x.get("dias_mora", 0), reverse=True)
        self._update_cards()
        self._apply_filter(self.filter_combo.currentText())

    def _apply_filter(self, filtro: str):
        data = self._data
        if filtro == "Solo vencidas":
            data = [f for f in data if f.get("dias_mora", 0) > 0]
        elif filtro in ("0-30 días","31-60 días","61-90 días","+90 días"):
            bucket = filtro.replace(" días", "")
            data = [f for f in data if f.get("bucket") == bucket]
        self._populate_table(data)

    def _update_cards(self):
        totals = {"0-30": 0, "31-60": 0, "61-90": 0, "+90": 0}
        grand_total = 0
        for f in self._data:
            pendiente = f.get("total", 0) - f.get("monto_cobrado", 0)
            bucket = f.get("bucket", "0-30")
            if bucket in totals:
                totals[bucket] += pendiente
            grand_total += pendiente
        for bucket, lbl in self.cards.items():
            lbl.setText(f"${totals[bucket]:,.0f}")
        self.lbl_total.setText(f"Total pendiente: ${grand_total:,.0f}")

    def _populate_table(self, data: list[dict]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for i, f in enumerate(data):
            self.table.insertRow(i)
            pendiente = f.get("total", 0) - f.get("monto_cobrado", 0)
            sem = f.get("semaforo", "verde")
            bg, fg = SEMAFORO_COLORS.get(sem, ("#1a1a2e", "#e0e0e0"))

            for j, val in enumerate([
                f.get("nro_factura", ""),
                f.get("tipo", ""),
                f.get("razon_social_cliente", "")[:35],
                f.get("cuit_cliente", ""),
                f.get("fecha_vencimiento", ""),
                f"${f.get('total', 0):,.2f}",
                f"${pendiente:,.2f}",
                str(f.get("dias_mora", 0)),
            ]):
                item = QTableWidgetItem(val)
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)

    def _export_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", "cuentas_por_cobrar.xlsx", "Excel (*.xlsx)"
        )
        if path:
            export_to_excel({"Cuentas por Cobrar": self._data}, path)

    def _export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", "cuentas_por_cobrar.pdf", "PDF (*.pdf)"
        )
        if path:
            try:
                conn = get_connection()
                empresa = get_empresa(conn)
                conn.close()
                vencidas = [f for f in self._data if f.get("dias_mora", 0) > 0]
                export_cxc_to_pdf(vencidas, empresa, path)
            except ImportError as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Dependencia faltante", str(e))
