import asyncio
import logging
import queue
import threading
from typing import Callable, Optional

from obswebsocket.core import obsws
from obswebsocket import requests, events as obs_events

from obs_data import OBSInput, OBSState, OBSStats
from logging_config import LOG_INTERVAL_SEC, get_obs_state_snapshot

logger = logging.getLogger(__name__)


class OBSClient:
    def __init__(self, host: str, port: int, password: Optional[str] = None):
        self.host = host
        self.port = port
        self.password = password or ""
        self._ws: Optional[obsws] = None
        self._state = OBSState()
        self._connected = False
        self._callbacks: list[Callable[[str, dict], None]] = []
        self._periodic_task: Optional[asyncio.Task] = None

    @property
    def url(self) -> str:
        return f"{self.host}:{self.port}"

    async def connect(self, timeout: float = 10.0) -> bool:
        logger.info("[OBSClient] Connecting to %s:%s", self.host, self.port)
        self._ws = obsws(
            host=self.host,
            port=self.port,
            password=self.password,
            timeout=timeout,
            on_connect=self._on_ws_connect,
            on_disconnect=self._on_ws_disconnect,
        )
        try:
            self._ws.connect()
            self._connected = True

            self._sync_queue: queue.Queue = queue.Queue()
            self._sync_thread = threading.Thread(target=self._sync_thread_main, daemon=True)
            self._sync_thread.start()
            logger.info("[OBSClient] Sync thread started")

            self.enqueue_sync()  # initial full sync
            self._periodic_task = asyncio.create_task(self._periodic_state_refresh())
            logger.info("[OBSClient] Connected successfully to %s:%s", self.host, self.port)
            return True
        except Exception as e:
            logger.error("[OBSClient] Connection failed to %s:%s — %s", self.host, self.port, e)
            self._connected = False
            raise

    def _sync_thread_main(self):
        """Dedicated thread that runs _sync_state on a short timeout to avoid
        blocking the websocket receive loop."""
        while self._connected:
            try:
                item = self._sync_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:  # sentinel — stop signal
                break
            self._sync_timeout(self._ws, self._state, timeout=2.0)
            item.set()

    def _on_ws_connect(self, _ws):
        logger.info("[OBSClient] WebSocket connected at %s:%s", self.host, self.port)

        def on_event(event_obj):
            try:
                event_name = type(event_obj).__name__
            except Exception:
                event_name = str(event_obj)
            try:
                event_data = event_obj.datain.copy()
            except Exception:
                event_data = {}
            logger.debug(
                "[OBSClient] Raw OBS event received — name=%s data=%s",
                event_name, event_data
            )
            self.handle_event(event_name, event_data)

        self._ws.register(on_event, obs_events.ExitStarted)
        self._ws.register(on_event, obs_events.Identified)
        self._ws.register(on_event, obs_events.SceneListChanged)
        self._ws.register(on_event, obs_events.CurrentProgramSceneChanged)
        self._ws.register(on_event, obs_events.CurrentPreviewSceneChanged)
        self._ws.register(on_event, obs_events.StreamStateChanged)
        self._ws.register(on_event, obs_events.RecordingStateChanged)
        self._ws.register(on_event, obs_events.InputVolumeChanged)
        self._ws.register(on_event, obs_events.InputMuteStateChanged)
        self._ws.register(on_event, obs_events.StreamDeckServiceStatusChanged)
        self._ws.register(on_event, obs_events.SceneItemEnableStateChanged)

        logger.info(
            "[OBSClient] Registered handlers for events: ExitStarted, Identified, "
            "SceneListChanged, CurrentProgramSceneChanged, CurrentPreviewSceneChanged, "
            "StreamStateChanged, RecordingStateChanged, InputVolumeChanged, "
            "InputMuteStateChanged, StreamDeckServiceStatusChanged, SceneItemEnableStateChanged"
        )

    def _on_ws_disconnect(self, _ws):
        logger.warning("[OBSClient] WebSocket disconnected from %s:%s", self.host, self.port)
        self._connected = False
        for cb in self._callbacks:
            try:
                cb("disconnected", {})
            except Exception:
                pass

    def enqueue_sync(self):
        """Enqueue a full state sync to run on the sync thread (non-blocking)."""
        if hasattr(self, '_sync_queue') and self._connected:
            self._sync_queue.put(threading.Event())

    def enqueue_sync_and_wait(self):
        """Enqueue a full state sync and wait for it to complete (max ~2s)."""
        if not hasattr(self, '_sync_queue') or not self._connected:
            return
        evt = threading.Event()
        self._sync_queue.put(evt)
        evt.wait(timeout=3.0)

    def _sync_timeout(self, ws, state, timeout=2.0):
        """Run _sync_state with individual request timeouts so the websocket thread
        never gets blocked for long periods."""
        if ws is None:
            return
        logger.info("[OBSClient] Syncing full state from OBS")

        saved_timeout = ws.timeout
        ws.timeout = timeout

        try:
            resp = ws.call(requests.GetSceneList())
            scenes_raw = resp.datain.get('scenes', [])
            state.scenes = [s.get("sceneName", "") for s in scenes_raw]
            state.current_program_scene = resp.datain.get("currentProgramSceneName", "")
            state.current_preview_scene = resp.datain.get("currentPreviewSceneName", "")
            logger.info(
                "[OBSClient] State sync — GetSceneList: program=%s preview=%s scenes=%s",
                state.current_program_scene, state.current_preview_scene, state.scenes
            )
        except Exception as e:
            logger.warning("[OBSClient] Failed to sync scene list: %s", e)

        try:
            resp = ws.call(requests.GetStats())
            d = resp.datain
            state.stats = OBSStats(
                fps=float(d.get("fps", 0)),
                cpu_usage=float(d.get("cpuUsage", 0)),
                memory_usage=float(d.get("memoryUsage", 0)),
                network_bitrate=float(d.get("bandwidth", 0)),
                stream_timecode=d.get("streamTimecode", "00:00:00") or "00:00:00",
                recording_timecode=d.get("recordingTimecode", "00:00:00") or "00:00:00",
                num_dropped_frames=int(d.get("droppedFrames", 0)),
                num_total_frames=int(d.get("totalFrames", 0)),
            )
            logger.info(
                "[OBSClient] State sync — GetStats: fps=%.1f cpu=%.1f%% mem=%.1fMB "
                "bitrate=%.0f stream=%s recording=%s dropped=%d total=%d",
                state.stats.fps, state.stats.cpu_usage,
                state.stats.memory_usage, state.stats.network_bitrate,
                state.stats.stream_timecode, state.stats.recording_timecode,
                state.stats.num_dropped_frames, state.stats.num_total_frames
            )
        except Exception as e:
            logger.warning("[OBSClient] Failed to sync stats: %s", e)

        try:
            resp = ws.call(requests.GetInputList())
            inputs = resp.datain.get("inputs", [])
            for inp_info in inputs:
                name = inp_info.get("inputName", "")
                kind = inp_info.get("inputKind", "")
                inp = OBSInput(input_name=name, input_kind=kind)
                inp.is_media = kind in ("ffmpeg_source", "vlc_source", "mediacapture")
                try:
                    inp_resp = ws.call(requests.GetInputSettings(inputName=name))
                    inp.volume = float(inp_resp.datain.get("inputVolume", 0))
                    inp.muted = bool(inp_resp.datain.get("inputMuted", False))
                except Exception:
                    pass
                state.inputs[name] = inp
            logger.info(
                "[OBSClient] State sync — GetInputList: %d inputs (first 5: %s)",
                len(inputs), list(state.inputs.keys())[:5]
            )
        except Exception as e:
            logger.warning("[OBSClient] Failed to sync inputs: %s", e)

        ws.timeout = saved_timeout

    def _sync_state(self):
        if self._ws is None:
            return
        _sync_timeout(self._ws, self._state, timeout=2.0)

    async def _periodic_state_refresh(self):
        """
        Periodically re-syncs full state from OBS so that live values
        (CPU, memory, FPS, stream/recording timers, etc.) stay fresh.
        """
        logger.info("[OBSClient] Starting periodic state refresh (interval=%ds)", LOG_INTERVAL_SEC)
        while self._connected and self._ws is not None:
            await asyncio.sleep(LOG_INTERVAL_SEC)
            if not self._connected:
                break
            try:
                self.enqueue_sync_and_wait()
                self._fire_callbacks("PeriodicSync", {"snapshot": get_obs_state_snapshot(self._state)})
                snapshot = get_obs_state_snapshot(self._state)
                logger.info("[OBSClient] === PERIODIC STATE SNAPSHOT (every %ds) ===", LOG_INTERVAL_SEC)
                logger.info("[OBSClient]   program_scene   = %s", snapshot.get("program_scene"))
                logger.info("[OBSClient]   preview_scene  = %s", snapshot.get("preview_scene"))
                logger.info("[OBSClient]   streaming      = %s", snapshot.get("streaming"))
                logger.info("[OBSClient]   recording      = %s", snapshot.get("recording"))
                logger.info(
                    "[OBSClient]   stats          fps=%.1f cpu=%.1f%% mem=%.1fMB "
                    "bitrate=%.1fkbps dropped=%d stream=%s rec=%s",
                    snapshot.get("fps", 0), snapshot.get("cpu_usage", 0),
                    snapshot.get("memory_mb", 0), snapshot.get("bitrate_kbps", 0),
                    snapshot.get("dropped_frames", 0),
                    snapshot.get("stream_time", "—"),
                    snapshot.get("recording_time", "—")
                )
                logger.info(
                    "[OBSClient]   inputs         (%d total): %s",
                    snapshot.get("num_inputs", 0),
                    snapshot.get("input_volumes", {})
                )
                logger.info(
                    "[OBSClient]   media_inputs   = %s",
                    snapshot.get("media_inputs", [])
                )
                logger.info("[OBSClient]   num_scenes    = %s", snapshot.get("num_scenes"))
                logger.info("[OBSClient] =========================================")
            except Exception as e:
                logger.warning("[OBSClient] Periodic state refresh failed: %s", e)

    async def get_state(self) -> OBSState:
        return self._state

    async def disconnect(self):
        logger.info("[OBSClient] User initiated disconnect from %s:%s", self.host, self.port)
        self._connected = False
        if self._periodic_task:
            self._periodic_task.cancel()
            self._periodic_task = None
        if hasattr(self, '_sync_queue'):
            self._sync_queue.put(None)  # sentinel to stop sync thread
        if hasattr(self, '_ws') and self._ws is not None:
            try:
                self._ws.disconnect()
            except Exception:
                pass
            self._ws = None
        logger.info("[OBSClient] Disconnected from %s:%s", self.host, self.port)

    def is_connected(self) -> bool:
        return self._connected

    def on_event(self, callback: Callable[[str, dict], None]):
        self._callbacks.append(callback)

    def handle_event(self, event_name: str, event_data: dict):
        logger.info("[OBSClient] Processing event — name=%s data=%s", event_name, event_data)
        if event_name in ("ExitStarted", "Identified"):
            return
        if event_name == "SceneListChanged":
            self._state.scenes = [s.get("sceneName", "") for s in event_data.get("scenes", [])]
            logger.info("[OBSClient] Event SceneListChanged — updated scenes list: %s", self._state.scenes)
        elif event_name == "CurrentProgramSceneChanged":
            self._state.current_program_scene = event_data.get("sceneName", "")
            logger.info("[OBSClient] Event CurrentProgramSceneChanged — program_scene=%s", self._state.current_program_scene)
        elif event_name == "CurrentPreviewSceneChanged":
            self._state.current_preview_scene = event_data.get("sceneName", "")
            logger.info("[OBSClient] Event CurrentPreviewSceneChanged — preview_scene=%s", self._state.current_preview_scene)
        elif event_name == "StreamStateChanged":
            state = event_data.get("outputState", "")
            self._state.streaming = state == "OBS_WEBSOCKET_OUTPUT_STATE_STARTED"
            logger.info("[OBSClient] Event StreamStateChanged — streaming=%s outputState=%s", self._state.streaming, state)
        elif event_name == "RecordingStateChanged":
            state = event_data.get("outputState", "")
            self._state.recording = state == "OBS_WEBSOCKET_OUTPUT_STATE_STARTED"
            logger.info("[OBSClient] Event RecordingStateChanged — recording=%s outputState=%s", self._state.recording, state)
        elif event_name == "InputVolumeChanged":
            name = event_data.get("inputName", "")
            vol = float(event_data.get("inputVolumeMultiplier", 1.0))
            if name in self._state.inputs:
                self._state.inputs[name].volume = vol
            logger.info("[OBSClient] Event InputVolumeChanged — input=%s volume=%.2f", name, vol)
        elif event_name == "InputMuteStateChanged":
            name = event_data.get("inputName", "")
            muted = bool(event_data.get("inputMuted", False))
            if name in self._state.inputs:
                self._state.inputs[name].muted = muted
            logger.info("[OBSClient] Event InputMuteStateChanged — input=%s muted=%s", name, muted)

        for cb in self._callbacks:
            try:
                cb(event_name, event_data)
            except Exception:
                pass

    def _fire_callbacks(self, event_name: str, event_data: dict):
        """Fire registered callbacks with an event, e.g. after a local action updates state."""
        logger.info("[OBSClient] _fire_callbacks — event=%s", event_name)
        for cb in self._callbacks:
            try:
                cb(event_name, event_data)
            except Exception:
                pass
                pass

    async def switch_scene(self, scene_name: str):
        logger.info("[OBSClient] Action: switch_scene — scene=%s", scene_name)
        if self._ws:
            try:
                self._ws.call(requests.SetCurrentProgramScene(sceneName=scene_name))
                self.enqueue_sync_and_wait()
                self._fire_callbacks("CurrentProgramSceneChanged", {"sceneName": scene_name})
            except Exception as e:
                logger.error("[OBSClient] switch_scene failed — scene=%s error=%s", scene_name, e)
                raise RuntimeError(f"Failed to switch scene: {e}") from e

    async def toggle_stream(self):
        action = "StartStream" if not self._state.streaming else "StopStream"
        logger.info("[OBSClient] Action: toggle_stream — action=%s current_streaming=%s", action, self._state.streaming)
        if self._ws:
            try:
                if self._state.streaming:
                    self._ws.call(requests.StopStream())
                else:
                    self._ws.call(requests.StartStream())
                self.enqueue_sync_and_wait()
                self._fire_callbacks("StreamStateChanged", {"outputState": "OBS_WEBSOCKET_OUTPUT_STATE_STARTED" if not self._state.streaming else "OBS_WEBSOCKET_OUTPUT_STATE_STOPPED"})
            except Exception as e:
                logger.error("[OBSClient] toggle_stream failed — action=%s error=%s", action, e)
                raise RuntimeError(f"Failed to toggle stream: {e}") from e

    async def toggle_recording(self):
        action = "StartRecording" if not self._state.recording else "StopRecording"
        logger.info("[OBSClient] Action: toggle_recording — action=%s current_recording=%s", action, self._state.recording)
        if self._ws:
            try:
                if self._state.recording:
                    self._ws.call(requests.StopRecording())
                else:
                    self._ws.call(requests.StartRecording())
                self.enqueue_sync_and_wait()
                self._fire_callbacks("RecordingStateChanged", {"outputState": "OBS_WEBSOCKET_OUTPUT_STATE_STARTED" if not self._state.recording else "OBS_WEBSOCKET_OUTPUT_STATE_STOPPED"})
            except Exception as e:
                logger.error("[OBSClient] toggle_recording failed — action=%s error=%s", action, e)
                raise RuntimeError(f"Failed to toggle recording: {e}") from e

    async def toggle_input_mute(self, input_name: str):
        muted = self._state.inputs.get(input_name).muted if input_name in self._state.inputs else None
        action = "Unmute" if muted else "Mute"
        logger.info("[OBSClient] Action: toggle_input_mute — input=%s action=%s current_muted=%s", input_name, action, muted)
        if self._ws:
            try:
                self._ws.call(requests.ToggleInputMute(inputName=input_name))
                self.enqueue_sync_and_wait()
                self._fire_callbacks("InputMuteStateChanged", {"inputName": input_name, "inputMuted": not muted if muted is not None else True})
            except Exception as e:
                logger.error("[OBSClient] toggle_input_mute failed — input=%s error=%s", input_name, e)
                raise RuntimeError(f"Failed to toggle mute: {e}") from e

    async def trigger_media_action(self, input_name: str, action: str):
        logger.info("[OBSClient] Action: trigger_media_action — input=%s action=%s", input_name, action)
        if self._ws:
            try:
                self._ws.call(requests.TriggerMediaInputAction(inputName=input_name, mediaAction=action))
            except Exception as e:
                logger.error("[OBSClient] trigger_media_action failed — input=%s action=%s error=%s", input_name, action, e)
                raise RuntimeError(f"Failed to trigger media action: {e}") from e
