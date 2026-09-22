"""Testes do câmbio sequencial, embreagem, modo e freio de mão."""

import importlib.util
import unittest

import pytest

from core.steering import SteeringProcessor
from inputs.microbit_serial import parse_line

HAS_EVDEV = importlib.util.find_spec("evdev") is not None
needs_evdev = pytest.mark.skipif(not HAS_EVDEV, reason="sem evdev nesta máquina")


class TestParseShifter(unittest.TestCase):
    def test_shift(self):
        self.assertEqual(parse_line("SHIFT:UP").shift, "UP")
        self.assertEqual(parse_line("shift:down").shift, "DOWN")

    def test_shift_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("SHIFT:SIDEWAYS")

    def test_mode(self):
        self.assertEqual(parse_line("MODE:AUTO").mode, "AUTO")
        self.assertEqual(parse_line("MODE:MANUAL").mode, "MANUAL")

    def test_mode_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("MODE:TURBO")

    def test_handbrake(self):
        self.assertTrue(parse_line("HANDBRAKE:ON").handbrake)
        self.assertFalse(parse_line("HANDBRAKE:OFF").handbrake)

    def test_handbrake_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("HANDBRAKE:MAYBE")

    def test_clutch(self):
        r = parse_line("CLUTCH:28")
        assert r is not None
        self.assertAlmostEqual(r.clutch_mm, 28.0)


class TestShifterGating(unittest.TestCase):
    def _pressed_clutch(self, p: SteeringProcessor) -> None:
        for _ in range(6):  # converge EMA com embreagem no fundo
            p.update_pedals(None, None, 15.0)

    def test_aceita_com_embreagem(self):
        p = SteeringProcessor()
        self._pressed_clutch(p)
        self.assertTrue(p.shift_event("UP"))
        snap = p.snapshot()
        self.assertTrue(snap.shift_up)
        self.assertEqual(snap.shift_up_count, 1)

    def test_rejeita_sem_embreagem(self):
        p = SteeringProcessor()
        p.update_pedals(50.0, 50.0, 60.0)  # tudo solto
        self.assertFalse(p.shift_event("UP"))
        self.assertEqual(p.snapshot().shift_up_count, 0)

    def test_rejeita_no_automatico(self):
        p = SteeringProcessor()
        self._pressed_clutch(p)
        p.set_mode(True)
        self.assertFalse(p.shift_event("DOWN"))
        self.assertEqual(p.snapshot().shift_down_count, 0)

    def test_manual_libera(self):
        p = SteeringProcessor()
        self._pressed_clutch(p)
        p.set_mode(True)
        p.set_mode(False)
        self.assertTrue(p.shift_event("DOWN"))

    def test_invalido(self):
        p = SteeringProcessor()
        with self.assertRaises(ValueError):
            p.shift_event("RE")


class TestModeHandbrake(unittest.TestCase):
    def test_padrao_manual_solto(self):
        snap = SteeringProcessor().snapshot()
        self.assertFalse(snap.auto_mode)
        self.assertFalse(snap.handbrake)

    def test_toggle(self):
        p = SteeringProcessor()
        self.assertTrue(p.set_mode(True))
        self.assertTrue(p.snapshot().auto_mode)
        self.assertTrue(p.set_handbrake(True))
        self.assertTrue(p.snapshot().handbrake)
        self.assertFalse(p.set_handbrake(False))


class TestShifterOutputs(unittest.TestCase):
    def test_gamepad_shift_e_clutch(self):
        pytest.importorskip("evdev")
        from evdev import ecodes

        from core.models import WheelState
        from outputs.uinput_gamepad import UinputGamepad, pedal_to_trigger
        from tests.test_gamepad import FakeUI

        fakes = []

        def factory(**kwargs):
            fake = FakeUI(**kwargs)
            fakes.append(fake)
            return fake

        pad = UinputGamepad(ui_factory=factory)
        pad.start()
        fakes[0].events.clear()
        pad.publish(WheelState(shift_up=True, shift_down=True, clutch=0.5,
                               handbrake=True))
        keys = {(e[1], e[2]) for e in fakes[0].events if e[0] == ecodes.EV_KEY}
        self.assertIn((ecodes.BTN_TR, 1), keys)
        self.assertIn((ecodes.BTN_TL, 1), keys)
        self.assertIn((ecodes.BTN_EAST, 1), keys)  # freio de mão
        trig = {e[1]: e[2] for e in fakes[0].events if e[0] == ecodes.EV_ABS}
        self.assertEqual(trig[ecodes.ABS_THROTTLE], pedal_to_trigger(0.5))
        pad.stop()

    def test_keyboard_shift_handbrake(self):
        from outputs.keyboard_windows import KeyMap

        km = KeyMap.from_dict({"shift_up": "e", "handbrake": "space"})
        self.assertEqual(km.shift_up, "e")
        self.assertEqual(km.shift_down, "q")  # padrão mantido


if __name__ == "__main__":
    unittest.main()
