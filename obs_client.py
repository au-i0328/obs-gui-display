import asyncio
import logging
import threading
from typing import Callable, Optional

import obswebsocket
import obswebsocket.baseRequests
import obswebsocket.exceptions

from obs_data import OBSInput, OBSScene, OBSState, OBSStats

logger = logging.getLogger(__name__)


class OBSClient:
    def __init__(self, url: str, password: Optional[str] = None):
        self.url = url
        self.password = password
        self._ws: Optional[obswebsocket.WebSocket] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._state = OBSState()
        self._state_lock = asyncio.Lock()
        self._connected = False
        self._reconnect = True
        self._callbacks: list[Callable[[str, dict], None]] = []
        self._exc_info: Optional[Exception] = None

    async def connect(self, timeout: float = 10.0) -> bool:
        self._loop = asyncio.get_running_loop()
        try:
            self._ws = obswebsocket.WebSocket()
            self._ws.connect(self.url, password=self.password, timeout=timeout)
            self._connected = True
            await self._sync_state()
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            self._exc_info = e
            self._connected = False
            raise

    def _listen_loop(self):
        while self._connected and self._ws is not None:
            try:
                msg = self._ws.poll()
                if msg is None:
                    break
            except Exception:
                break

        if self._connected:
            self._connected = False
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._on_disconnect)

    def _on_disconnect(self):
        for cb in self._callbacks:
            try:
                cb("disconnected", {})
            except Exception:
                pass

    async def _sync_state(self):
        if self._ws is None:
            return
        try:
            scene_list_resp = self._ws.call("GetSceneList")
            self._state.scenes = [s["sceneName"] for s in scene_list_resp.scenes]
            self._state.current_program_scene = scene_list_resp.currentProgramSceneName or ""
            self._state.current_preview_scene = scene_list_resp.currentPreviewSceneName or ""

            for s in (scene_list_resp.scenes or []):
                scene_name = s["sceneName"]
                scene_resp = self._ws.call("GetSceneItemList", sceneName=scene_name)
                for item in (scene_resp.sceneItems or []):
                    src_name = item.get("sourceName", "")
                    src_kind = item.get("sourceType", "")
                    if src_kind == "input":
                        self._state.inputs.setdefault(
                            src_name,
                            OBSInput(input_name=src_name, input_kind="input"),
                        )
                    elif src_kind == "filter":
                        pass
                    elif src_kind:
                        self._state.inputs.setdefault(
                            src_name,
                            OBSInput(input_name=src_name, input_kind=src_kind),
                        )
        except Exception:
            pass

        try:
            stats_resp = self._ws.call("GetStats")
            self._state.stats = OBSStats(
                fps=float(getattr(stats_resp, "fps", 0.0)),
                cpu_usage=float(getattr(stats_resp, "cpuUsage", 0.0)),
                memory_usage=float(getattr(stats_resp, "memoryUsage", 0.0)),
                network_bitrate=float(getattr(stats_resp, "bandwidth", 0.0)),
                stream_timecode=getattr(stats_resp, "streamTimecode", "00:00:00") or "00:00:00",
                recording_timecode=getattr(stats_resp, "recordingTimecode", "00:00:00") or "00:00:00",
                num_dropped_frames=getattr(stats_resp, "droppedFrames", 0),
                num_total_frames=getattr(stats_resp, "totalFrames", 0),
                fps_avg=float(getattr(stats_resp, "fps", 0.0)),
                cpu_avg=float(getattr(stats_resp, "cpuUsage", 0.0)),
            )
        except Exception:
            pass

        try:
            for inp_name in list(self._state.inputs.keys()):
                try:
                    inp_resp = self._ws.call("GetInputSettings", inputName=inp_name)
                    vol = inp_resp.inputVolume or 0.0
                    muted = bool(getattr(inp_resp, "inputMuted", False))
                    inp = self._state.inputs[inp_name]
                    inp.volume = vol
                    inp.muted = muted
                    kind = getattr(inp_resp, "inputKind", inp.input_kind or "")
                    inp.is_media = kind in ("ffmpeg_source", "vlc_source", "mediacapture")
                except Exception:
                    pass
        except Exception:
            pass

    async def get_state(self) -> OBSState:
        return self._state

    async def disconnect(self):
        self._connected = False
        self._reconnect = False
        if self._ws is not None:
            try:
                self._ws.disconnect()
            except Exception:
                pass
            self._ws = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_connected(self) -> bool:
        return self._connected

    def on_event(self, callback: Callable[[str, dict], None]):
        self._callbacks.append(callback)

    async def switch_scene(self, scene_name: str):
        if self._ws:
            try:
                self._ws.call("SetCurrentProgramScene", sceneName=scene_name)
            except Exception as e:
                raise RuntimeError(f"Failed to switch scene: {e}") from e

    async def toggle_stream(self):
        if self._ws:
            try:
                if self._state.streaming:
                    self._ws.call("StopStream")
                else:
                    self._ws.call("StartStream")
            except Exception as e:
                raise RuntimeError(f"Failed to toggle stream: {e}") from e

    async def toggle_recording(self):
        if self._ws:
            try:
                if self._state.recording:
                    self._ws.call("StopRecording")
                else:
                    self._ws.call("StartRecording")
            except Exception as e:
                raise RuntimeError(f"Failed to toggle recording: {e}") from e

    async def set_input_volume(self, input_name: str, volume: float):
        if self._ws:
            try:
                self._ws.call("SetInputVolume", inputName=input_name, inputVolume=volume)
            except Exception as e:
                raise RuntimeError(f"Failed to set input volume: {e}") from e

    async def toggle_input_mute(self, input_name: str):
        if self._ws:
            try:
                self._ws.call("ToggleInputMute", inputName=input_name)
            except Exception as e:
                raise RuntimeError(f"Failed to toggle mute: {e}") from e

    async def trigger_media_action(self, input_name: str, action: str):
        if self._ws:
            try:
                self._ws.call("TriggerMediaInputAction", inputName=input_name, mediaAction=action)
            except Exception as e:
                raise RuntimeError(f"Failed to trigger media action: {e}") from e

    async def refresh_media(self, input_name: str):
        if self._ws:
            try:
                self._ws.call("TriggerMediaInputAction", inputName=input_name, mediaAction="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
            except Exception as e:
                raise RuntimeError(f"Failed to refresh media: {e}") from e

    async def set_current_preview_scene(self, scene_name: str):
        if self._ws:
            try:
                self._ws.call("SetCurrentPreviewScene", sceneName=scene_name)
            except Exception:
                pass

    def handle_event(self, event_name: str, event_data: dict):
        if event_name in ("ExitStarted", "Identified"):
            return
        if event_name == "SceneListChanged":
            self._state.scenes = [s.get("sceneName", "") for s in event_data.get("scenes", [])]
        elif event_name == "CurrentProgramSceneChanged":
            self._state.current_program_scene = event_data.get("sceneName", "")
        elif event_name == "CurrentPreviewSceneChanged":
            self._state.current_preview_scene = event_data.get("sceneName", "")
        elif event_name in ("StreamStateChanged",):
            self._state.streaming = event_data.get("outputState", "") == "OBS_WEBSOCKET_OUTPUT_STATE_STARTED"
        elif event_name in ("RecordingStateChanged",):
            self._state.recording = event_data.get("outputState", "") == "OBS_WEBSOCKET_OUTPUT_STATE_STARTED"
        elif event_name == "InputVolumeChanged":
            name = event_data.get("inputName", "")
            vol = float(event_data.get("inputVolumeMultiplier", 1.0))
            if name in self._state.inputs:
                self._state.inputs[name].volume = vol
        elif event_name == "InputMuteStateChanged":
            name = event_data.get("inputName", "")
            muted = bool(event_data.get("inputMuted", False))
            if name in self._state.inputs:
                self._state.inputs[name].muted = muted

        for cb in self._callbacks:
            try:
                cb(event_name, event_data)
            except Exception:
                pass
