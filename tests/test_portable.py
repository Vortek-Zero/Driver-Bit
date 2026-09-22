"""Testes da saída teclado Windows + autodetecção (sem hardware/Windows)."""

import unittest

from inputs.autodetect import classify_lines, pick_port, MicrobitPort
from outputs.keyboard_windows import KeyMap, KeyPwm, parse_key


class TestParseKey(unittest.TestCase):
    def test_setas_sao_estendidas(self):
        vk, ext = parse_key("left")
        self.assertEqual(vk, 0x25)
        self.assertTrue(ext)

    def test_letras(self):
        vk, ext = parse_key("A")
        self.assertEqual(vk, 0x41)
        self.assertFalse(ext)

    def test_case_insensitive(self):
        self.assertEqual(parse_key("Space"), parse_key("space"))

    def test_invalida(self):
        with self.assertRaises(ValueError):
            parse_key("turbo")


class TestKeyMap(unittest.TestCase):
    def test_padrao(self):
        km = KeyMap()
        self.assertEqual(km.left, "left")
        self.assertEqual(km.accel, "up")

    def test_dict_parcial(self):
        km = KeyMap.from_dict({"left": "a", "right": "d"})
        self.assertEqual(km.left, "a")
        self.assertEqual(km.right, "d")
        self.assertEqual(km.accel, "up")  # resto mantém padrão

    def test_tecla_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            KeyMap.from_dict({"left": "turbo"})

    def test_campo_desconhecido_ignorado(self):
        km = KeyMap.from_dict({"nitro": "space", "left": "a"})
        self.assertEqual(km.left, "a")  # resto segue padrão


class TestKeyPwm(unittest.TestCase):
    def _duty(self, value: float, ticks: int = 60) -> float:
        pwm = KeyPwm()
        return sum(pwm.update(value) for _ in range(ticks)) / ticks

    def test_zero_e_um(self):
        self.assertEqual(self._duty(0.0), 0.0)
        self.assertEqual(self._duty(1.0), 1.0)

    def test_proporcional(self):
        self.assertAlmostEqual(self._duty(0.5), 0.5, places=1)
        self.assertGreater(self._duty(0.8), self._duty(0.3))

    def test_zona_morta(self):
        self.assertEqual(self._duty(0.05), 0.0)


class TestClassifyLines(unittest.TestCase):
    def test_hub(self):
        self.assertEqual(classify_lines(["BRAKE:34", "STEER:90"]), "hub")
        self.assertEqual(classify_lines(["ACCEL:41"]), "hub")

    def test_wheel(self):
        self.assertEqual(classify_lines(["STEER:90", "GEAR:UP"]), "wheel")

    def test_unknown(self):
        self.assertEqual(classify_lines([]), "unknown")
        self.assertEqual(classify_lines(["FREIO:34cm", "hello"]), "unknown")

    def test_case_insensitive(self):
        self.assertEqual(classify_lines(["steer:10"]), "wheel")


class TestPickPort(unittest.TestCase):
    def test_prefere_hub(self):
        ports = [
            MicrobitPort("COM9", role="wheel"),
            MicrobitPort("COM7", role="hub"),
        ]
        self.assertEqual(pick_port(ports), "COM7")

    def test_wheel_se_so_houver(self):
        self.assertEqual(pick_port([MicrobitPort("COM9", role="wheel")]), "COM9")

    def test_primeira_quando_desconhecido(self):
        ports = [MicrobitPort("COM7"), MicrobitPort("COM9")]
        self.assertEqual(pick_port(ports), "COM7")

    def test_vazio(self):
        self.assertIsNone(pick_port([]))


class TestFindSerialPort(unittest.TestCase):
    def test_explicita_passa_direto(self):
        from inputs.microbit_serial import find_serial_port

        self.assertEqual(find_serial_port("COM7"), "COM7")
        self.assertEqual(find_serial_port("/dev/ttyACM0"), "/dev/ttyACM0")

    def test_auto_sem_placa_retorna_none(self):
        from unittest import mock

        from inputs import microbit_serial

        with mock.patch("inputs.autodetect.find_microbits", return_value=[]):
            self.assertIsNone(microbit_serial.find_serial_port("auto"))


if __name__ == "__main__":
    unittest.main()
