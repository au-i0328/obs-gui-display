from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OBSInstance:
    host: str
    port: int
    obs_version: Optional[str] = None
    ws_version: Optional[str] = None
    instance_name: Optional[str] = None
    identified: bool = False

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def display_label(self) -> str:
        if self.instance_name:
            return f"{self.instance_name} ({self.address})"
        return self.address


@dataclass
class OBSStats:
    fps: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    network_bitrate: float = 0.0
    stream_timecode: str = "00:00:00"
    recording_timecode: str = "00:00:00"
    num_dropped_frames: int = 0
    num_total_frames: int = 0
    fps_avg: float = 0.0
    cpu_avg: float = 0.0


@dataclass
class OBSInput:
    input_name: str
    input_kind: str
    muted: bool = False
    volume: float = 0.0
    audio_levels_db: float = -96.0
    audio_levels_linear: float = 0.0
    monitor_type: Optional[str] = None
    is_media: bool = False


@dataclass
class OBSScene:
    scene_name: str
    sources: list[dict] = field(default_factory=list)


@dataclass
class OBSState:
    current_program_scene: str = ""
    current_preview_scene: str = ""
    streaming: bool = False
    recording: bool = False
    stream_paused: bool = False
    scenes: list[str] = field(default_factory=list)
    inputs: dict[str, OBSInput] = field(default_factory=dict)
    stats: OBSStats = field(default_factory=OBSStats)
    media_inputs: dict[str, str] = field(default_factory=dict)
