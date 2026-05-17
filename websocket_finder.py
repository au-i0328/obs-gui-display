import asyncio
import socket
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

try:
    import ifaddr
    _HAS_IFADDR = True
except ImportError:
    _HAS_IFADDR = False

try:
    import netifaces
    _HAS_NETIFACES = True
except ImportError:
    _HAS_NETIFACES = False

import obswebsocket
import obswebsocket.baseRequests
import obswebsocket.exceptions

OBS_DEFAULT_PORT = 4455
OBS_PORT_RANGE = range(4444, 4465)
COMMON_PORTS = [4455, 4444, 4450, 4451, 4452, 4453, 4454, 4456, 4457, 4458, 4459]
SCAN_TIMEOUT = 0.25
_SCAN_WORKERS = 60


@dataclass
class DiscoveredOBS:
    host: str
    port: int
    obs_version: Optional[str] = None
    ws_version: Optional[str] = None
    identified: bool = False

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


def _get_local_ips() -> list[str]:
    ips = []
    discovered = set()

    if _HAS_IFADDR:
        for adapter in ifaddr.get_adapters():
            for addr in adapter.ips:
                if addr.is_ip:
                    ip = addr.ip
                    if ip and ip not in ("127.0.0.1", "::1") and "." in ip:
                        if ip not in discovered:
                            discovered.add(ip)
                            ips.append(ip)

    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and ip not in discovered:
                discovered.add(ip)
                ips.append(ip)
        except OSError:
            pass

    if "127.0.0.1" not in discovered:
        discovered.add("127.0.0.1")
        ips.insert(0, "127.0.0.1")

    return ips


async def _probe_host(host: str, port: int, semaphore: asyncio.Semaphore) -> Optional[DiscoveredOBS]:
    async with semaphore:
        url = f"ws://{host}:{port}"
        try:
            client = obswebsocket.WebSocket()
            client.connect(url, timeout=SCAN_TIMEOUT)
            try:
                hello = client.call("GetVersion")
                obs_version = getattr(hello, "obsWebSocketVersion", None)
                ident = None
                try:
                    ident = client.call("GetAuthRequired")
                except Exception:
                    pass
                return DiscoveredOBS(
                    host=host,
                    port=port,
                    obs_version=str(hello.obsWebSocketVersion or ""),
                    ws_version=str(hello.obsWebSocketVersion or ""),
                    identified=True,
                )
            finally:
                client.disconnect()
        except Exception:
            return None


async def find_all_obs_websockets(
    timeout: float = 8.0,
) -> AsyncGenerator[DiscoveredOBS, None]:
    hosts = _get_local_ips()
    ports = sorted(set([OBS_PORT_RANGE[0], OBS_PORT_RANGE[-1]] + list(OBS_PORT_RANGE) + COMMON_PORTS))

    tasks = []
    semaphore = asyncio.Semaphore(_SCAN_WORKERS)

    for host in hosts:
        for port in ports:
            task = asyncio.create_task(_probe_host(host, port, semaphore))
            tasks.append(task)

    done, pending = [], []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while tasks and loop.time() < deadline:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        done_n, pending = await asyncio.wait(
            tasks, timeout=min(remaining, 1.0), return_when=asyncio.FIRST_COMPLETED
        )
        for t in done_n:
            tasks.remove(t)
        done.extend(done_n)

    for t in tasks:
        t.cancel()

    seen = set()
    for t in done:
        try:
            result = t.result()
        except Exception:
            continue
        if result is not None:
            key = (result.host, result.port)
            if key not in seen:
                seen.add(key)
                yield result

    for t in pending:
        t.cancel()
