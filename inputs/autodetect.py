"""Autodetecção de placas micro:bit (qualquer SO).

Encontra portas de micro:bit pelo VID/PID USB e identifica o PAPEL de
cada placa farejando linhas seriais:

- viu ``BRAKE:``/``ACCEL:`` → ``hub`` (pedais + relay do volante);
- só ``STEER:``/``GEAR:`` → ``wheel`` (volante direto);
- nada legível → ``unknown``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger(__name__)

MICROBIT_VID_PIDS = {(0x0D28, 0x0204)}


@dataclass
class MicrobitPort:
    device: str  # ex: COM7, /dev/ttyACM0
    serial_number: Optional[str] = None
    description: Optional[str] = None
    role: str = "unknown"  # hub | wheel | unknown


def find_microbits() -> List[MicrobitPort]:
    """Lista portas com VID/PID de micro:bit (ordenadas)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    found = []
    for info in sorted(list_ports.comports(), key=lambda p: p.device or ""):
        vidpid = (getattr(info, "vid", None), getattr(info, "pid", None))
        if vidpid in MICROBIT_VID_PIDS and info.device:
            found.append(
                MicrobitPort(
                    device=info.device,
                    serial_number=getattr(info, "serial_number", None),
                    description=getattr(info, "description", None),
                )
            )
    return found


def classify_lines(lines: List[str]) -> str:
    """Papel da placa a partir de linhas já lidas (função pura, testável)."""
    saw_pedal = saw_steer = False
    for line in lines:
        upper = line.strip().upper()
        if upper.startswith("BRAKE:") or upper.startswith("ACCEL:"):
            saw_pedal = True
        elif upper.startswith("STEER:") or upper.startswith("GEAR:"):
            saw_steer = True
    if saw_pedal:
        return "hub"
    if saw_steer:
        return "wheel"
    return "unknown"


def sniff_role(port: str, baudrate: int = 115200, duration_s: float = 2.5) -> str:
    """Abre a porta, lê por `duration_s` e classifica (fecha ao final)."""
    import serial

    lines: List[str] = []
    try:
        with serial.Serial(port, baudrate, timeout=0.5) as ser:
            ser.reset_input_buffer()
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                raw = ser.readline()
                if raw:
                    lines.append(raw.decode("utf-8", errors="ignore"))
                if classify_lines(lines) == "hub":
                    break  # hub já provado; volante puro exige a janela toda
    except Exception as exc:
        log.warning("sniff %s: %s", port, exc)
        return "unknown"
    return classify_lines(lines)


def detect_setup(baudrate: int = 115200,
                 sniff_s: float = 2.5) -> List[MicrobitPort]:
    """Encontra placas e fareja o papel de cada uma."""
    ports = find_microbits()
    if len(ports) == 1:
        # Uma só: usa direto (papel descoberto pelo uso; sem espera).
        return ports
    for entry in ports:
        entry.role = sniff_role(entry.device, baudrate, sniff_s)
    return ports


def pick_port(ports: List[MicrobitPort]) -> Optional[str]:
    """Escolhe a melhor porta: hub > wheel > primeira disponível."""
    if not ports:
        return None
    for want in ("hub", "wheel"):
        for entry in ports:
            if entry.role == want:
                return entry.device
    return ports[0].device
