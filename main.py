"""WheelBridge — camada genérica de tradução de entrada (etapa 1: teste no navegador).

Pipeline desta etapa::

    micro:bit → USB serial → InputAdapter → NormalizedReading
        → SteeringProcessor → HTTP/SSE/WebSocket → dashboard
                              ↘ (opcional, --gamepad) gamepad virtual Linux

Uso:
    python main.py --simulate            # sem hardware (senoide demo)
    python main.py --port auto            # micro:bit (padrão)
    python main.py --port /dev/ttyACM0 --baud 115200 --http-port 8123
    python main.py --port /dev/ttyACM0 --gamepad   # + gamepad p/ jogos
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

# Roda de qualquer pasta, com Python portátil (vendor/) ou .exe (frozen).
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from paths import base_dir, user_dir
except ImportError:  # desenvolvimento sem paths.py? usa raiz
    def base_dir() -> Path:
        return _ROOT

    def user_dir() -> Path:
        return _ROOT
_VENDOR = base_dir() / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from core.models import ProcessorConfig
from core.pedals import PedalConfig
from core.steering import SteeringProcessor
from inputs.base import InputDevice
from inputs.microbit_serial import MicrobitSerialInput
from inputs.simulated import SimulatedInput
from server.dashboard_server import DashboardServer

log = logging.getLogger("wheelbridge")

DEFAULTS = {
    "port": "auto",
    "baud": 115200,
    "host": "127.0.0.1",
    "http_port": 8123,
    "max_angle_deg": 90.0,
    "deadzone": 0.05,
    "smoothing": 0.35,
    "gear_flash_ms": 400,
    "pedal_far_mm": 50.0,
    "pedal_near_mm": 20.0,
    "pedal_smoothing": 0.5,
}


def load_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("config %s ignorado: JSON raiz deve ser objeto", path)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("não foi possível ler %s: %s", path, exc)
        return {}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WheelBridge — teste do volante no navegador")
    p.add_argument("--port", default=None, help="porta serial ou 'auto' (padrão: auto)")
    p.add_argument("--baud", type=int, default=None, help="baud rate (padrão: 115200)")
    p.add_argument("--host", default=None, help="interface HTTP (padrão: 127.0.0.1)")
    p.add_argument("--http-port", type=int, default=None, help="porta do dashboard (padrão: 8123)")
    p.add_argument("--max-angle", type=float, default=None, help="graus por lado p/ |steering|=1 (padrão: 90)")
    p.add_argument("--deadzone", type=float, default=None, help="zona morta 0..0.9 (padrão: 0.05)")
    p.add_argument("--smoothing", type=float, default=None, help="alpha EMA 0..1 (padrão: 0.35)")
    p.add_argument("--pedal-far", type=float, default=None, help="mm p/ pedal solto (padrão: 50)")
    p.add_argument("--pedal-near", type=float, default=None, help="mm p/ pedal no fundo (padrão: 20)")
    p.add_argument("--simulate", action="store_true", help="usa senoide simulada, sem hardware")
    p.add_argument("--gamepad", action="store_true",
                   help="cria gamepad virtual Linux (uinput) p/ jogos")
    p.add_argument("--gamepad-rate", type=float, default=None,
                   help="taxa de publicação na saída em Hz (padrão: 60)")
    p.add_argument("--keyboard", action="store_true",
                   help="teclado virtual no Windows (sem driver) p/ jogos")
    p.add_argument("--browser", action="store_true",
                   help="abre o dashboard no navegador ao iniciar")
    p.add_argument("--config", default=None,
                   help="arquivo JSON de config (padrão: config.json ao lado do programa)")
    p.add_argument("--verbose", "-v", action="store_true", help="log detalhado")
    return p


def resolve(value: Any, file_value: Any, default: Any) -> Any:
    if value is not None:
        return value
    if file_value is not None:
        return file_value
    return default


def build_device(args: argparse.Namespace, cfg: dict[str, Any]) -> InputDevice:
    if args.simulate or cfg.get("simulate"):
        period = float(cfg.get("simulate_period_s", 8.0))
        return SimulatedInput(period_s=period)
    port = resolve(args.port, cfg.get("port"), DEFAULTS["port"])
    baud = int(resolve(args.baud, cfg.get("baud"), DEFAULTS["baud"]))
    if str(port) == "auto":
        # Auto inteligente: prefere o hub (pedais+relay) ao volante direto.
        try:
            from inputs.autodetect import detect_setup, pick_port

            found = detect_setup(baudrate=baud)
            picked = pick_port(found)
            if picked:
                for entry in found:
                    log.info("placa: %s (%s)", entry.device, entry.role)
                port = picked
        except Exception as exc:
            log.warning("autodetecção falhou (%s); usando busca simples", exc)
    return MicrobitSerialInput(port=str(port), baudrate=baud)


def pump_output(
    output: Any,
    processor: SteeringProcessor,
    device: InputDevice,
    stop: threading.Event,
    rate_hz: float = 60.0,
) -> None:
    """Publica snapshots do núcleo na saída até `stop` ser sinalizado."""
    interval = 1.0 / max(1.0, rate_hz)
    while not stop.is_set():
        try:
            output.publish(
                processor.snapshot(
                    connected=device.is_connected,
                    port=device.port_info,
                    last_seen=device.last_seen,
                )
            )
        except Exception as exc:
            log.warning("falha ao publicar em %s: %s", getattr(output, "name", "?"), exc)
        stop.wait(interval)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg_path = Path(args.config) if args.config else (user_dir() / "config.json")
    file_cfg = load_config_file(cfg_path)

    try:
        proc_cfg = ProcessorConfig(
            max_angle_deg=float(resolve(args.max_angle, file_cfg.get("max_angle_deg"), DEFAULTS["max_angle_deg"])),
            deadzone=float(resolve(args.deadzone, file_cfg.get("deadzone"), DEFAULTS["deadzone"])),
            smoothing=float(resolve(args.smoothing, file_cfg.get("smoothing"), DEFAULTS["smoothing"])),
            gear_flash_ms=int(file_cfg.get("gear_flash_ms", DEFAULTS["gear_flash_ms"])),
        )
        proc_cfg.validate()
        pedal_cfg = PedalConfig(
            far_mm=float(resolve(args.pedal_far, file_cfg.get("pedal_far_mm"), DEFAULTS["pedal_far_mm"])),
            near_mm=float(resolve(args.pedal_near, file_cfg.get("pedal_near_mm"), DEFAULTS["pedal_near_mm"])),
            smoothing=float(file_cfg.get("pedal_smoothing", DEFAULTS["pedal_smoothing"])),
        )
        pedal_cfg.validate()
    except ValueError as exc:
        log.error("config inválida: %s", exc)
        return 2

    host = str(resolve(args.host, file_cfg.get("host"), DEFAULTS["host"]))
    http_port = int(resolve(args.http_port, file_cfg.get("http_port"), DEFAULTS["http_port"]))

    processor = SteeringProcessor(proc_cfg, pedal_cfg)
    device = build_device(args, file_cfg)
    server = DashboardServer(processor, device, host=host, port=http_port,
                             web_dir=base_dir() / "server" / "web")

    if args.gamepad and args.keyboard:
        log.error("use --gamepad OU --keyboard, não os dois")
        return 2

    output = None
    output_stop = threading.Event()
    output_thread = None
    if args.gamepad or file_cfg.get("gamepad"):
        from outputs.uinput_gamepad import UinputGamepad, check_gamepad_requirements

        problems = check_gamepad_requirements()
        if problems:
            log.error("gamepad virtual indisponível:")
            for item in problems:
                log.error("  - %s", item)
            return 3
        output = UinputGamepad()
    elif args.keyboard or file_cfg.get("keyboard"):
        from outputs.keyboard_windows import KeyboardWindows, KeyMap

        try:
            keymap = KeyMap.from_dict(file_cfg.get("keys"))
        except ValueError as exc:
            log.error("keymap inválido: %s", exc)
            return 2
        output = KeyboardWindows(keymap)
    if output is not None:
        try:
            output.start()
        except (RuntimeError, OSError) as exc:
            log.error("não foi possível ativar a saída %s: %s", output.name, exc)
            return 3
        rate = float(resolve(args.gamepad_rate, file_cfg.get("gamepad_rate"), 60.0))
        output_thread = threading.Thread(
            target=pump_output,
            args=(output, processor, device, output_stop, rate),
            name="output-pump",
            daemon=True,
        )

    device.start()
    server.start()
    if output_thread is not None:
        output_thread.start()
    if args.browser or file_cfg.get("browser"):
        try:
            webbrowser.open(server.url)
        except Exception as exc:
            log.warning("não foi possível abrir o navegador: %s", exc)
    print(f"\n  Abra o navegador em:  {server.url}\n"
          f"  Adaptador: {device.name}  |  gire o micro:bit e veja o marcador mover.\n"
          + (f"  Saída ativa: {output.name} ({output.device_path if hasattr(output, 'device_path') else 'teclado'})\n" if output else "")
          + f"  Ctrl+C para sair.\n")

    try:
        # Bomba principal: drena leituras normalizadas → núcleo.
        while True:
            for reading in device.drain():
                if reading.heading_deg is not None:
                    processor.update_heading(reading.heading_deg)
                if reading.gear is not None:
                    try:
                        processor.gear_event(reading.gear)
                    except ValueError as exc:
                        log.warning("%s", exc)
                if reading.shift is not None:
                    processor.shift_event(reading.shift)
                if reading.mode is not None:
                    processor.set_mode(reading.mode == "AUTO")
                if reading.handbrake is not None:
                    processor.set_handbrake(reading.handbrake)
                if (reading.brake_mm is not None or reading.accel_mm is not None
                        or reading.clutch_mm is not None):
                    processor.update_pedals(
                        reading.brake_mm, reading.accel_mm, reading.clutch_mm
                    )
            time.sleep(0.01)  # ~100 Hz
    except KeyboardInterrupt:
        print("\nEncerrando…")
    finally:
        if output_thread is not None:
            output_stop.set()
            output_thread.join(timeout=2.0)
        if output is not None:
            output.stop()
        server.stop()
        device.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
