import asyncio
import logging
from typing import Callable, Optional

import qasync
from PySide6.QtCore import QSize, Qt, Slot, QTimer
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton,
    QToolButton, QVBoxLayout, QWidget, QStyle,
)

from obs_client import OBSClient
from obs_data import OBSState
from websocket_finder import DiscoveredOBS, find_all_obs_websockets

logger = logging.getLogger(__name__)


class DisplaySettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Display Settings")
        self.setMinimumWidth(340)
        layout = QFormLayout(self)

        self._cb_scenes = QCheckBox("Scenes")
        self._cb_sources = QCheckBox("Sources")
        self._cb_audio = QCheckBox("Audio Meters")
        self._cb_stats = QCheckBox("Stats")
        self._cb_media = QCheckBox("Media Controls")

        self._cb_scenes.setChecked(config.get("display_scenes", True))
        self._cb_sources.setChecked(config.get("display_sources", True))
        self._cb_audio.setChecked(config.get("display_audio", True))
        self._cb_stats.setChecked(config.get("display_stats", True))
        self._cb_media.setChecked(config.get("display_media", True))

        for cb in (self._cb_scenes, self._cb_sources, self._cb_audio, self._cb_stats, self._cb_media):
            layout.addRow(cb)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def settings(self) -> dict:
        return {
            "display_scenes": self._cb_scenes.isChecked(),
            "display_sources": self._cb_sources.isChecked(),
            "display_audio": self._cb_audio.isChecked(),
            "display_stats": self._cb_stats.isChecked(),
            "display_media": self._cb_media.isChecked(),
        }


class _AnimatedDots:
    def __init__(self):
        self._counter = 0

    def text(self, base: str) -> str:
        self._counter = (self._counter + 1) % 4
        return base + "." * self._counter


class ConnectionScreen(QWidget):
    _sig_instance_selected = None  # set after qasync init
    _sig_settings_changed = None

    def __init__(
        self,
        on_instance_selected: Callable[[str, int, Optional[str]], None],
        on_settings_changed: Callable[[dict], None],
        config: dict,
        parent=None,
    ):
        super().__init__(parent)
        self._on_instance_selected = on_instance_selected
        self._on_settings_changed = on_settings_changed
        self._config = config
        self._scan_task: Optional[asyncio.Task] = None
        self._discovered: list[DiscoveredOBS] = []
        self._dots = _AnimatedDots()
        self._pending_connects: dict[str, DiscoveredOBS] = {}
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(48, 40, 48, 40)
        main_layout.setSpacing(16)

        header = QHBoxLayout()
        self._title_label = QLabel("OBS WebSocket Finder")
        self._title_label.setObjectName("title")
        header.addWidget(self._title_label)

        header.addStretch()

        settings_btn = QToolButton()
        settings_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_SettingsIcon))
        settings_btn.setToolTip("Display Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)

        main_layout.addLayout(header)

        self._status_label = QLabel("Initializing scan…")
        self._status_label.setObjectName("subtitle")
        main_layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        main_layout.addWidget(self._progress)

        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        main_layout.addWidget(self._list_widget, 1)

        btn_row = QHBoxLayout()

        self._refresh_btn = QPushButton("Refresh Scan")
        self._refresh_btn.setProperty("secondary", "true")
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        btn_row.addWidget(self._refresh_btn)

        btn_row.addStretch()

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setProperty("primary", "true")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._connect_btn.setEnabled(False)
        btn_row.addWidget(self._connect_btn)

        main_layout.addLayout(btn_row)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #d32f2f; font-size: 12px;")
        self._error_label.setWordWrap(True)
        main_layout.addWidget(self._error_label)

        self._retry_timer = QTimer(self)
        self._retry_timer.timeout.connect(self._animate_status)
        self._retry_timer.start(400)

    def _animate_status(self):
        if self._progress.isVisible():
            self._status_label.setText(self._dots.text("Scanning all network interfaces"))

    @Slot()
    def _on_refresh_clicked(self):
        if self._scan_task is not None and not self._scan_task.done():
            return
        self._list_widget.clear()
        self._discovered.clear()
        self._error_label.setText("")
        self._status_label.setText("Scanning all network interfaces…")
        self._progress.show()
        self._connect_btn.setEnabled(False)
        self._scan_task = asyncio.create_task(self._run_scan())

    def refresh_scan(self):
        self._on_refresh_clicked()

    @Slot(str)
    def show_error(self, msg: str):
        self._error_label.setText(msg)
        self._progress.hide()

    def _open_settings(self):
        dlg = DisplaySettingsDialog(self._config, self)
        if dlg.exec():
            new_cfg = dlg.settings()
            self._config.update(new_cfg)
            if self._on_settings_changed:
                self._on_settings_changed(new_cfg)

    async def _run_scan(self):
        try:
            found_any = False
            async for inst in find_all_obs_websockets(timeout=8.0):
                found_any = True
                self._discovered.append(inst)
                self._add_list_item(inst)
            if not found_any:
                self._status_label.setText("No OBS WebSocket instances found.")
            else:
                self._status_label.setText(f"Found {len(self._discovered)} instance(s).")
            self._progress.hide()
        except asyncio.CancelledError:
            self._progress.hide()
            raise

    def _add_list_item(self, inst: DiscoveredOBS):
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(8, 8, 8, 8)

        info_layout = QVBoxLayout()
        addr_label = QLabel(f"<b>{inst.address}</b>")
        addr_label.setStyleSheet("font-size: 14px;")
        info_layout.addWidget(addr_label)

        detail_row = QHBoxLayout()
        if inst.obs_version:
            badge = QLabel(f"OBS {inst.obs_version}")
            badge.setStyleSheet(
                "background: #e3f2fd; color: #1565c0; border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            detail_row.addWidget(badge)
        if inst.ws_version:
            ws_badge = QLabel(f"WS {inst.ws_version}")
            ws_badge.setStyleSheet(
                "background: #f3e5f5; color: #6a1b9a; border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            detail_row.addWidget(ws_badge)
        detail_row.addStretch()
        info_layout.addLayout(detail_row)

        item_layout.addLayout(info_layout, 1)
        item_layout.addWidget(QLabel(f"{'Identified' if inst.identified else 'Auth required'}"))

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, inst)
        item.setSizeHint(item_widget.sizeHint() + QSize(0, 20))
        self._list_widget.addItem(item)
        self._list_widget.setItemWidget(item, item_widget)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        inst = item.data(Qt.ItemDataRole.UserRole)
        if inst:
            self._prompt_password(inst)

    @Slot()
    def _on_connect_clicked(self):
        current = self._list_widget.currentItem()
        if not current:
            return
        inst = current.data(Qt.ItemDataRole.UserRole)
        if inst:
            self._prompt_password(inst)

    def _prompt_password(self, inst: DiscoveredOBS):
        if not inst.identified:
            pwd_dlg = QDialog(self)
            pwd_dlg.setWindowTitle("Enter OBS WebSocket Password")
            pwd_dlg.setModal(True)
            layout = QFormLayout(pwd_dlg)
            pwd_input = QLineEdit()
            pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addRow("Password:", pwd_input)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(pwd_dlg.accept)
            bb.rejected.connect(pwd_dlg.reject)
            layout.addRow(bb)

            def _do_accept():
                pwd_dlg.hide()
                self._do_connect(inst, pwd_input.text())

            def _do_reject():
                pwd_dlg.hide()

            bb.accepted.disconnect()
            bb.accepted.connect(_do_accept)
            bb.rejected.disconnect()
            bb.rejected.connect(_do_reject)

            pwd_dlg.open()
        else:
            self._do_connect(inst, None)

    def _do_connect(self, inst: DiscoveredOBS, password: Optional[str]):
        if self._on_instance_selected:
            self._on_instance_selected(inst.host, inst.port, password)
