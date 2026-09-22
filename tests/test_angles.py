"""Testes do wrap-around e helpers de ângulo (stdlib unittest)."""

import unittest

from core.angles import apply_deadzone, normalize_compass, relative_angle


class TestNormalizeCompass(unittest.TestCase):
    def test_faixa(self):
        for v in (-720, -1, 0, 359, 360, 361, 720.5):
            self.assertGreaterEqual(normalize_compass(v), 0.0)
            self.assertLess(normalize_compass(v), 360.0)

    def test_valores(self):
        self.assertAlmostEqual(normalize_compass(0), 0.0)
        self.assertAlmostEqual(normalize_compass(359), 359.0)
        self.assertAlmostEqual(normalize_compass(360), 0.0)
        self.assertAlmostEqual(normalize_compass(-10), 350.0)


class TestRelativeAngle(unittest.TestCase):
    def test_centro_e_zero(self):
        self.assertAlmostEqual(relative_angle(180, 180), 0.0)

    def test_direita_positiva_esquerda_negativa(self):
        self.assertAlmostEqual(relative_angle(190, 180), 10.0)
        self.assertAlmostEqual(relative_angle(170, 180), -10.0)

    def test_wrap_359_para_0(self):
        # O caso crítico pedido: girar de 359° para 5° são +6°, não −354°.
        self.assertAlmostEqual(relative_angle(5, 355), 10.0)
        self.assertAlmostEqual(relative_angle(355, 5), -10.0)
        self.assertAlmostEqual(relative_angle(0, 359), 1.0)
        self.assertAlmostEqual(relative_angle(359, 0), -1.0)

    def test_limites(self):
        r = relative_angle(0, 180)
        self.assertGreaterEqual(r, -180.0)
        self.assertLess(r, 180.0)


class TestDeadzone(unittest.TestCase):
    def test_dentro_morre(self):
        self.assertEqual(apply_deadzone(0.04, 0.05), 0.0)
        self.assertEqual(apply_deadzone(-0.04, 0.05), 0.0)

    def test_fora_reescala(self):
        # borda → 0; fundo de curso continua 1.0
        self.assertAlmostEqual(apply_deadzone(0.05, 0.05), 0.0)
        self.assertAlmostEqual(apply_deadzone(1.0, 0.05), 1.0)
        self.assertAlmostEqual(apply_deadzone(-1.0, 0.05), -1.0)
        meio = apply_deadzone(0.525, 0.05)
        self.assertAlmostEqual(meio, 0.5)

    def test_zero_desliga(self):
        self.assertAlmostEqual(apply_deadzone(0.3, 0.0), 0.3)


if __name__ == "__main__":
    unittest.main()
