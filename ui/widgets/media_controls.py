from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QScrollArea,
)


class MediaControlWidget(QWidget):
    def __init__(self, input_name: str, on_action: callable, parent=None):
        super().__init__(parent)
        self._input_name = input_name
        self._on_action = on_action
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        name_lbl = QLabel(self._input_name)
        name_lbl.setMinimumWidth(160)
        name_lbl.setStyleSheet("font-weight: 500;")
        layout.addWidget(name_lbl)

        for label, action in [
            ("Play", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"),
            ("Pause", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"),
            ("Stop", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"),
            ("Restart", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, a=action: self._on_action(a))
            layout.addWidget(btn)

    def _on_action(self, action: str):
        if self._on_action:
            self._on_action(self._input_name, action)


class MediaControlsPanel(QScrollArea):
    def __init__(self, on_action: callable = None, parent=None):
        super().__init__(parent)
        self._on_action = on_action
        self._widgets: dict[str, MediaControlWidget] = {}
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(8)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()
        self.setWidgetResizable(True)
        self.setWidget(self._container)

    def update_media_inputs(self, inputs: dict):
        media_inputs = {
            name: inp for name, inp in inputs.items() if inp.is_media
        }

        existing = set(self._widgets.keys())
        current = set(media_inputs.keys())

        for name in existing - current:
            w = self._widgets.pop(name)
            w.deleteLater()

        if not media_inputs:
            if not hasattr(self, "_empty_lbl"):
                self._empty_lbl = QLabel("(No media inputs detected. Add a media source in OBS to see controls here.)")
                self._empty_lbl.setStyleSheet("color: #888; font-style: italic;")
                self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._container_layout.insertWidget(0, self._empty_lbl)
            return

        if hasattr(self, "_empty_lbl"):
            self._empty_lbl.deleteLater()
            del self._empty_lbl

        for name, inp in media_inputs.items():
            if name not in self._widgets:
                w = MediaControlWidget(name, self._on_action_wrapper)
                self._widgets[name] = w
                self._container_layout.insertWidget(
                    self._container_layout.count() - 1, w
                )

    def _on_action_wrapper(self, input_name: str, action: str):
        if self._on_action:
            self._on_action(input_name, action)
