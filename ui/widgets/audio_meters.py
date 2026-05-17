from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class AudioMeterWidget(QWidget):
    def __init__(self, input_name: str, on_mute_toggle: callable = None, parent=None):
        super().__init__(parent)
        self._input_name = input_name
        self._on_mute_toggle = on_mute_toggle
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        self._name_label = QLabel(self._input_name)
        self._name_label.setMinimumWidth(160)
        top_row.addWidget(self._name_label)

        self._mute_btn = QPushButton("Mute")
        self._mute_btn.setFixedWidth(60)
        self._mute_btn.clicked.connect(self._on_mute_click)
        top_row.addWidget(self._mute_btn)

        self._vol_label = QLabel("0%")
        self._vol_label.setFixedWidth(40)
        top_row.addWidget(self._vol_label)

        layout.addLayout(top_row)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

    def update(self, volume: float, muted: bool):
        pct = min(int(volume * 100), 100)
        self._bar.setValue(pct)
        self._vol_label.setText(f"{pct}%")
        self._mute_btn.setText("Unmute" if muted else "Mute")

        if muted:
            bar_style = "QProgressBar::chunk { background: #ef5350; border-radius: 4px; }"
        else:
            bar_style = "QProgressBar::chunk { background: #66bb6a; border-radius: 4px; }"
        self._bar.setStyleSheet(bar_style)

    def _on_mute_click(self):
        if self._on_mute_toggle:
            self._on_mute_toggle(self._input_name)


class AudioMetersPanel(QWidget):
    def __init__(self, on_mute_toggle: callable = None, parent=None):
        super().__init__(parent)
        self._on_mute_toggle = on_mute_toggle
        self._meters: dict[str, AudioMeterWidget] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout

    def update_inputs(self, inputs: dict):
        current_names = set(inputs.keys())
        existing_names = set(self._meters.keys())

        for name in existing_names - current_names:
            w = self._meters.pop(name)
            w.deleteLater()

        for name, inp in inputs.items():
            if name not in self._meters:
                meter = AudioMeterWidget(name, self._on_mute_toggle)
                self._meters[name] = meter
                self._layout.addWidget(meter)
            self._meters[name].update(inp.volume, inp.muted)
