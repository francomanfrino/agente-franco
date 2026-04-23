"""
Conciliacion tab — shows automatic matches + pending items.
Allows the user to accept/reject automatic matches and drag-drop manual ones.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QSplitter, QHeaderView, QComboBox,
    QProgressBar, QMessageBox, QFrame,
)

from database.db import get_connection
from database.repositorios import (
    get_movimientos, get_facturas_emitidas, insert_conciliacion,
    marcar_movimiento_conciliado, update_factura_emitida_cobro,
    log_auditoria, get_conciliaciones,
)
from core.conciliacion import (
    conciliar, MovimientoDTO, FacturaDTO, ConciliacionResult,
)


class ConciliacionWorker(QThread):
    finished = pyqtSignal(list, list, list)
    error = pyqtSignal(str)

    def run(self):
        try:
            conn = get_connection()
            movs_raw = get_movimientos(conn, solo_no_conciliados=True)
            facs_raw = get_facturas_emitidas(conn)
            conn.close()

            movs = [MovimientoDTO(
                id=m["id"], fecha=m["fecha"], descripcion=m["descripcion"],
                credito=m["credito"] or 0, debito=m["debito"] or 0,
                conciliado=bool(m["conciliado"]),
                es_transferencia_interna=bool(m["es_transferencia_interna"]),
            ) for m in movs_raw]

            facs = [FacturaDTO(
                id=f["id"], nro_factura=f["nro_factura"],
                fecha_emision=f["fecha_emision"],
                fecha_vencimiento=f.get("fecha_vencimiento"),
                cuit=f["cuit_cliente"],
                razon_social=f["razon_social_cliente"],
                total=f["total"],
                monto_cobrado=f["monto_cobrado"] or 0,
                estado=f["estado"],
                tipo="emitida",
            ) for f in facs_raw]

            matches, unmatched_mov, unmatched_fac = conciliar(movs, facs)
            self.finished.emit(matches, unmatched_mov, unmatched_fac)
        except Exception as e:
            self.error.emit(str(e))


class TabConciliacion(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_matches: list[ConciliacionResult] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Controls
        ctrl = QHBoxLayout()
        self.btn_run = QPushButton("▶  Ejecutar Conciliación Automática")
        self.btn_run.clicked.connect(self._run_conciliacion)
        ctrl.addWidget(self.btn_run)

        self.btn_accept_all = QPushButton("✓  Aceptar Todo")
        self.btn_accept_all.clicked.connect(self._accept_all)
        self.btn_accept_all.setEnabled(False)
        ctrl.addWidget(self.btn_accept_all)

        self.btn_accept_selected = QPushButton("✓  Aceptar Seleccionados")
        self.btn_accept_selected.clicked.connect(self._accept_selected)
        self.btn_accept_selected.setEnabled(False)
        ctrl.addWidget(self.btn_accept_selected)

        ctrl.addStretch()
        self.lbl_status = QLabel("")
        ctrl.addWidget(self.lbl_status)
        layout.addLayout(ctrl)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Splitter: matches table | unmatched movements
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Matches table
        matches_frame = QFrame()
        matches_frame.setObjectName("card")
        mf_layout = QVBoxLayout(matches_frame)
        mf_layout.addWidget(QLabel("Matches automáticos (pendientes de confirmar)"))

        self.table_matches = QTableWidget(0, 7)
        self.table_matches.setHorizontalHeaderLabels([
            "Movimiento", "Fecha Mov", "Monto Mov", "Factura", "Cliente", "Método", "Confianza"
        ])
        self.table_matches.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_matches.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_matches.setAlternatingRowColors(True)
        mf_layout.addWidget(self.table_matches)
        splitter.addWidget(matches_frame)

        # Unmatched movements
        unmatched_frame = QFrame()
        unmatched_frame.setObjectName("card")
        uf_layout = QVBoxLayout(unmatched_frame)
        uf_layout.addWidget(QLabel("Movimientos sin conciliar"))

        self.table_unmatched = QTableWidget(0, 5)
        self.table_unmatched.setHorizontalHeaderLabels([
            "ID", "Fecha", "Descripción", "Crédito", "Débito"
        ])
        self.table_unmatched.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_unmatched.setAlternatingRowColors(True)
        uf_layout.addWidget(self.table_unmatched)
        splitter.addWidget(unmatched_frame)

        splitter.setSizes([450, 200])
        layout.addWidget(splitter)

    def reload(self):
        self._run_conciliacion()

    def _run_conciliacion(self):
        self.btn_run.setEnabled(False)
        self.btn_accept_all.setEnabled(False)
        self.btn_accept_selected.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.lbl_status.setText("Ejecutando conciliación...")

        self._worker = ConciliacionWorker()
        self._worker.finished.connect(self._on_conciliacion_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_conciliacion_done(self, matches: list, unmatched_mov: list, unmatched_fac: list):
        self._pending_matches = matches
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)

        self._populate_matches(matches)
        self._populate_unmatched(unmatched_mov)

        confirmed = sum(1 for m in matches if not m.es_probable)
        probable = sum(1 for m in matches if m.es_probable)
        self.lbl_status.setText(
            f"{confirmed} matches confirmados, {probable} probables, "
            f"{len(unmatched_mov)} movs sin conciliar"
        )

        if matches:
            self.btn_accept_all.setEnabled(True)
            self.btn_accept_selected.setEnabled(True)

    def _on_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Error en conciliación: {msg}")

    def _populate_matches(self, matches: list[ConciliacionResult]):
        self.table_matches.setRowCount(0)
        conn = get_connection()
        movs = {m["id"]: m for m in get_movimientos(conn)}
        facs = {f["id"]: f for f in get_facturas_emitidas(conn)}
        conn.close()

        for i, match in enumerate(matches):
            self.table_matches.insertRow(i)
            mov = movs.get(match.movimiento_id, {})
            fac = facs.get(match.factura_id, {})

            conf_pct = f"{match.confianza * 100:.0f}%"
            conf_color = Qt.GlobalColor.green if match.confianza >= 0.9 else Qt.GlobalColor.yellow

            items = [
                mov.get("descripcion", "")[:40],
                mov.get("fecha", ""),
                f"${mov.get('credito', 0):,.2f}",
                fac.get("nro_factura", ""),
                fac.get("razon_social_cliente", "")[:30],
                match.metodo.replace("automatico_", "").replace("_", " ").title(),
                conf_pct,
            ]
            for j, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, i)
                if j == 6:  # confianza column
                    item.setForeground(conf_color)
                if match.es_probable:
                    item.setForeground(Qt.GlobalColor.yellow)
                self.table_matches.setItem(i, j, item)

    def _populate_unmatched(self, unmatched_ids: list[int]):
        self.table_unmatched.setRowCount(0)
        if not unmatched_ids:
            return
        conn = get_connection()
        all_movs = {m["id"]: m for m in get_movimientos(conn)}
        conn.close()

        for i, mid in enumerate(unmatched_ids):
            mov = all_movs.get(mid, {})
            if not mov:
                continue
            self.table_unmatched.insertRow(i)
            for j, val in enumerate([
                str(mov.get("id", "")),
                mov.get("fecha", ""),
                mov.get("descripcion", "")[:60],
                f"${mov.get('credito', 0):,.2f}",
                f"${mov.get('debito', 0):,.2f}",
            ]):
                self.table_unmatched.setItem(i, j, QTableWidgetItem(val))

    def _accept_all(self):
        self._save_matches(self._pending_matches)

    def _accept_selected(self):
        selected_rows = set(
            self.table_matches.item(i.row(), 0).data(Qt.ItemDataRole.UserRole)
            for i in self.table_matches.selectedItems()
        )
        selected = [m for i, m in enumerate(self._pending_matches) if i in selected_rows]
        self._save_matches(selected)

    def _save_matches(self, matches: list[ConciliacionResult]):
        if not matches:
            return
        conn = get_connection()
        try:
            with conn:
                for m in matches:
                    insert_conciliacion(conn, {
                        "movimiento_id": m.movimiento_id,
                        "factura_tipo": m.factura_tipo,
                        "factura_id": m.factura_id,
                        "monto_aplicado": m.monto_aplicado,
                        "metodo": m.metodo,
                        "confianza": m.confianza,
                        "notas": m.notas,
                    })
                    marcar_movimiento_conciliado(conn, m.movimiento_id)
                    if m.factura_tipo == "emitida":
                        update_factura_emitida_cobro(conn, m.factura_id, m.monto_aplicado)
                    log_auditoria(conn, "conciliacion_guardada",
                                  "conciliaciones", None,
                                  f"mov={m.movimiento_id} fac={m.factura_id} metodo={m.metodo}")
        finally:
            conn.close()

        QMessageBox.information(self, "Listo", f"{len(matches)} conciliaciones guardadas.")
        self._run_conciliacion()
