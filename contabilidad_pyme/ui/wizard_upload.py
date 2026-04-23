"""
Step-by-step file upload wizard.
Step 1: Select file type and file
Step 2: Preview + column mapping
Step 3: Import & confirm
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QComboBox, QTableWidget, QTableWidgetItem,
    QWizard, QWizardPage, QFormLayout, QLineEdit,
    QHeaderView, QMessageBox, QFrame, QScrollArea,
)

from core.importador import (
    load_file, auto_map_extracto, auto_map_facturas,
    parse_extracto_rows, parse_facturas_rows, MappingResult,
)
from database.db import get_connection
from database.repositorios import (
    get_cuentas, insert_movimientos_bulk,
    insert_facturas_emitidas_bulk, insert_facturas_recibidas_bulk,
    log_auditoria,
)


LOGICAL_LABELS = {
    "fecha": "Fecha",
    "descripcion": "Descripción / Concepto",
    "debito": "Débito / Cargo",
    "credito": "Crédito / Abono",
    "saldo": "Saldo",
    "referencia": "Referencia / Nro operación",
    "nro_factura": "Nro Factura",
    "tipo": "Tipo (A/B/C)",
    "fecha_emision": "Fecha Emisión",
    "fecha_vencimiento": "Fecha Vencimiento",
    "cuit": "CUIT",
    "razon_social": "Razón Social",
    "neto": "Neto",
    "iva": "IVA",
    "percepciones": "Percepciones",
    "total": "Total",
}


class Page1_FileSelect(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Paso 1 — Seleccionar archivo")
        self.setSubTitle("Elegí el tipo de archivo y seleccioná el archivo a importar.")
        self._path: str | None = None

        layout = QFormLayout(self)

        self.tipo_combo = QComboBox()
        self.tipo_combo.addItems([
            "Extracto bancario",
            "Facturas emitidas",
            "Facturas recibidas",
        ])
        layout.addRow("Tipo de archivo:", self.tipo_combo)

        # Cuenta selector (only for extractos)
        self.cuenta_combo = QComboBox()
        self._load_cuentas()
        self.cuenta_label = QLabel("Cuenta bancaria:")
        layout.addRow(self.cuenta_label, self.cuenta_combo)
        self.tipo_combo.currentIndexChanged.connect(self._on_tipo_change)
        self._on_tipo_change(0)

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Ruta del archivo...")
        self.path_edit.setReadOnly(True)
        btn_browse = QPushButton("Examinar...")
        btn_browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit)
        file_row.addWidget(btn_browse)
        layout.addRow("Archivo:", file_row)

        self.registerField("file_path*", self.path_edit)
        self.registerField("file_type", self.tipo_combo, "currentText")

    def _load_cuentas(self):
        try:
            conn = get_connection()
            cuentas = get_cuentas(conn)
            conn.close()
            for c in cuentas:
                self.cuenta_combo.addItem(
                    f"{c['banco']} — {c.get('alias', c.get('nro_cuenta',''))}",
                    userData=c["id"]
                )
            if not cuentas:
                self.cuenta_combo.addItem("(sin cuentas — agregar en Configuración)", userData=None)
        except Exception:
            self.cuenta_combo.addItem("(error cargando cuentas)", userData=None)

    def _on_tipo_change(self, idx: int):
        is_extracto = idx == 0
        self.cuenta_label.setVisible(is_extracto)
        self.cuenta_combo.setVisible(is_extracto)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo",
            "", "Archivos Excel/CSV (*.xlsx *.xls *.csv)"
        )
        if path:
            self.path_edit.setText(path)
            self._path = path

    def get_cuenta_id(self) -> int | None:
        return self.cuenta_combo.currentData()


class Page2_ColumnMapping(QWizardPage):
    def __init__(self, page1: Page1_FileSelect):
        super().__init__()
        self.page1 = page1
        self.setTitle("Paso 2 — Vista previa y mapeo de columnas")
        self.setSubTitle("Verificá que las columnas estén bien mapeadas. Podés corregirlas manualmente.")

        self._mapping_result: MappingResult | None = None
        self._column_selectors: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)

        # Preview table
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setMaximumHeight(180)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(QLabel("Vista previa (primeras 5 filas):"))
        layout.addWidget(self.preview_table)

        # Column mapping form
        layout.addWidget(QLabel("Mapeo de columnas:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._map_widget = QFrame()
        self._map_layout = QFormLayout(self._map_widget)
        scroll.setWidget(self._map_widget)
        layout.addWidget(scroll)

    def initializePage(self):
        path = self.page1.field("file_path")
        tipo = self.page1.field("file_type")
        if not path:
            return
        try:
            df = load_file(path)
            if tipo == "Extracto bancario":
                result = auto_map_extracto(df)
            elif tipo == "Facturas emitidas":
                result = auto_map_facturas(df, "emitidas")
            else:
                result = auto_map_facturas(df, "recibidas")
            self._mapping_result = result
            self._show_preview(df)
            self._show_mapping(result)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo leer el archivo:\n{e}")

    def _show_preview(self, df):
        preview = df.head(5)
        self.preview_table.setRowCount(len(preview))
        self.preview_table.setColumnCount(len(preview.columns))
        self.preview_table.setHorizontalHeaderLabels(list(preview.columns))
        for i, row in enumerate(preview.itertuples(index=False)):
            for j, val in enumerate(row):
                self.preview_table.setItem(i, j, QTableWidgetItem(str(val) if val else ""))

    def _show_mapping(self, result: MappingResult):
        # Clear old selectors
        while self._map_layout.rowCount():
            self._map_layout.removeRow(0)
        self._column_selectors.clear()

        columns = list(result.df.columns)
        options = ["(no mapear)"] + columns

        for logical, label in LOGICAL_LABELS.items():
            # Only show relevant fields
            if result.file_type == "extracto" and logical not in (
                "fecha","descripcion","debito","credito","saldo","referencia"
            ):
                continue
            if result.file_type.startswith("facturas") and logical in (
                "debito","credito","saldo","referencia"
            ):
                continue

            combo = QComboBox()
            combo.addItems(options)
            mapped = result.column_map.get(logical)
            if mapped and mapped in columns:
                combo.setCurrentText(mapped)
            self._column_selectors[logical] = combo
            self._map_layout.addRow(f"{label}:", combo)

    def get_final_mapping(self) -> dict[str, str]:
        mapping = {}
        for logical, combo in self._column_selectors.items():
            val = combo.currentText()
            if val != "(no mapear)":
                mapping[logical] = val
        return mapping

    def get_mapping_result(self) -> MappingResult | None:
        return self._mapping_result


class Page3_Confirm(QWizardPage):
    def __init__(self, page1: Page1_FileSelect, page2: Page2_ColumnMapping):
        super().__init__()
        self.page1 = page1
        self.page2 = page2
        self.setTitle("Paso 3 — Confirmar importación")
        self._imported = 0

        layout = QVBoxLayout(self)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

    def initializePage(self):
        result = self.page2.get_mapping_result()
        if not result:
            self.lbl_summary.setText("No hay datos para importar.")
            return

        mapping = self.page2.get_final_mapping()
        result.column_map = mapping
        tipo = self.page1.field("file_type")

        try:
            if tipo == "Extracto bancario":
                cuenta_id = self.page1.get_cuenta_id() or 1
                rows = parse_extracto_rows(result, cuenta_id, Path(self.page1.field("file_path")).name)
            elif tipo == "Facturas emitidas":
                result.file_type = "facturas_emitidas"
                rows = parse_facturas_rows(result, Path(self.page1.field("file_path")).name)
            else:
                result.file_type = "facturas_recibidas"
                rows = parse_facturas_rows(result, Path(self.page1.field("file_path")).name)

            self.lbl_summary.setText(
                f"Se encontraron <b>{len(rows)} registros</b> para importar.\n"
                f"Archivo: {Path(self.page1.field('file_path')).name}\n"
                f"Tipo: {tipo}\n\n"
                f"Presioná <b>Finalizar</b> para importar."
            )
            self._rows_to_import = rows
            self._tipo = tipo
        except Exception as e:
            self.lbl_summary.setText(f"Error procesando archivo: {e}")
            self._rows_to_import = []

    def validatePage(self) -> bool:
        if not hasattr(self, "_rows_to_import") or not self._rows_to_import:
            QMessageBox.warning(self, "Sin datos", "No hay filas válidas para importar.")
            return False
        try:
            conn = get_connection()
            with conn:
                tipo = self._tipo
                if tipo == "Extracto bancario":
                    n = insert_movimientos_bulk(conn, self._rows_to_import)
                elif tipo == "Facturas emitidas":
                    n = insert_facturas_emitidas_bulk(conn, self._rows_to_import)
                else:
                    n = insert_facturas_recibidas_bulk(conn, self._rows_to_import)
                log_auditoria(conn, f"importacion_{tipo.lower().replace(' ','_')}",
                              detalle=f"{n} registros importados de {Path(self.page1.field('file_path')).name}")
            conn.close()
            self._imported = n
            QMessageBox.information(self, "Importación exitosa", f"Se importaron {n} registros.")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al importar: {e}")
            return False


class WizardUpload(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar Archivo")
        self.setMinimumSize(800, 600)

        p1 = Page1_FileSelect()
        p2 = Page2_ColumnMapping(p1)
        p3 = Page3_Confirm(p1, p2)

        self.addPage(p1)
        self.addPage(p2)
        self.addPage(p3)

        self._page1 = p1
