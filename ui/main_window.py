import logging
from typing import Optional

import qasync
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from config import load as load_config
from obs_client import OBSClient
from obs_data import OBSState
from ui.connection_screen import ConnectionScreen
from ui.obs_dashboard import OBSDashboard

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    ASPECT_RATIO = 16.0 / 9.0

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")

        # Start at a 16:9 size
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.geometry()
            start_w = min(1280, screen_geo.width() * 85 // 100)
            start_h = int(start_w / self.ASPECT_RATIO)
            if start_h > screen_geo.height() * 85 // 100:
                start_h = screen_geo.height() * 85 // 100
                start_w = int(start_h * self.ASPECT_RATIO)
        else:
            start_w, start_h = 1280, 720
        self.resize(start_w, start_h)

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

        self._menu_bar_h = self.menuBar().height() if self.menuBar() else 0

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
        logger.info("[MainWindow] User switched to: Connection Screen")
        self._stack.setCurrentWidget(self._connection_screen)

    def _show_dashboard(self):
        self._stack.setCurrentWidget(self._dashboard)

    @qasync.asyncSlot()
    async def _on_instance_selected(self, host: str, port: int, password: Optional[str]):
        logger.info("[MainWindow] Instance selected — host=%s port=%s hasPassword=%s", host, port, password is not None)
        self._client = OBSClient(host, port, password)
        try:
            await self._client.connect(timeout=5.0)
            self._client.on_event(self._on_obs_event)
            self._dashboard.obs_event.connect(self._dashboard.on_obs_event, Qt.QueuedConnection)
            state = await self._client.get_state()
            self._dashboard.bind(self._client, state)
            self._show_dashboard()
            self.setWindowTitle(f"OBS Studio — {host}:{port}")
            logger.info("[MainWindow] Successfully connected — dashboard shown")
        except Exception as e:
            logger.error("[MainWindow] Connection failed — host=%s port=%s error=%s", host, port, e)
            self._connection_screen.show_error(f"Connection failed: {e}")

    def _on_obs_event(self, event_name: str, event_data: dict):
        if self._client is None:
            return
        if event_name == "disconnected":
            qasync.QMetaObject.invokeMethod(self, "_on_disconnected", Qt.QueuedConnection)
            return
        self._dashboard.obs_event.emit(event_name)

    @qasync.asyncSlot()
    async def _on_disconnected(self):
        logger.warning("[MainWindow] OBS disconnected — returning to connection screen")
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._dashboard.unbind()
        self._connection_screen.show_error("OBS disconnected. Please select an instance.")
        self._show_connection_screen()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")

    @qasync.asyncSlot()
    async def _disconnect(self):
        logger.info("[MainWindow] User triggered: Disconnect via menu")
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._dashboard.unbind()
        self._show_connection_screen()
        self.setWindowTitle("OBS Studio — WebSocket Viewer")

    def _on_settings_changed(self, config: dict):
        logger.info("[MainWindow] Display settings changed: %s", config)
        self._config = config
        self._dashboard.apply_config(config)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        # Enforce 16:9 aspect ratio on every resize
        new_h = int(self.width() / self.ASPECT_RATIO)
        if abs(self.height() - new_h) > 2:
            self.resize(self.width(), new_h)

    def closeEvent(self, event):
        logger.info("[MainWindow] App closing — cleaning up OBS connection")
        self._dashboard._internet.stop()
        if self._client and self._client.is_connected():
            try:
                self._client._connected = False
                self._client._ws.disconnect()
            except Exception:
                pass
        event.accept()
