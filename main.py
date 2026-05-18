import asyncio
import logging
import sys

import qasync
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from logging_config import setup_logging
from ui.obs_dashboard import BG, TEXT_PRIMARY, TEXT_MUTED, ACCENT, ACCENT_DIM

setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    logger.info("OBS PyGUI starting — Qt style: Fusion")
    app.setStyle("Fusion")
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(BG))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    dark.setColor(QPalette.ColorRole.Base, QColor("#0e0e18"))
    dark.setColor(QPalette.ColorRole.AlternateBase, QColor("#13131f"))
    dark.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e1e2e"))
    dark.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    dark.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    dark.setColor(QPalette.ColorRole.Button, QColor("#1e1e2e"))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_PRIMARY))
    dark.setColor(QPalette.ColorRole.BrightText, QColor(ACCENT))
    dark.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_DIM))
    dark.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    dark.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    app.setPalette(dark)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    main_window = MainWindow()
    main_window.show()
    logger.info("MainWindow displayed")

    try:
        with loop:
            loop.run_forever()
    finally:
        logger.info("OBS PyGUI shutting down")


if __name__ == "__main__":
    main()
