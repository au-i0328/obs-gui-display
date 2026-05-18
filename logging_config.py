import logging
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".obs-pygui" / "logs"
LOG_FILE = LOG_DIR / "obs-pygui.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_INTERVAL_SEC = 1


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        LOG_FILE, encoding="utf-8", mode="a"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    root_logger.addHandler(file_handler)

    root_logger.info("Logging initialised — file: %s", LOG_FILE)
    return root_logger


def get_obs_state_snapshot(state) -> dict:
    """Return a serialisable dict snapshot of OBSState for logging."""
    if state is None:
        return {"_note": "No state available"}
    stats = state.stats
    return {
        "program_scene": state.current_program_scene,
        "preview_scene": state.current_preview_scene,
        "streaming": state.streaming,
        "recording": state.recording,
        "num_scenes": len(state.scenes),
        "num_inputs": len(state.inputs),
        "fps": round(stats.fps, 1),
        "cpu_usage": round(stats.cpu_usage, 1),
        "memory_mb": round(stats.memory_usage, 1),
        "bitrate_kbps": round(stats.network_bitrate / 1000.0, 1) if stats.network_bitrate else 0.0,
        "dropped_frames": stats.num_dropped_frames,
        "stream_time": stats.stream_timecode,
        "recording_time": stats.recording_timecode,
        "input_volumes": {
            name: round(inp.volume * 100, 1)
            for name, inp in list(state.inputs.items())[:10]
        },
        "media_inputs": list(state.media_inputs.keys()),
    }
