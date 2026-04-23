"""
ContabilidadAR — Entry point.
"""
import sys
import os

# Ensure project root is in path when run from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from database.db import init_db
from database.repositorios import init_default_config
from database.db import get_connection


def main():
    # Init DB
    init_db()
    conn = get_connection()
    with conn:
        init_default_config(conn)
    conn.close()

    app = QApplication(sys.argv)
    app.setApplicationName("ContabilidadAR")

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    # Load initial data
    window.tab_cxc.reload()
    window.tab_cxp.reload()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
