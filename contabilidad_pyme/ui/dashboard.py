"""KPI card row for the dashboard header."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel


class KPICard(QFrame):
    def __init__(self, title: str, icon: str = "", color: str = "#e94560"):
        super().__init__()
        self.setObjectName("card")
        self.setMinimumWidth(200)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.title_lbl = QLabel(f"{icon}  {title}" if icon else title)
        self.title_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")

        self.value_lbl = QLabel("—")
        font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        self.value_lbl.setFont(font)
        self.value_lbl.setStyleSheet(f"color: {color};")

        self.sub_lbl = QLabel("")
        self.sub_lbl.setStyleSheet("color: #888; font-size: 11px;")

        layout.addWidget(self.title_lbl)
        layout.addWidget(self.value_lbl)
        layout.addWidget(self.sub_lbl)

    def set_value(self, value: float, prefix: str = "$", suffix: str = ""):
        self.value_lbl.setText(f"{prefix}{value:,.0f}{suffix}")

    def set_subtitle(self, text: str):
        self.sub_lbl.setText(text)


class DashboardHeader(QFrame):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        self.card_saldo = KPICard("Saldo Bancario", "🏦", "#4fc3f7")
        self.card_cobrar = KPICard("Total a Cobrar", "📥", "#81c784")
        self.card_pagar = KPICard("Total a Pagar", "📤", "#ff8a65")
        self.card_neto = KPICard("Saldo Neto 30d", "📊", "#ce93d8")

        for card in (self.card_saldo, self.card_cobrar, self.card_pagar, self.card_neto):
            layout.addWidget(card)

    def update_values(self, summary: dict):
        self.card_saldo.set_value(summary.get("saldo_bancario", 0))
        self.card_cobrar.set_value(summary.get("total_cobrar", 0))
        self.card_pagar.set_value(summary.get("total_pagar", 0))
        self.card_neto.set_value(summary.get("saldo_neto", 0))
