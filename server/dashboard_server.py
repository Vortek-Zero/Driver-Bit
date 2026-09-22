"""Servidor local de teste: HTTP + SSE + WebSocket (apenas stdlib).

O navegador é SOMENTE visualização. Toda a lógica do volante está no
``SteeringProcessor``; este servidor apenas serializa o snapshot.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import select
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from core.steering import SteeringProcessor
from inputs.base import InputDevice

log = logging.getLogger(__name__)

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_accept(key: str) -> str:
    digest = hashlib.sha1((key.strip() + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _ws_send_text(sock, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += n.to_bytes(2, "big")
    else:
        header.append(127)
        header += n.to_bytes(8, "big")
    sock.sendall(bytes(header) + payload)


def _ws_recv_frame(sock) -> Optional[dict]:
    """Lê UM frame do cliente. Retorna {'opcode': int, 'payload': bytes} ou None."""
    try:
        hdr = sock.recv(2)
    except (TimeoutError, OSError):
        return None
    if len(hdr) < 2:
        return None
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        ext = sock.recv(2)
        if len(ext) < 2:
            return None
        length = int.from_bytes(ext, "big")
    elif length == 127:
        ext = sock.recv(8)
        if len(ext) < 8:
            return None
        length = int.from_bytes(ext, "big")
    mask = sock.recv(4) if masked else b""
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            break
        payload += chunk
    if masked and mask:
        payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
    return {"opcode": opcode, "payload": payload}


def _ws_send_control(sock, opcode: int, payload: bytes = b"") -> None:
    header = bytes([0x80 | opcode, len(payload)])
    sock.sendall(header + payload)


class DashboardServer:
    """HTTP estático + JSON API + SSE + WebSocket na mesma porta."""

    def __init__(
        self,
        processor: SteeringProcessor,
        device: InputDevice,
        host: str = "127.0.0.1",
        port: int = 8123,
        web_dir: Optional[Path] = None,
        broadcast_hz: float = 30.0,
    ) -> None:
        self._processor = processor
        self._device = device
        self._host = host
        self._port = port
        self._web_dir = web_dir or (Path(__file__).resolve().parent / "web")
        self._interval = 1.0 / max(1.0, broadcast_hz)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def snapshot_dict(self) -> dict:
        state = self._processor.snapshot(
            connected=self._device.is_connected,
            port=self._device.port_info,
            last_seen=self._device.last_seen,
        )
        data = state.to_dict()
        data["capture"] = self._processor.capture_status()
        data["last_capture"] = self._processor.last_capture()
        data["locks"] = self._processor.lock_marks()
        return data

    def start(self) -> None:
        processor, device, web_dir, interval = (
            self._processor,
            self._device,
            self._web_dir,
            self._interval,
        )
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "WheelBridge/1.0"

            def log_message(self, fmt, *args):  # reduz ruído; vai p/ logging
                log.debug("%s - %s", self.address_string(), fmt % args)

            # -- utilidades -------------------------------------------
            def _send_json(self, obj, status: int = 200) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _state(self) -> dict:
                return server_self.snapshot_dict()

            def _serve_static(self, filename: str) -> None:
                safe = (web_dir / filename.lstrip("/")).resolve()
                try:
                    safe.relative_to(web_dir.resolve())
                except ValueError:
                    self.send_error(403)
                    return
                if not safe.is_file():
                    self.send_error(404, f"não encontrado: {filename}")
                    return
                mime, _ = mimetypes.guess_type(str(safe))
                body = safe.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            # -- rotas GET ---------------------------------------------
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._serve_static("index.html")
                elif path in ("/app.js", "/style.css"):
                    self._serve_static(path.lstrip("/"))
                elif path == "/api/state":
                    self._send_json(self._state())
                elif path == "/api/config":
                    pcfg = processor.pedal_config
                    self._send_json(
                        {
                            "max_angle_deg": processor.config.max_angle_deg,
                            "deadzone": processor.config.deadzone,
                            "smoothing": processor.config.smoothing,
                            "pedal_far_mm": pcfg.far_mm,
                            "pedal_near_mm": pcfg.near_mm,
                            "pedal_smoothing": pcfg.smoothing,
                        }
                    )
                elif path == "/events":
                    self._handle_sse()
                elif path == "/ws":
                    self._handle_ws()
                else:
                    self.send_error(404)

            # -- rotas POST --------------------------------------------
            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except json.JSONDecodeError:
                    self._send_json({"error": "JSON inválido"}, status=400)
                    return
                if path == "/api/calibrate":
                    mode = str(body.get("mode", "hold")).lower()
                    try:
                        if mode == "instant":
                            center = processor.calibrate()
                            self._send_json({"mode": "instant", "center": center})
                        elif mode == "hold":
                            seconds = float(body.get("seconds", 2.0))
                            info = processor.start_center_capture(seconds)
                            self._send_json({"mode": "hold", **info})
                        else:
                            self._send_json(
                                {"error": "mode deve ser 'hold' ou 'instant'"}, status=400
                            )
                    except (RuntimeError, ValueError) as exc:
                        self._send_json({"error": str(exc)}, status=409)
                        return
                elif path == "/api/calibrate/cancel":
                    processor.cancel_capture()
                    self._send_json({"cancelled": True})
                elif path == "/api/lock":
                    side = str(body.get("side", "")).upper()
                    try:
                        marked = processor.mark_lock(side)
                    except (RuntimeError, ValueError) as exc:
                        self._send_json({"error": str(exc)}, status=409)
                        return
                    self._send_json({"side": side, "angle": marked})
                elif path == "/api/lock/finish":
                    try:
                        result = processor.finish_lock_calibration()
                    except (RuntimeError, ValueError) as exc:
                        self._send_json({"error": str(exc)}, status=409)
                        return
                    self._send_json(result)
                elif path == "/api/lock/clear":
                    processor.clear_locks()
                    self._send_json({"cleared": True})
                elif path == "/api/reset":
                    processor.reset_calibration()
                    self._send_json({"center": None})
                elif path == "/api/config":
                    try:
                        cfg = processor.update_config(
                            max_angle_deg=body.get("max_angle_deg"),
                            deadzone=body.get("deadzone"),
                            smoothing=body.get("smoothing"),
                            pedal_far_mm=body.get("pedal_far_mm"),
                            pedal_near_mm=body.get("pedal_near_mm"),
                            pedal_smoothing=body.get("pedal_smoothing"),
                        )
                    except (ValueError, TypeError) as exc:
                        self._send_json({"error": str(exc)}, status=400)
                        return
                    pcfg = processor.pedal_config
                    self._send_json(
                        {
                            "max_angle_deg": cfg.max_angle_deg,
                            "deadzone": cfg.deadzone,
                            "smoothing": cfg.smoothing,
                            "pedal_far_mm": pcfg.far_mm,
                            "pedal_near_mm": pcfg.near_mm,
                            "pedal_smoothing": pcfg.smoothing,
                        }
                    )
                elif path == "/api/gear":
                    gear = str(body.get("gear", "")).upper()
                    if gear not in ("UP", "DOWN"):
                        self._send_json({"error": "gear deve ser UP ou DOWN"}, status=400)
                        return
                    try:
                        processor.gear_event(gear)
                    except ValueError as exc:
                        self._send_json({"error": str(exc)}, status=400)
                        return
                    self._send_json({"gear": gear})
                elif path == "/api/shift":
                    shift = str(body.get("shift", "")).upper()
                    if shift not in ("UP", "DOWN"):
                        self._send_json({"error": "shift deve ser UP ou DOWN"}, status=400)
                        return
                    accepted = processor.shift_event(shift)
                    self._send_json({"shift": shift, "accepted": accepted})
                elif path == "/api/mode":
                    if "auto" not in body:
                        self._send_json({"error": "envie {\"auto\": true/false}"}, status=400)
                        return
                    auto = processor.set_mode(bool(body["auto"]))
                    self._send_json({"auto": auto})
                elif path == "/api/handbrake":
                    if "on" not in body:
                        self._send_json({"error": "envie {\"on\": true/false}"}, status=400)
                        return
                    on = processor.set_handbrake(bool(body["on"]))
                    self._send_json({"handbrake": on})
                else:
                    self.send_error(404)

            # -- SSE ----------------------------------------------------
            def _handle_sse(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    while True:
                        data = json.dumps(self._state())
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(interval)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            # -- WebSocket ----------------------------------------------
            def _handle_ws(self) -> None:
                upgrade = (self.headers.get("Upgrade") or "").lower()
                key = self.headers.get("Sec-WebSocket-Key")
                if upgrade != "websocket" or not key:
                    self.send_error(400, "esperado upgrade para websocket em /ws")
                    return
                accept = _ws_accept(key)
                self.send_response(101, "Switching Protocols")
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                sock = self.connection
                sock.settimeout(1.0)
                log.info("websocket conectado: %s", self.address_string())
                try:
                    while True:
                        # 1) consome frames do cliente (detecta close/ping)
                        try:
                            readable, _, _ = select.select([sock], [], [], interval)
                        except (OSError, ValueError):
                            break
                        if readable:
                            frame = _ws_recv_frame(sock)
                            if frame is None:
                                break
                            op = frame["opcode"]
                            if op == 0x8:  # close
                                try:
                                    _ws_send_control(sock, 0x8, frame["payload"][:125])
                                except OSError:
                                    pass
                                break
                            if op == 0x9:  # ping → pong
                                try:
                                    _ws_send_control(sock, 0xA, frame["payload"][:125])
                                except OSError:
                                    break
                                continue
                        # 2) envia estado atual
                        try:
                            _ws_send_text(sock, json.dumps(self._state()))
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                finally:
                    log.info("websocket desconectado: %s", self.address_string())

        self._httpd = ThreadingHTTPServer((self._host, self._port), Handler)
        self._httpd.daemon_threads = True
        # Se porta 0 → SO escolhe; atualiza para o URL real.
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="dashboard-http", daemon=True
        )
        self._thread.start()
        log.info("dashboard em %s", self.url)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=3.0)
