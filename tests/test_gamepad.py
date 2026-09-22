"""Testes da saída gamepad virtual (sem hardware, sem /dev/uinput)."""

import unittest

from core.models import WheelState
from outputs.uinput_gamepad import (
    ABS_MAX,
    UinputGamepad,
    check_gamepad_requirements,
    steering_to_abs,
)


class FakeUI:
    """Dublê de evdev.UInput: registra write()/syn()."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.events = []
        self.syncs = 0
        self.closed = False

    def write(self, kind, code, value):
        self.events.append((kind, code, value))

    def syn(self):
        self.syncs += 1

    def close(self):
        self.closed = True


class TestSteeringToAbs(unittest.TestCase):
    def test_extremos_e_centro(self):
        self.assertEqual(steering_to_abs(-1.0), -ABS_MAX)
        self.assertEqual(steering_to_abs(0.0), 0)
        self.assertEqual(steering_to_abs(1.0), ABS_MAX)

    def test_meio_curso(self):
        self.assertEqual(steering_to_abs(0.5), ABS_MAX // 2 + 1)  # round(16383.5)
        self.assertEqual(steering_to_abs(-0.5), -(ABS_MAX // 2 + 1))

    def test_saturacao(self):
        self.assertEqual(steering_to_abs(2.0), ABS_MAX)
        self.assertEqual(steering_to_abs(-9.0), -ABS_MAX)

    def test_continuo_nao_e_tecla(self):
        vals = {steering_to_abs(v / 100.0) for v in range(-100, 101)}
        self.assertGreater(len(vals), 100)  # granularidade analógica


class TestUinputGamepadFake(unittest.TestCase):
    def _pad(self) -> tuple[UinputGamepad, FakeUI]:
        fakes = []

        def factory(**kwargs):
            fake = FakeUI(**kwargs)
            fakes.append(fake)
            return fake

        pad = UinputGamepad(ui_factory=factory)
        pad.start()
        return pad, fakes[0]

    def test_perfil_xbox(self):
        pad, fake = self._pad()
        self.assertEqual(fake.kwargs["vendor"], 0x045E)
        self.assertEqual(fake.kwargs["product"], 0x028E)
        from evdev import ecodes

        self.assertIn(ecodes.EV_ABS, fake.kwargs["events"])
        self.assertIn(ecodes.EV_KEY, fake.kwargs["events"])
        pad.stop()
        self.assertTrue(fake.closed)

    def test_publica_eixo(self):
        from evdev import ecodes

        pad, fake = self._pad()
        fake.events.clear()
        pad.publish(WheelState(steering=0.5))
        axis = [e for e in fake.events if e[0] == ecodes.EV_ABS and e[1] == ecodes.ABS_X]
        self.assertEqual(len(axis), 1)
        self.assertEqual(axis[0][2], steering_to_abs(0.5))
        self.assertGreaterEqual(fake.syncs, 1)
        pad.stop()

    def test_publica_gatilhos(self):
        from evdev import ecodes
        from outputs.uinput_gamepad import pedal_to_trigger as p2t

        pad, fake = self._pad()
        fake.events.clear()
        pad.publish(WheelState(brake=0.5, accel=1.0))
        trig = {e[1]: e[2] for e in fake.events if e[0] == ecodes.EV_ABS}
        self.assertEqual(trig[ecodes.ABS_Z], p2t(0.5))
        self.assertEqual(trig[ecodes.ABS_RZ], 255)
        pad.stop()

    def test_botoes_up_down(self):
        from evdev import ecodes

        pad, fake = self._pad()
        fake.events.clear()
        pad.publish(WheelState(gear_up=True, gear_down=False))
        keys = {(e[1], e[2]) for e in fake.events if e[0] == ecodes.EV_KEY}
        self.assertIn((ecodes.BTN_EAST, 1), keys)  # B = UP
        # Soltar gera transição 1→0.
        fake.events.clear()
        pad.publish(WheelState(gear_up=False, gear_down=True))
        keys = {(e[1], e[2]) for e in fake.events if e[0] == ecodes.EV_KEY}
        self.assertIn((ecodes.BTN_EAST, 0), keys)
        self.assertIn((ecodes.BTN_SOUTH, 1), keys)  # A = DOWN
        pad.stop()

    def test_sem_start_falha(self):
        with self.assertRaises(RuntimeError):
            UinputGamepad(ui_factory=FakeUI).publish(WheelState())

    def test_stop_solta_botoes(self):
        from evdev import ecodes

        pad, fake = self._pad()
        pad.publish(WheelState(gear_up=True))
        fake.events.clear()
        pad.stop()
        keys = {(e[1], e[2]) for e in fake.events if e[0] == ecodes.EV_KEY}
        self.assertIn((ecodes.BTN_EAST, 0), keys)


class TestPreflight(unittest.TestCase):
    def test_retorna_lista(self):
        # Neste ambiente evdev + /dev/uinput existem → sem problemas.
        self.assertEqual(check_gamepad_requirements(), [])


if __name__ == "__main__":
    unittest.main()
