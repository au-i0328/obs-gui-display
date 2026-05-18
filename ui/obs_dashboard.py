import logging
import math
import os
import platform
import threading
import time
from datetime import datetime

import qasync
from PySide6.QtCore import QEvent, QObject, Qt, QRectF, QTimer, Signal, Slot, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QFrame,
)

from obs_client import OBSClient
from obs_data import OBSState

logger = logging.getLogger(__name__)

# ── Shared dark palette ────────────────────────────────────────────────────────
BG = "#0b0b12"
TOPBAR_BG = "#10101a"
PANEL_BG = "#13131f"
PANEL_BORDER = "#1e1e2e"
ACCENT = "#00e5a0"
ACCENT_DIM = "#007a54"
LIVE_RED = "#ff3d5a"
WARN_ORANGE = "#ff9100"
TEXT_PRIMARY = "#d8d8e8"
TEXT_SECONDARY = "#6e6e8a"
TEXT_MUTED = "#3a3a52"
GRID_LINE = "#1a1a2a"

PANEL_H = """
    QFrame#panel {
        background: %s;
        border: 1px solid %s;
        border-radius: 8px;
    }
""" % (PANEL_BG, PANEL_BORDER)

BTN_BASE = """
    QPushButton {
        background: transparent;
        border: 1px solid %s;
        border-radius: 4px;
        color: %s;
        font-family: "Menlo", "Consolas", monospace;
        padding: 6px 14px;
    }
    QPushButton:hover {
        background: #1e1e2e;
        border-color: %s;
    }
    QPushButton:pressed {
        background: #252535;
    }
    QPushButton:disabled {
        border-color: %s;
        color: %s;
    }
""" % (PANEL_BORDER, TEXT_SECONDARY, ACCENT, TEXT_MUTED, TEXT_MUTED)

TOPBAR_STYLE = f"""
    background: {TOPBAR_BG};
    border-bottom: 1px solid {PANEL_BORDER};
"""

STATUS_BAR_STYLE = f"""
    background: {TOPBAR_BG};
    border-top: 1px solid {PANEL_BORDER};
"""

NO_SELECT_SCROLL = """
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
        border: none;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 4px;
    }
    QScrollBar::handle:vertical {
        background: %s;
        border-radius: 2px;
        min-height: 30px;
    }
""" % PANEL_BORDER

MUTE_BTN_STYLE = """
    QPushButton {
        background: transparent;
        border: 1px solid %s;
        border-radius: 3px;
        color: %s;
        font-family: "Menlo", "Consolas", monospace;
        font-size: 10px;
        padding: 3px 8px;
    }
    QPushButton:hover {
        background: #1e1e2e;
    }
"""

ACTIVE_SOURCE_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 4px;
        color: %s;
        font-family: "Helvetica Neue", "Menlo", sans-serif;
        font-size: 12px;
        padding: 6px 12px;
        text-align: left;
    }
    QPushButton:hover {
        background: rgba(0, 229, 160, 0.08);
    }
""" % TEXT_PRIMARY

INACTIVE_SOURCE_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 4px;
        color: %s;
        font-family: "Helvetica Neue", "Menlo", sans-serif;
        font-size: 12px;
        padding: 6px 12px;
        text-align: left;
    }
""" % TEXT_MUTED


# ══════════════════════════════════════════════════════════════════════════════
# Helper: internet ping checker
# ══════════════════════════════════════════════════════════════════════════════

class _InternetChecker(QObject):
    internet_changed = Signal(bool)  # True = online, False = offline

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._thread: threading.Thread | None = None
        self._online = True
        self._last_checked = False
        self._interval = 15.0  # seconds

    def _get_active_interface_info(self) -> tuple[str, str]:
        """Returns (interface_name, wifi_ssid_or_empty)."""
        system = platform.system()
        try:
            if system == "Darwin":
                result = os.popen(
                    "route get 8.8.8.8 2>/dev/null | "
                    "grep 'interface:' | awk '{print $2}'"
                ).read().strip()
                if not result:
                    return ("Unknown", "")
                ssid_result = os.popen(
                    f"/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null | "
                    "grep ' SSID' | sed 's/.*: //'"
                ).read().strip()
                return (result, ssid_result)
            elif system == "Linux":
                dest = socket.gethostbyname("8.8.8.8")
                with open("/proc/net/route") as f:
                    for line in f:
                        fields = line.strip().split()
                        if len(fields) >= 8 and fields[1] == "00000000":
                            iface = fields[0]
                            ssid = ""
                            return (iface, ssid)
                return ("Unknown", "")
            elif system == "Windows":
                import subprocess
                result = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
                     "Select-Object -First 1 -ExpandProperty InterfaceAlias)"],
                    capture_output=True, text=True, timeout=5
                )
                iface = result.stdout.strip() or "Unknown"
                return (iface, "")
        except Exception:
            pass
        return ("Unknown", "")

    def _check_once(self) -> bool:
        system = platform.system()
        try:
            if system == "Windows":
                import subprocess
                r = subprocess.run(
                    ["ping", "-n", "1", "-w", "1000", "8.8.8.8"],
                    capture_output=True, timeout=3
                )
                return r.returncode == 0
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect(("8.8.8.8", 53))
                sock.close()
                return True
        except Exception:
            return False

    def _worker(self):
        while self._running:
            online = self._check_once()
            if online != self._last_checked:
                self._last_checked = online
                self.internet_changed.emit(online)
            threading.Event().wait(self._interval)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def current_status(self) -> tuple[bool, str, str]:
        """Returns (is_online, interface_name, ssid_or_empty)."""
        online = self._check_once()
        iface, ssid = self._get_active_interface_info()
        return online, iface, ssid


# ══════════════════════════════════════════════════════════════════════════════
# Circular gauge widget
# ══════════════════════════════════════════════════════════════════════════════

class _CircularGauge(QWidget):
    """A small circular arc gauge for CPU/Memory."""
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._max = 100.0
        self._label = label
        self._color = ACCENT
        self.setFixedSize(110, 110)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_value(self, value: float, color: str = ACCENT):
        self._value = min(value, self._max)
        self._color = color
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 10

        bg_path = QPainterPath()
        bg_path.arcMoveTo(cx - r, cy - r, r * 2, r * 2, 135)
        bg_path.arcTo(cx - r, cy - r, r * 2, r * 2, 270, -270)
        bg_pen = QPen(QColor(TEXT_MUTED))
        bg_pen.setWidthF(6)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawPath(bg_path)

        sweep = 270 * (self._value / self._max)
        fg_path = QPainterPath()
        fg_path.arcMoveTo(cx - r, cy - r, r * 2, r * 2, 135)
        fg_path.arcTo(cx - r, cy - r, r * 2, r * 2, 270, -sweep)
        fg_pen = QPen(QColor(self._color))
        fg_pen.setWidthF(6)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)
        painter.drawPath(fg_path)

        val_font = QFont("Menlo", 14, QFont.Weight.Bold)
        painter.setFont(val_font)
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            QRectF(0, cy - 14, w, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{self._value:.0f}%"
        )

        lbl_font = QFont("Menlo", 8)
        painter.setFont(lbl_font)
        painter.setPen(QColor(TEXT_SECONDARY))
        painter.drawText(
            QRectF(0, cy + 6, w, 12),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._label
        )


# ══════════════════════════════════════════════════════════════════════════════
# Audio visualizer widget (vertical bars)
# ══════════════════════════════════════════════════════════════════════════════

class _AudioVisualizer(QWidget):
    """Vertical bar audio visualizer using volume level from OBS."""
    def __init__(self, bars: int = 20, parent=None):
        super().__init__(parent)
        self._bars = bars
        self._levels = [0.0] * bars
        self._target = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(50)
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_level(self, volume: float):
        self._target = max(0.0, min(1.0, volume))

    def _animate(self):
        changed = False
        for i in range(self._bars):
            target = self._target * (0.4 + 0.6 * ((self._bars - i) / self._bars))
            diff = target - self._levels[i]
            self._levels[i] += diff * 0.25
            if abs(diff) > 0.005:
                changed = True
        if changed:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        n = self._bars
        bar_w = max(2, (w - (n - 1) * 2) // n)
        gap = (w - bar_w * n) // (n - 1) if n > 1 else 2

        for i in range(n):
            level = self._levels[i]
            color_val = int(255 * level)
            if level > 0.8:
                color = QColor(LIVE_RED)
            elif level > 0.5:
                color = QColor(WARN_ORANGE)
            else:
                color = QColor(ACCENT)
            color.setAlpha(200)

            bar_h = max(2, int(self.height() * level))
            x = i * (bar_w + gap)
            y = self.height() - bar_h
            painter.fillRect(QRect(x, y, bar_w, bar_h), color)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# ON AIR glowing icon
# ══════════════════════════════════════════════════════════════════════════════

class _OnAirIcon(QWidget):
    """A pulsing red circle with a drop shadow — ON AIR indicator."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._glow = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(600)

    def _pulse(self):
        self._glow = 0.55 + 0.45 * abs(math.sin(
            self._timer.interval() * 0.001 * (time.time() % (2 * math.pi))
        ))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2, self.height() / 2
        r = 10

        glow_color = QColor(LIVE_RED)
        glow_color.setAlpha(int(80 * self._glow))
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(4, 0, -1):
            glow = QColor(LIVE_RED)
            glow.setAlpha(int(20 * self._glow * (5 - i) / 4))
            painter.setBrush(glow)
            painter.drawEllipse(
                QRectF(cx - r - i * 2, cy - r - i * 2, (r + i * 2) * 2, (r + i * 2) * 2)
            )

        painter.setBrush(QColor(LIVE_RED))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        inner = QColor("#ff8090")
        inner.setAlpha(180)
        painter.setBrush(inner)
        painter.drawEllipse(QRectF(cx - r + 2, cy - r + 2, r * 2 - 4, r * 2 - 4))

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# Main dashboard
# ══════════════════════════════════════════════════════════════════════════════

class OBSDashboard(QWidget):
    obs_event = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._client: OBSClient | None = None
        self._state: OBSState | None = None
        self._config = config
        self._touch_locked = False
        self._source_buttons: dict = {}
        self._internet = _InternetChecker(self)
        self._internet.internet_changed.connect(self._on_internet_changed)
        self._internet.start()
        self._setup_ui()
        self._start_timers()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"background: {BG};")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Thin Top Bar ─────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(56)
        topbar.setStyleSheet(TOPBAR_STYLE)
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(16, 0, 16, 0)
        tb_lay.setSpacing(16)

        # Left: OBS logo
        self._obs_logo = QLabel("OBS")
        self._obs_logo.setFont(QFont("Menlo", 22, QFont.Weight.Bold))
        self._obs_logo.setStyleSheet(
            f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
        )
        tb_lay.addWidget(self._obs_logo)

        # Weather info (between logo and clock)
        self._weather_lbl = QLabel("—")
        self._weather_lbl.setFont(QFont("Menlo", 10))
        self._weather_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
        )
        tb_lay.addWidget(self._weather_lbl)

        tb_lay.addStretch()

        # Right: local date and time
        self._clock_lbl = QLabel("")
        self._clock_lbl.setFont(QFont("Menlo", 10))
        self._clock_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
        )
        tb_lay.addWidget(self._clock_lbl)

        root.addWidget(topbar)

        # ── Main content grid ─────────────────────────────────────────────────
        self._main_grid = QGridLayout()
        self._main_grid.setContentsMargins(16, 16, 16, 16)
        self._main_grid.setSpacing(16)
        self._main_grid.setRowStretch(0, 1)
        self._main_grid.setRowStretch(1, 1)
        self._main_grid.setColumnStretch(0, 1)  # stream block
        self._main_grid.setColumnStretch(1, 1)  # cpumem
        self._main_grid.setColumnStretch(2, 1)  # bitrate
        self._main_grid.setColumnStretch(3, 1)  # empty top-right

        # Row 0 — top blocks
        self._stream_block = self._make_stream_block()
        self._main_grid.addWidget(self._stream_block, 0, 0)

        self._cpumem_block = self._make_cpumem_block()
        self._main_grid.addWidget(self._cpumem_block, 0, 1)

        self._bitrate_block = self._make_bitrate_block()
        self._main_grid.addWidget(self._bitrate_block, 0, 2)

        self._empty_top_block = self._make_empty_block()
        self._main_grid.addWidget(self._empty_top_block, 0, 3)

        # Row 1 — bottom blocks
        self._source_block = self._make_source_block()
        self._main_grid.addWidget(self._source_block, 1, 0)

        # Cols 1-3: empty center+right bottom
        self._empty_bottom_block = self._make_empty_block()
        self._main_grid.addWidget(self._empty_bottom_block, 1, 1, 1, 3)

        root.addLayout(self._main_grid)

        # ── Bottom Thin Bar ──────────────────────────────────────────────────
        statusbar = QWidget()
        statusbar.setFixedHeight(56)
        statusbar.setStyleSheet(STATUS_BAR_STYLE)
        sb_lay = QHBoxLayout(statusbar)
        sb_lay.setContentsMargins(16, 0, 16, 0)
        sb_lay.setSpacing(12)

        # Left: wifi icon + interface name
        self._wifi_icon = QLabel("Wifi")
        self._wifi_icon.setFont(QFont("Menlo", 10))
        self._wifi_icon.setStyleSheet(
            f"color: {ACCENT}; background: transparent; border: none; padding: 0;"
        )
        sb_lay.addWidget(self._wifi_icon)

        self._net_iface_lbl = QLabel("—")
        self._net_iface_lbl.setFont(QFont("Menlo", 9))
        self._net_iface_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
        )
        sb_lay.addWidget(self._net_iface_lbl)

        sb_lay.addStretch()

        # Audio visualizer (center-right of bottom bar)
        self._audio_viz = _AudioVisualizer(bars=16)
        self._audio_viz.setFixedWidth(200)
        sb_lay.addWidget(self._audio_viz)

        # Master mute button
        self._master_mute_btn = QPushButton("MUTE")
        self._master_mute_btn.setFont(QFont("Menlo", 10, QFont.Weight.Bold))
        self._master_mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._master_mute_btn.setStyleSheet(
            MUTE_BTN_STYLE % (LIVE_RED, LIVE_RED)
        )
        self._master_mute_btn.clicked.connect(self._on_master_mute)
        sb_lay.addWidget(self._master_mute_btn)

        # Padlock lock button
        self._lock_btn = QPushButton()
        self._lock_btn.setFixedWidth(40)
        self._lock_btn.setFont(QFont("Menlo", 14))
        self._lock_btn.setStyleSheet(
            f"background: transparent; border: 1px solid {PANEL_BORDER}; "
            f"border-radius: 4px; color: {TEXT_SECONDARY}; padding: 0;"
        )
        self._lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lock_btn.clicked.connect(self._on_lock_toggle)
        self._update_lock_icon()
        sb_lay.addWidget(self._lock_btn)

        # IP addr + port
        self._conn_info_lbl = QLabel("—")
        self._conn_info_lbl.setFont(QFont("Menlo", 9))
        self._conn_info_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
        )
        sb_lay.addWidget(self._conn_info_lbl)

        root.addWidget(statusbar)

        # Install event filter for touch lock
        self.installEventFilter(self)

    def eventFilter(self, obj, event: QEvent) -> bool:
        if self._touch_locked:
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.TouchBegin,
                QEvent.Type.TouchUpdate,
                QEvent.Type.TouchEnd,
            ):
                logger.debug("[OBSDashboard] Touch locked — event blocked")
                return True
        return super().eventFilter(obj, event)

    # ── Block factories ───────────────────────────────────────────────────────

    def _make_frame(self) -> QFrame:
        f = QFrame()
        f.setObjectName("panel")
        f.setStyleSheet(PANEL_H)
        return f

    def _make_stream_block(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 16, 12, 16)
        lay.setSpacing(8)

        # ON AIR row: icon + text
        onair_row = QHBoxLayout()
        onair_row.addStretch()
        self._onair_icon = _OnAirIcon()
        self._onair_icon.hide()
        onair_row.addWidget(self._onair_icon)
        self._onair_lbl = QLabel("ON AIR")
        self._onair_lbl.setFont(QFont("Menlo", 28, QFont.Weight.Bold))
        self._onair_lbl.setStyleSheet(
            f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
        )
        onair_row.addWidget(self._onair_lbl)
        onair_row.addStretch()
        onair_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(onair_row)

        # STOPPED row: gray circle + text
        stopped_row = QHBoxLayout()
        stopped_row.addStretch()
        stopped_circle = QLabel()
        stopped_circle.setFixedSize(32, 32)
        stopped_circle.setStyleSheet(
            "background: transparent; border: none; border-radius: 16px; "
            "background-color: #3a3a52;"
        )
        self._stopped_circle = stopped_circle
        stopped_row.addWidget(stopped_circle)
        self._stopped_lbl = QLabel("STOPPED")
        self._stopped_lbl.setFont(QFont("Menlo", 28, QFont.Weight.Bold))
        self._stopped_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none; padding: 0;"
        )
        stopped_row.addWidget(self._stopped_lbl)
        stopped_row.addStretch()
        stopped_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(stopped_row)

        # Timestamp
        self._stream_time_lbl = QLabel("00:00:00")
        self._stream_time_lbl.setFont(QFont("Menlo", 16))
        self._stream_time_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._stream_time_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none; padding: 0;"
        )
        lay.addWidget(self._stream_time_lbl)

        lay.addStretch()

        # Clickable overlay
        self._stream_block_click = QLabel()
        self._stream_block_click.setStyleSheet("background: transparent;")
        self._stream_block_click.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stream_block_click.mousePressEvent = lambda e: self._on_stream_toggle()
        lay.addWidget(self._stream_block_click, 1)

        w.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 8px;")
        return w

    def _make_cpumem_block(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(8)

        self._cpu_gauge = _CircularGauge("CPU")
        lay.addWidget(self._cpu_gauge)

        self._mem_gauge = _CircularGauge("MEM", self)
        self._mem_gauge.set_value(0)
        lay.addWidget(self._mem_gauge)

        w.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 8px;")
        return w

    def _make_bitrate_block(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        self._bitrate_val_lbl = QLabel("—")
        self._bitrate_val_lbl.setFont(QFont("Menlo", 28, QFont.Weight.Bold))
        self._bitrate_val_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._bitrate_val_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; background: transparent; border: none; padding: 0;"
        )
        lay.addWidget(self._bitrate_val_lbl)

        self._bitrate_unit_lbl = QLabel("kbps")
        self._bitrate_unit_lbl.setFont(QFont("Menlo", 10))
        self._bitrate_unit_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._bitrate_unit_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
        )
        lay.addWidget(self._bitrate_unit_lbl)

        self._bitrate_setting_lbl = QLabel("—")
        self._bitrate_setting_lbl.setFont(QFont("Menlo", 9))
        self._bitrate_setting_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._bitrate_setting_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none; padding: 0;"
        )
        lay.addWidget(self._bitrate_setting_lbl)

        w.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 8px;")
        return w

    def _make_source_block(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        lbl = QLabel("Sources")
        lbl.setFont(QFont("Menlo", 10, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;")
        hdr.addWidget(lbl)
        hdr.addStretch()

        self._hide_all_btn = QPushButton("Hide All")
        self._hide_all_btn.setFont(QFont("Menlo", 9))
        self._hide_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hide_all_btn.setStyleSheet(
            MUTE_BTN_STYLE % (PANEL_BORDER, TEXT_SECONDARY)
        )
        self._hide_all_btn.clicked.connect(self._on_hide_all_sources)
        hdr.addWidget(self._hide_all_btn)
        lay.addLayout(hdr)

        # Scroll area for source list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(NO_SELECT_SCROLL)
        self._source_scroll_content = QWidget()
        self._source_scroll_content.setStyleSheet("background: transparent;")
        self._source_scroll_lay = QVBoxLayout(self._source_scroll_content)
        self._source_scroll_lay.setContentsMargins(0, 0, 0, 0)
        self._source_scroll_lay.setSpacing(4)
        self._source_scroll_lay.addStretch()
        scroll.setWidget(self._source_scroll_content)
        lay.addWidget(scroll, 1)

        w.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 8px;")
        return w

    def _make_empty_block(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 8px;")
        return w

    # ── Timers ────────────────────────────────────────────────────────────────

    def _start_timers(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(self._update_internet_display)
        self._net_timer.start(15000)
        self._update_internet_display()

    def _update_clock(self):
        now = datetime.now()
        date_str = now.strftime("%a %b %d %Y")
        time_str = now.strftime("%I:%M:%S %p")
        self._clock_lbl.setText(f"{date_str}  {time_str}")

    def _update_internet_display(self):
        online, iface, ssid = self._internet.current_status()
        self._on_internet_changed(online)
        if online:
            self._wifi_icon.setStyleSheet(
                f"color: {ACCENT}; background: transparent; border: none; padding: 0;"
            )
            self._wifi_icon.setText("Wifi")
            if ssid:
                self._net_iface_lbl.setText(f"{iface} ({ssid})")
            else:
                self._net_iface_lbl.setText(iface)
        else:
            self._wifi_icon.setStyleSheet(
                f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
            )
            self._wifi_icon.setText("Wifi")
            self._net_iface_lbl.setText("Internet Disconnected")

    @Slot(bool)
    def _on_internet_changed(self, online: bool):
        if online:
            self._wifi_icon.setStyleSheet(
                f"color: {ACCENT}; background: transparent; border: none; padding: 0;"
            )
            self._wifi_icon.setText("Wifi")
            self._net_iface_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent; border: none; padding: 0;"
            )
        else:
            self._wifi_icon.setStyleSheet(
                f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
            )
            self._wifi_icon.setText("Wifi")
            self._net_iface_lbl.setText("Internet Disconnected")
            self._net_iface_lbl.setStyleSheet(
                f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
            )

    # ── Binding ──────────────────────────────────────────────────────────────

    def bind(self, client: OBSClient, state: OBSState):
        self._client = client
        self._state = client._state
        self._refresh_all()
        conn = f"{client.host}:{client.port}"
        self._conn_info_lbl.setText(conn)
        self._conn_info_lbl.setToolTip(f"Connected to {conn}")

    def unbind(self):
        self._client = None
        self._state = None
        self._conn_info_lbl.setText("—")
        self._onair_lbl.hide()
        self._stopped_lbl.show()
        self._stream_time_lbl.setText("00:00:00")
        self._stream_time_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none; padding: 0;"
        )
        self._bitrate_val_lbl.setText("—")
        self._bitrate_setting_lbl.setText("—")
        self._cpu_gauge.set_value(0)
        self._mem_gauge.set_value(0)
        self._audio_viz.set_level(0)
        self._clear_sources()

    def apply_config(self, config: dict):
        self._config = config

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh_all(self):
        if not self._state:
            return
        self._refresh_stream_status()
        self._refresh_stats()
        self._refresh_sources()
        self._refresh_audio()

    # ── OBS event handler ─────────────────────────────────────────────────────

    @Slot(str)
    def on_obs_event(self, event_name: str):
        if not self._state:
            return
        if event_name in (
            "SceneListChanged", "CurrentProgramSceneChanged",
            "CurrentPreviewSceneChanged", "StreamStateChanged",
            "RecordingStateChanged", "InputVolumeChanged",
            "InputMuteStateChanged", "PeriodicSync",
            "SceneItemEnableStateChanged",
        ):
            self._refresh_all()

    def _refresh_stream_status(self):
        streaming = self._state.streaming
        self._onair_icon.setVisible(streaming)
        self._onair_lbl.setVisible(streaming)
        self._stopped_circle.setVisible(not streaming)
        self._stopped_lbl.setVisible(not streaming)

        tc = self._state.stats.stream_timecode or "00:00:00"
        self._stream_time_lbl.setText(tc)
        if streaming:
            self._stream_time_lbl.setStyleSheet(
                f"color: {LIVE_RED}; background: transparent; border: none; padding: 0;"
            )
        else:
            self._stream_time_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; background: transparent; border: none; padding: 0;"
            )

    def _refresh_stats(self):
        if not self._state:
            return
        s = self._state.stats

        cpu = min(s.cpu_usage, 100)
        cpu_color = LIVE_RED if cpu > 80 else (WARN_ORANGE if cpu > 60 else ACCENT)
        self._cpu_gauge.set_value(cpu, cpu_color)

        mem_mb = s.memory_usage
        mem_pct = min(mem_mb / 8192 * 100, 100)  # rough estimate vs 8GB
        mem_color = LIVE_RED if mem_pct > 90 else (WARN_ORANGE if mem_pct > 75 else ACCENT)
        self._mem_gauge.set_value(mem_pct, mem_color)

        bitrate_kbps = s.network_bitrate / 1000
        if bitrate_kbps > 0:
            self._bitrate_val_lbl.setText(f"{bitrate_kbps:.0f}")
        else:
            self._bitrate_val_lbl.setText("—")

    def _refresh_sources(self):
        if not self._state:
            return
        inputs = list(self._state.inputs.values())
        self._update_source_list(inputs)

    def _update_source_list(self, inputs: list):
        """Rebuild the source button list preserving scroll position."""
        lay = self._source_scroll_lay
        insert_at = lay.count() - 1

        names = {inp.input_name for inp in inputs}
        existing = self._source_buttons or {}

        for inp in inputs:
            name = inp.input_name
            is_active = not inp.muted
            if name in existing:
                btn = existing[name]
                btn.setText(name)
                btn.setStyleSheet(
                    ACTIVE_SOURCE_STYLE if is_active else INACTIVE_SOURCE_STYLE
                )
            else:
                btn = QPushButton(name)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    ACTIVE_SOURCE_STYLE if is_active else INACTIVE_SOURCE_STYLE
                )
                captured_name = name
                btn.clicked.connect(
                    lambda checked, n=captured_name: self._on_source_toggle(n)
                )
                self._source_buttons[name] = btn
                lay.insertWidget(insert_at, btn)

        for name in list(existing.keys()):
            if name not in names:
                self._source_buttons.pop(name).deleteLater()

    def _clear_sources(self):
        if self._source_buttons:
            for btn in list(self._source_buttons.values()):
                btn.deleteLater()
            self._source_buttons.clear()

    def _refresh_audio(self):
        if not self._state:
            return
        inputs = list(self._state.inputs.values())
        audio_inputs = [
            i for i in inputs
            if i.input_kind not in ("filter",)
        ]
        if audio_inputs:
            avg_vol = sum(i.volume for i in audio_inputs) / len(audio_inputs)
            self._audio_viz.set_level(avg_vol)
        else:
            self._audio_viz.set_level(0)

    # ── Actions ──────────────────────────────────────────────────────────────

    @qasync.asyncSlot()
    async def _on_stream_toggle(self):
        logger.info("[OBSDashboard] User pressed: Stream block toggle")
        if self._client:
            await self._client.toggle_stream()

    def _on_source_toggle(self, name: str):
        logger.info("[OBSDashboard] User toggled source: %s", name)
        if self._client:
            qasync.QMetaObject.invokeMethod(self, "_do_source_toggle_async", Qt.QueuedConnection, name=name)

    @qasync.asyncSlot(str)
    async def _do_source_toggle_async(self, name: str):
        if self._client and name in self._client._state.inputs:
            await self._client.toggle_input_mute(name)

    def _on_hide_all_sources(self):
        logger.info("[OBSDashboard] User pressed: Hide All sources")
        if self._client:
            for name in list(self._client._state.inputs.keys()):
                qasync.QMetaObject.invokeMethod(self, "_do_source_toggle_async", Qt.QueuedConnection, name=name)

    def _on_master_mute(self):
        logger.info("[OBSDashboard] User pressed: Master Mute")
        if self._client:
            inputs = list(self._client._state.inputs.values())
            all_muted = all(i.muted for i in inputs)
            for name in list(self._client._state.inputs.keys()):
                inp = self._client._state.inputs.get(name)
                if inp:
                    was_muted = inp.muted
                    if all_muted or was_muted:
                        qasync.QMetaObject.invokeMethod(self, "_do_source_toggle_async", Qt.QueuedConnection, name=name)

    def _on_lock_toggle(self):
        self._touch_locked = not self._touch_locked
        if self._touch_locked:
            self._lock_btn.setText("Unlock")
            self._lock_btn.setStyleSheet(
                MUTE_BTN_STYLE % (LIVE_RED, LIVE_RED)
            )
            self.setStyleSheet(
                f"background: {BG};"
                "QWidget:focus { border: 2px solid %s; }"
                "" % LIVE_RED
            )
        else:
            self._lock_btn.setText("Lock")
            self._lock_btn.setStyleSheet(
                MUTE_BTN_STYLE % (PANEL_BORDER, TEXT_SECONDARY)
            )
            self.setStyleSheet(f"background: {BG};")
