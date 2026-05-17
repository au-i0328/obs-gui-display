from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget


class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        fields = [
            ("FPS", "fps"),
            ("CPU Usage", "cpu"),
            ("Memory (MB)", "mem"),
            ("Bitrate (kbps)", "bitrate"),
            ("Dropped Frames", "dropped"),
            ("Total Frames", "total"),
            ("Stream Time", "stream_time"),
            ("Recording Time", "rec_time"),
        ]

        grid = QGridLayout()
        grid.setSpacing(12)

        for row, (label_text, key) in enumerate(fields):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #666; font-size: 12px; font-weight: 500;")
            grid.addWidget(lbl, row, 0)

            val_lbl = QLabel("—")
            val_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a2e;")
            grid.addWidget(val_lbl, row, 1)
            self._labels[key] = val_lbl

        layout.addLayout(grid)
        layout.addStretch()

    def update_stats(self, stats):
        mapping = {
            "fps": f"{stats.fps:.1f}",
            "cpu": f"{stats.cpu_usage:.1f}%",
            "mem": f"{stats.memory_usage:.1f}",
            "bitrate": f"{stats.network_bitrate / 1000.0:.0f}",
            "dropped": str(stats.num_dropped_frames),
            "total": str(stats.num_total_frames),
            "stream_time": stats.stream_timecode,
            "rec_time": stats.recording_timecode,
        }
        for key, val in mapping.items():
            if key in self._labels:
                self._labels[key].setText(val)
