import asyncio
import logging
from typing import Optional

import qasync
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from config import load as load_config
from obs_client import OBSClient
from obs_data import OBSState
from ui.connection_screen import ConnectionScreen
from ui.obs_dashboard import OBSDashboard

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)

        self._config = load_config()
        self._client: Optional[OBSClient] = None
        self._connect_password: Optional[str] = None

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._connection_screen = ConnectionScreen(
            on_instance_selected=self._on_instance_selected,
            on_settings_changed=self._on_settings_changed,
            config=self._config,
        )
        self._dashboard = OBSDashboard(config=self._config)

        self._stack.addWidget(self._connection_screen)
        self._stack.addWidget(self._dashboard)

        self._setup_menu()
        self._stack.setCurrentWidget(self._connection_screen)

    def _setup_menu(self):
        menubar = self.menuBar()
        view_menu = menubar.addMenu("View")

        toggle_conn = QAction("Connection Screen", self, checkable=True)
        toggle_conn.setChecked(False)
        toggle_conn.triggered.connect(lambda checked: self._show_connection_screen() if checked else None)
        view_menu.addAction(toggle_conn)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self._disconnect)
        view_menu.addAction(disconnect_action)

        view_menu.addSeparator()

        refresh_action = QAction("Refresh Scan", self)
        refresh_action.triggered.connect(self._connection_screen.refresh_scan)
        view_menu.addAction(refresh_action)

    def _show_connection_screen(self):
        self._stack.setCurrentWidget(self._connection_screen)

    def _show_dashboard(self):
        self._stack.setCurrentWidget(self._dashboard)

    @qasync.asyncSlot()
    async def _on_instance_selected(self, host: str, port: int, password: Optional[str]):
        url = f"ws://{host}:{port}"
        logger.info(f"Connecting to OBS at {url}...")
        self._client = OBSClient(url, password)
        try:
            await self._client.connect(timeout=5.0)
            self._client.on_event(self._on_obs_event)
            state = await self._client.get_state()
            self._dashboard.bind(self._client, state)
            self._show_dashboard()
            self.setWindowTitle(f"OBS Studio — {host}:{port}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connection_screen.show_error(f"Connection failed: {e}")

    def _on_obs_event(self, event_name: str, event_data: dict):
        if self._client is None:
            return
        if event_name == "disconnected":
            qasync.QMetaObject.invokeMethod(self, "_on_disconnected", Qt.QueuedConnection)
            return
        self._client.handle_event(event_name, event_data)
        qasync.QMetaObject.invokeMethod(
            self._dashboard, "on_obs_event", Qt.QueuedConnection,
            Qt.Q_ARG(str, event_name), Qt.Q_ARG(dict, event_data)
        )

    @qasync.asyncSlot()
    async def _on_disconnected(self):
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._dashboard.unbind()
        self._connection_screen.show_error("OBS disconnected. Please select an instance.")
        self._show_connection_screen()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")

    @qasync.asyncSlot()
    async def _disconnect(self):
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._dashboard.unbind()
        self._show_connection_screen()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")

    def _on_settings_changed(self, config: dict):
        self._config = config
        self._dashboard.apply_config(config)

    def closeEvent(self, event):
        if self._client:
            try:
                loop = asyncio.get_running_loop()
                loop.run_until_complete(self._client.disconnect())
            except Exception:
                pass
        event.accept()
