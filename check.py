"""WheelBridge self-check (o "F5"): verifica tudo em segundos, sem servidor.

Uso (duplo clique no Windows via INICIAR.bat, ou terminal)::

    python check.py

Checa: Python, pyserial, placas micro:bit (papel hub/volante), fluxo
real de linhas seriais, arquivos do dashboard, porta HTTP livre e saída
disponível na plataforma (teclado no Windows, gamepad no Linux).
Saída 0 = tudo pronto; 1 = algo a corrigir (a lista diz o quê).
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from paths import base_dir, user_dir
except ImportError:
    def base_dir() -> Path:
        return ROOT

    def user_dir() -> Path:
        return ROOT
VENDOR = base_dir() / "vendor"
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

results: list[tuple[str, bool, str]] = []


def item(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "[OK] " if ok else "[FALHOU]"
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=== WheelBridge self-check ===\n")

    # 1) Python
    ok = sys.version_info >= (3, 10)
    item("python", ok, f"{sys.version.split()[0]} (mínimo 3.10)")

    # 2) pyserial
    try:
        import serial  # noqa: F401

        item("pyserial", True, "comunicação USB disponível")
    except ImportError:
        item("pyserial", False, "copie a pasta vendor/ ou: pip install pyserial")

    # 3) placas micro:bit
    roles: dict[str, str] = {}
    try:
        from inputs.autodetect import detect_setup

        ports = detect_setup()
        if not ports:
            item("micro:bit", False, "nenhuma placa achada — confira cabos USB (dados, não só carga)")
        else:
            for entry in ports:
                roles[entry.device] = entry.role
            item("micro:bit", True, ", ".join(f"{d}={r}" for d, r in roles.items()))
    except Exception as exc:
        item("micro:bit", False, str(exc))

    # 4) fluxo real de linhas (prova que a placa fala o protocolo)
    if roles:
        try:
            from inputs.autodetect import sniff_role  # noqa
            from inputs.microbit_serial import parse_line

            import serial as serial_mod

            counts: dict[str, int] = {}
            first = next(iter(roles))
            with serial_mod.Serial(first, 115200, timeout=0.5) as ser:
                ser.reset_input_buffer()
                import time

                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and sum(counts.values()) < 10:
                    raw = ser.readline()
                    if not raw:
                        continue
                    try:
                        reading = parse_line(raw.decode("utf-8", errors="ignore"))
                    except ValueError:
                        counts["invalidas"] = counts.get("invalidas", 0) + 1
                        continue
                    if reading is None:
                        continue
                    if reading.heading_deg is not None:
                        counts["STEER"] = counts.get("STEER", 0) + 1
                    if reading.gear is not None:
                        counts["GEAR"] = counts.get("GEAR", 0) + 1
                    if reading.brake_mm is not None:
                        counts["BRAKE"] = counts.get("BRAKE", 0) + 1
                    if reading.accel_mm is not None:
                        counts["ACCEL"] = counts.get("ACCEL", 0) + 1
            ok = any(k in counts for k in ("STEER", "BRAKE", "ACCEL"))
            item("protocolo", ok, f"{first}: {counts or 'sem linhas em 3s'}")
        except Exception as exc:
            item("protocolo", False, str(exc))

    # 5) arquivos do dashboard
    web = base_dir() / "server" / "web"
    ok = (web / "index.html").is_file() and (web / "app.js").is_file()
    item("dashboard", ok, str(web) if ok else "arquivos web ausentes")

    # 6) config + porta HTTP
    try:
        cfg = json.loads((user_dir() / "config.json").read_text(encoding="utf-8"))
        port = int(cfg.get("http_port", 8123))
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
            item("porta http", True, f"{port} livre")
        except OSError:
            item("porta http", False, f"{port} ocupada — outro servidor rodando?")
        finally:
            probe.close()
    except Exception as exc:
        item("porta http", False, str(exc))

    # 7) saída da plataforma
    if sys.platform == "win32":
        try:
            from outputs.keyboard_windows import available_keys  # noqa

            item("saída teclado", True, "SendInput pronto (sem driver)")
        except Exception as exc:
            item("saída teclado", False, str(exc))
    else:
        try:
            from outputs.uinput_gamepad import check_gamepad_requirements

            problems = check_gamepad_requirements()
            item("saída gamepad", not problems, "pronta" if not problems else "; ".join(problems))
        except Exception as exc:
            item("saída gamepad", False, str(exc))

    print()
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"RESULTADO: {len(failed)} item(ns) com problema: {', '.join(failed)}")
        return 1
    print("RESULTADO: tudo pronto — pode iniciar o servidor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
