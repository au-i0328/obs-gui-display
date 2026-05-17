import qasync
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from obs_client import OBSClient
from obs_data import OBSState


class OBSDashboard(QWidget):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._client: OBSClient | None = None
        self._state: OBSState | None = None
        self._config = config
        self._child_widgets: list[QWidget] = []
        self._setup_ui()

    def _setup_ui(self):
        from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QPushButton, QLabel, QWidget
        from PySide6.QtCore import Qt

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()

        self._conn_label = QLabel("Not connected")
        self._conn_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #1a1a2e;")
        header.addWidget(self._conn_label)
        header.addStretch()

        self._stream_btn = QPushButton("Stream")
        self._stream_btn.setProperty("primary", "true")
        self._stream_btn.clicked.connect(qasync.asyncSlot()(self._on_stream_toggle))
        self._stream_btn.setEnabled(False)
        header.addWidget(self._stream_btn)

        self._rec_btn = QPushButton("Record")
        self._rec_btn.clicked.connect(qasync.asyncSlot()(self._on_rec_toggle))
        self._rec_btn.setEnabled(False)
        header.addWidget(self._rec_btn)

        layout.addLayout(header)

        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget, 1)

        self._scenes_widget: QWidget | None = None
        self._sources_widget: QWidget | None = None
        self._audio_widget: QWidget | None = None
        self._stats_widget: QWidget | None = None
        self._media_widget: QWidget | None = None

        self._rebuild_tabs()

    def _rebuild_tabs(self):
        self._tab_widget.clear()

        if self._config.get("display_scenes", True):
            self._scenes_widget = self._build_scenes_widget()
            self._tab_widget.addTab(self._scenes_widget, "Scenes")

        if self._config.get("display_sources", True):
            self._sources_widget = self._build_sources_widget()
            self._tab_widget.addTab(self._sources_widget, "Sources")

        if self._config.get("display_audio", True):
            self._audio_widget = self._build_audio_widget()
            self._tab_widget.addTab(self._audio_widget, "Audio")

        if self._config.get("display_stats", True):
            self._stats_widget = self._build_stats_widget()
            self._tab_widget.addTab(self._stats_widget, "Stats")

        if self._config.get("display_media", True):
            self._media_widget = self._build_media_widget()
            self._tab_widget.addTab(self._media_widget, "Media")

        if self._tab_widget.count() == 0:
            from PySide6.QtWidgets import QLabel
            empty = QLabel("All display panels are disabled.\nOpen Settings to enable them.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tab_widget.addTab(empty, "(No panels enabled)")

    def _build_scenes_widget(self) -> QWidget:
        from PySide6.QtWidgets import QListWidget, QVBoxLayout, QWidget
        from PySide6.QtCore import Qt

        w = QWidget()
        layout = QVBoxLayout(w)
        self._scene_list = QListWidget()
        self._scene_list.itemClicked.connect(qasync.asyncSlot()(self._on_scene_clicked))
        layout.addWidget(self._scene_list)
        return w

    def _build_sources_widget(self) -> QWidget:
        from PySide6.QtWidgets import QTreeWidget, QVBoxLayout, QWidget, QTreeWidgetItem
        from PySide6.QtCore import Qt

        w = QWidget()
        layout = QVBoxLayout(w)
        self._source_tree = QTreeWidget()
        self._source_tree.setHeaderLabels(["Name", "Kind", "Muted"])
        self._source_tree.header().setStretchLastSection(True)
        self._source_tree.setColumnWidth(0, 250)
        layout.addWidget(self._source_tree)
        return w

    def _build_audio_widget(self) -> QWidget:
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QProgressBar, QLabel, QHBoxLayout, QPushButton
        from PySide6.QtCore import Qt

        w = QWidget()
        self._audio_layout = QVBoxLayout(w)
        self._audio_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._audio_meters: dict[str, tuple[QProgressBar, QLabel]] = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        return scroll

    def _build_stats_widget(self) -> QWidget:
        from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget, QLabel, QFrame
        from PySide6.QtCore import Qt

        w = QWidget()
        layout = QVBoxLayout(w)
        grid = QGridLayout()
        grid.setSpacing(12)

        self._stat_labels: dict[str, QLabel] = {}
        stat_keys = [
            ("FPS", "fps"),
            ("CPU Usage", "cpu"),
            ("Memory (MB)", "mem"),
            ("Bitrate (kbps)", "bitrate"),
            ("Dropped Frames", "dropped"),
            ("Total Frames", "total"),
            ("Stream Time", "stream_time"),
            ("Recording Time", "rec_time"),
        ]

        for row, (label_text, key) in enumerate(stat_keys):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #666; font-size: 12px;")
            grid.addWidget(lbl, row, 0)

            val_lbl = QLabel("—")
            val_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a2e;")
            grid.addWidget(val_lbl, row, 1)
            self._stat_labels[key] = val_lbl

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _build_media_widget(self) -> QWidget:
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        self._media_layout = QVBoxLayout()
        self._media_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._media_buttons: dict[str, QWidget] = {}

        container = QWidget()
        container.setLayout(self._media_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def bind(self, client: OBSClient, state: OBSState):
        self._client = client
        self._state = state
        self._conn_label.setText(f"Connected — {client.url}")
        self._conn_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #2e7d32;")
        self._stream_btn.setEnabled(True)
        self._rec_btn.setEnabled(True)
        self._update_stream_btn()
        self._update_rec_btn()
        self._refresh_all()

    def unbind(self):
        self._client = None
        self._state = None
        self._conn_label.setText("Not connected")
        self._conn_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #888;")
        self._stream_btn.setEnabled(False)
        self._rec_btn.setEnabled(False)
        self._scene_list.clear()
        self._source_tree.clear()
        self._stat_labels.get("fps", QLabel()).setText("—")

    def apply_config(self, config: dict):
        self._config = config
        self._rebuild_tabs()
        if self._state:
            self._refresh_all()

    def _update_stream_btn(self):
        if self._state:
            label = "Stop Stream" if self._state.streaming else "Start Stream"
            self._stream_btn.setText(label)

    def _update_rec_btn(self):
        if self._state:
            label = "Stop Recording" if self._state.recording else "Start Recording"
            self._rec_btn.setText(label)

    def on_obs_event(self, event_name: str = None, event_data: dict = None):
        if not self._state:
            return
        if self._client:
            self._client.handle_event(event_name or "", event_data or {})
        if event_name in ("SceneListChanged", "CurrentProgramSceneChanged",
                          "CurrentPreviewSceneChanged", "StreamStateChanged",
                          "RecordingStateChanged", "InputVolumeChanged",
                          "InputMuteStateChanged"):
            self._refresh_all()

    def _refresh_all(self):
        if not self._state:
            return
        self._refresh_scenes()
        self._refresh_sources()
        self._refresh_audio()
        self._refresh_stats()
        self._refresh_media()
        self._update_stream_btn()
        self._update_rec_btn()

    def _refresh_scenes(self):
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtCore import Qt

        self._scene_list.clear()
        for name in self._state.scenes:
            item = QListWidgetItem(name)
            if name == self._state.current_program_scene:
                item.setBackground(Qt.GlobalColor.highlight)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._scene_list.addItem(item)

    def _refresh_sources(self):
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtCore import Qt

        self._source_tree.clear()
        for inp in self._state.inputs.values():
            item = QTreeWidgetItem([inp.input_name, inp.input_kind or "input", "Muted" if inp.muted else "—"])
            if inp.muted:
                item.setForeground(2, Qt.GlobalColor.red)
            self._source_tree.addTopLevelItem(item)

    def _refresh_audio(self):
        from PySide6.QtWidgets import QProgressBar, QLabel, QHBoxLayout, QWidget, QPushButton
        from PySide6.QtCore import Qt

        audio_inputs = [
            (name, inp) for name, inp in self._state.inputs.items()
            if inp.input_kind not in ("filter",) and hasattr(inp, "volume")
        ]

        while self._audio_layout.count():
            child = self._audio_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._audio_meters.clear()

        for name, inp in audio_inputs:
            row = QHBoxLayout()
            name_lbl = QLabel(name)
            name_lbl.setMinimumWidth(150)
            row.addWidget(name_lbl)

            bar = QProgressBar()
            bar.setRange(0, 100)
            vol_pct = min(int(inp.volume * 100), 100)
            bar.setValue(vol_pct)
            bar.setStyleSheet(
                f"QProgressBar {{ border-radius: 4px; text: {vol_pct}%; }}"
                f"QProgressBar::chunk {{ background: {'#ef5350' if inp.muted else '#66bb6a'}; border-radius: 4px; }}"
            )
            row.addWidget(bar, 1)

            mute_btn = QPushButton("Mute" if not inp.muted else "Unmute")
            mute_btn.clicked.connect(qasync.asyncSlot()(lambda n=name: self._on_mute_toggle(n)))
            row.addWidget(mute_btn)

            vol_lbl = QLabel(f"{inp.volume * 100:.0f}%")
            vol_lbl.setMinimumWidth(40)
            row.addWidget(vol_lbl)

            self._audio_layout.addLayout(row)
            self._audio_meters[name] = (bar, vol_lbl)

    def _refresh_stats(self):
        if not self._state:
            return
        stats = self._state.stats
        mapping = {
            "fps": f"{stats.fps:.1f}",
            "cpu": f"{stats.cpu_usage:.1f}%",
            "mem": f"{stats.memory_usage:.1f} MB",
            "bitrate": f"{stats.network_bitrate / 1000.0:.0f}",
            "dropped": str(stats.num_dropped_frames),
            "total": str(stats.num_total_frames),
            "stream_time": stats.stream_timecode,
            "rec_time": stats.recording_timecode,
        }
        for key, val in mapping.items():
            if key in self._stat_labels:
                self._stat_labels[key].setText(val)

    def _refresh_media(self):
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
        from PySide6.QtCore import Qt

        media_inputs = [
            (name, inp) for name, inp in self._state.inputs.items() if inp.is_media
        ]

        while self._media_layout.count():
            child = self._media_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not media_inputs:
            empty_lbl = QLabel("(No media inputs detected. Add a media source in OBS to see controls here.)")
            empty_lbl.setStyleSheet("color: #888; font-style: italic;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._media_layout.addWidget(empty_lbl)
            return

        for name, inp in media_inputs:
            row = QHBoxLayout()
            name_lbl = QLabel(name)
            name_lbl.setMinimumWidth(150)
            row.addWidget(name_lbl)

            play_btn = QPushButton("Play")
            play_btn.clicked.connect(qasync.asyncSlot()(lambda n=name: self._on_media_action(n, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY")))
            row.addWidget(play_btn)

            pause_btn = QPushButton("Pause")
            pause_btn.clicked.connect(qasync.asyncSlot()(lambda n=name: self._on_media_action(n, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE")))
            row.addWidget(pause_btn)

            stop_btn = QPushButton("Stop")
            stop_btn.clicked.connect(qasync.asyncSlot()(lambda n=name: self._on_media_action(n, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP")))
            row.addWidget(stop_btn)

            restart_btn = QPushButton("Restart")
            restart_btn.clicked.connect(qasync.asyncSlot()(lambda n=name: self._on_media_action(n, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")))
            row.addWidget(restart_btn)

            self._media_layout.addLayout(row)

    async def _on_stream_toggle(self):
        if self._client:
            await self._client.toggle_stream()
            state = await self._client.get_state()
            self._state = state
            self._update_stream_btn()

    async def _on_rec_toggle(self):
        if self._client:
            await self._client.toggle_recording()
            state = await self._client.get_state()
            self._state = state
            self._update_rec_btn()

    async def _on_scene_clicked(self, item):
        if self._client:
            await self._client.switch_scene(item.text())

    async def _on_mute_toggle(self, name: str):
        if self._client:
            await self._client.toggle_input_mute(name)
            self._refresh_audio()

    async def _on_media_action(self, name: str, action: str):
        if self._client:
            await self._client.trigger_media_action(name, action)
