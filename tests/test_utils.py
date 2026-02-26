"""Unit tests for src.utils."""

import unittest
from src.utils import sanitize_nickname, is_valid_solana_address, is_valid_address


class TestSanitizeNickname(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_nickname(""), "")
        self.assertEqual(sanitize_nickname(None), "")
        self.assertEqual(sanitize_nickname("   "), "")

    def test_strips_whitespace(self):
        self.assertEqual(sanitize_nickname("  BigTrader  "), "BigTrader")

    def test_removes_angle_brackets(self):
        self.assertEqual(sanitize_nickname("<script>"), "script")
        self.assertEqual(sanitize_nickname("Trader>"), "Trader")

    def test_escapes_ampersand(self):
        self.assertEqual(sanitize_nickname("A & B"), "A &amp; B")

    def test_limits_length(self):
        long_name = "A" * 100
        self.assertEqual(len(sanitize_nickname(long_name)), 50)

    def test_non_string_returns_empty(self):
        self.assertEqual(sanitize_nickname(123), "")
        self.assertEqual(sanitize_nickname([]), "")


class TestIsValidSolanaAddress(unittest.TestCase):
    def test_valid_base58_32_chars(self):
        self.assertTrue(is_valid_solana_address("11111111111111111111111111111111"))

    def test_valid_base58_44_chars(self):
        addr = "So11111111111111111111111111111111111111112"
        self.assertTrue(is_valid_solana_address(addr))

    def test_invalid_too_short(self):
        self.assertFalse(is_valid_solana_address("short"))

    def test_invalid_contains_zero(self):
        self.assertFalse(is_valid_solana_address("0" * 32))

    def test_invalid_contains_lowercase_l(self):
        self.assertFalse(is_valid_solana_address("l" + "1" * 31))

    def test_empty_returns_false(self):
        self.assertFalse(is_valid_solana_address(""))
        self.assertFalse(is_valid_solana_address(None))

    def test_strips_whitespace(self):
        addr = "So11111111111111111111111111111111111111112"
        self.assertTrue(is_valid_solana_address("  " + addr + "  "))


class TestIsValidAddress(unittest.TestCase):
    def test_valid_eth_address(self):
        self.assertTrue(is_valid_address("0x" + "a" * 40))
        self.assertTrue(is_valid_address("0x" + "A" * 40))

    def test_invalid_no_prefix(self):
        self.assertFalse(is_valid_address("a" * 40))

    def test_invalid_wrong_length(self):
        self.assertFalse(is_valid_address("0x" + "a" * 39))
        self.assertFalse(is_valid_address("0x" + "a" * 41))

    def test_empty_returns_false(self):
        self.assertFalse(is_valid_address(""))
        self.assertFalse(is_valid_address(None))


if __name__ == "__main__":
    unittest.main()
