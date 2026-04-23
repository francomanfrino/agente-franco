"""
Main application window.
Hosts the dashboard header + 4 tabs + sidebar alerts.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QFrame, QSplitter,
    QStatusBar, QScrollArea, QMessageBox, QApplication,
)

from database.db import get_connection
from database.repositorios import get_resumen_dashboard
from ui.dashboard import DashboardHeader
from ui.tab_conciliacion import TabConciliacion
from ui.tab_cxc import TabCuentasPorCobrar
from ui.tab_cxp import TabCuentasPorPagar
from ui.wizard_upload import WizardUpload


STYLE_SHEET = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #2d2d4e;
    background: #16213e;
    border-radius: 6px;
}
QTabBar::tab {
    background: #0f3460;
    color: #a0a0c0;
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 3px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background: #e94560;
    color: white;
}
QTabBar::tab:hover:!selected {
    background: #1a4a80;
    color: white;
}
QPushButton {
    background-color: #0f3460;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #1a4a80;
}
QPushButton#btn_upload {
    background-color: #e94560;
    font-size: 14px;
    padding: 12px 24px;
    border-radius: 8px;
}
QPushButton#btn_upload:hover {
    background-color: #c73652;
}
QTableWidget {
    background-color: #16213e;
    gridline-color: #2d2d4e;
    border: 1px solid #2d2d4e;
    border-radius: 4px;
    selection-background-color: #e94560;
    alternate-background-color: #1e2a4a;
}
QTableWidget::item {
    padding: 6px;
}
QHeaderView::section {
    background-color: #0f3460;
    color: white;
    padding: 8px;
    border: none;
    font-weight: bold;
}
QFrame#card {
    background-color: #16213e;
    border: 1px solid #2d2d4e;
    border-radius: 10px;
    padding: 12px;
}
QLabel#alert_rojo {
    color: #ff4444;
    background-color: #3d0000;
    border-left: 4px solid #ff4444;
    padding: 6px 10px;
    border-radius: 4px;
}
QLabel#alert_amarillo {
    color: #ffaa00;
    background-color: #3d2d00;
    border-left: 4px solid #ffaa00;
    padding: 6px 10px;
    border-radius: 4px;
}
QScrollBar:vertical {
    background: #16213e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #0f3460;
    border-radius: 5px;
    min-height: 30px;
}
"""


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contabilidad PyME Argentina")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(STYLE_SHEET)

        self._build_ui()
        self._refresh_dashboard()

        # Auto-refresh every 60 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_dashboard)
        self._timer.start(60_000)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 8)
        main_layout.setSpacing(12)

        # ── Top bar ──────────────────────────────────────────────────────────
        top_bar = QHBoxLayout()

        title_label = QLabel("ContabilidadAR")
        title_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #e94560;")
        top_bar.addWidget(title_label)
        top_bar.addStretch()

        self.btn_upload = QPushButton("⬆  Subir Archivos")
        self.btn_upload.setObjectName("btn_upload")
        self.btn_upload.clicked.connect(self._open_wizard)
        top_bar.addWidget(self.btn_upload)

        self.btn_refresh = QPushButton("↻  Actualizar")
        self.btn_refresh.clicked.connect(self._refresh_dashboard)
        top_bar.addWidget(self.btn_refresh)

        main_layout.addLayout(top_bar)

        # ── Dashboard header (KPI cards) ─────────────────────────────────────
        self.dashboard_header = DashboardHeader()
        main_layout.addWidget(self.dashboard_header)

        # ── Main splitter: tabs | alerts sidebar ─────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_conciliacion = TabConciliacion(self)
        self.tab_cxc = TabCuentasPorCobrar(self)
        self.tab_cxp = TabCuentasPorPagar(self)

        self.tabs.addTab(self.tab_conciliacion, "⚡  Conciliación")
        self.tabs.addTab(self.tab_cxc, "📥  Cuentas por Cobrar")
        self.tabs.addTab(self.tab_cxp, "📤  Cuentas por Pagar")
        splitter.addWidget(self.tabs)

        # Alerts sidebar
        sidebar = self._build_alerts_sidebar()
        splitter.addWidget(sidebar)
        splitter.setSizes([900, 300])

        main_layout.addWidget(splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Listo")

    def _build_alerts_sidebar(self) -> QWidget:
        container = QFrame()
        container.setObjectName("card")
        layout = QVBoxLayout(container)

        header = QLabel("🔔  Alertas Pendientes")
        header.setStyleSheet("font-weight: bold; font-size: 14px; color: #e94560;")
        layout.addWidget(header)

        self.alerts_scroll = QScrollArea()
        self.alerts_scroll.setWidgetResizable(True)
        self.alerts_content = QWidget()
        self.alerts_layout = QVBoxLayout(self.alerts_content)
        self.alerts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.alerts_scroll.setWidget(self.alerts_content)
        layout.addWidget(self.alerts_scroll)

        return container

    def _refresh_dashboard(self):
        try:
            conn = get_connection()
            summary = get_resumen_dashboard(conn)
            conn.close()
            self.dashboard_header.update_values(summary)
            self._refresh_alerts(summary)
            self.status_bar.showMessage(
                f"Actualizado: {__import__('datetime').datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            self.status_bar.showMessage(f"Error al actualizar: {e}")

    def _refresh_alerts(self, summary: dict):
        # Clear old alerts
        while self.alerts_layout.count():
            item = self.alerts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        alerts = []

        # Low balance alert
        try:
            conn = get_connection()
            from database.repositorios import get_config
            cfg = get_config(conn)
            conn.close()
            minimo = float(cfg.get("saldo_minimo_alerta", "100000"))
            if summary["saldo_bancario"] < minimo:
                alerts.append(("rojo", f"⚠ Saldo bancario bajo el mínimo: ${summary['saldo_bancario']:,.0f}"))
        except Exception:
            pass

        if not alerts:
            lbl = QLabel("Sin alertas críticas ✓")
            lbl.setStyleSheet("color: #4caf50; padding: 8px;")
            self.alerts_layout.addWidget(lbl)
            return

        for severity, msg in alerts:
            lbl = QLabel(msg)
            lbl.setObjectName(f"alert_{severity}")
            lbl.setWordWrap(True)
            self.alerts_layout.addWidget(lbl)

    def _open_wizard(self):
        wizard = WizardUpload(self)
        if wizard.exec():
            self._refresh_dashboard()
            self.tab_conciliacion.reload()
            self.tab_cxc.reload()
            self.tab_cxp.reload()
