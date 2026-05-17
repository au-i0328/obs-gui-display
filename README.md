# OBS WebSocket Finder & Viewer

A cross-platform Python GUI application that automatically discovers active OBS Studio instances broadcasting WebSocket servers across all network interfaces, and presents an elegant dashboard for monitoring and controlling OBS.

## Features

- **Zero-config auto-start** — launches and begins scanning immediately; no user input required
- **Multi-interface scanning** — discovers OBS WebSocket servers on all local network interfaces and ports 4444–4464
- **Cross-platform** — works identically on macOS, Windows, and Linux
- **Elegant connection picker** — shows each discovered instance with OBS version and WebSocket version badges
- **Customizable dashboard** — toggle which panels appear (Scenes, Sources, Audio, Stats, Media) via the settings dialog
- **Real-time updates** — responds to OBS events (scene changes, stream start/stop, mute toggles) without polling
- **OBS control** — start/stop streaming and recording, switch scenes, toggle mutes, and control media sources directly from the GUI

## Requirements

- Python 3.10 or later
- OBS Studio 28.0 or later with WebSocket server enabled

### OBS WebSocket Setup

1. Open OBS Studio
2. Go to **Tools → WebSocket Server Settings**
3. Enable the server and set a password (optional)
4. Note the port number (default: 4455)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

The application will immediately begin scanning all network interfaces for running OBS WebSocket servers.

## Display Settings

Click the gear icon (⚙) on the connection screen to choose which panels appear in the dashboard:

| Panel | Description |
|---|---|
| Scenes | Live list of all OBS scenes; click to switch |
| Sources | Tree view of sources per scene |
| Audio | Volume meters and mute controls per input |
| Stats | FPS, CPU, memory, bitrate, stream/recording time |
| Media | Play/pause/stop/restart controls for media sources |

Settings are persisted to `~/.obs-pygui/settings.json`.

## Architecture

```
obs-pygui/
├── main.py               Entry point; sets up qasync event loop
├── config.py             Settings persistence (~/.obs-pygui/settings.json)
├── obs_data.py          Data models (OBSInstance, OBSState, OBSStats, etc.)
├── websocket_finder.py  Async scanner for all interfaces + ports
├── obs_client.py        Async OBS WebSocket client wrapper
└── ui/
    ├── main_window.py       QMainWindow + View menu
    ├── connection_screen.py Auto-scan + instance picker
    ├── obs_dashboard.py     Tabbed dashboard widget
    └── widgets/
        ├── scene_list.py
        ├── source_list.py
        ├── audio_meters.py
        ├── stats_panel.py
        └── media_controls.py
```

## Dependencies

| Package | Purpose |
|---|---|
| PySide6 | Cross-platform Qt UI framework |
| obs-websocket-py | OBS WebSocket protocol client |
| qasync | Qt event loop integration for asyncio |
| ifaddr | Network interface enumeration |
| websockets | Async WebSocket client (peer) |
| aiohttp | Async HTTP client (peer) |

## Troubleshooting

**No instances found**
- Ensure OBS Studio is running
- Verify WebSocket Server is enabled (`Tools → WebSocket Server Settings`)
- Check the port matches the OBS settings
- Try clicking "Refresh Scan"

**Connection refused**
- A firewall may be blocking the WebSocket port
- Verify OBS WebSocket server port in OBS settings

**Authentication failed**
- OBS Studio requires a password for this instance
- Double-click the instance entry to enter the password
