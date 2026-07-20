from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from modbus_v7_codec import V7CodecError, decode_words, encode_words


class ModbusV7CodecTests(unittest.TestCase):
    def test_big_endian_round_trip(self) -> None:
        for value, data_type in ((-12, "int16"), (0x12345678, "uint32"), (123.5, "float32"), (2**48 + 7, "uint64")):
            decoded = decode_words(encode_words(value, data_type), data_type)
            self.assertAlmostEqual(decoded, value, places=4) if data_type == "float32" else self.assertEqual(decoded, value)

    def test_boolean_register_uses_zero_or_one(self) -> None:
        self.assertEqual(encode_words(True, "bool"), [1])
        self.assertEqual(encode_words(False, "bool"), [0])

    def test_rejects_bad_length_and_non_finite_float(self) -> None:
        with self.assertRaises(V7CodecError):
            decode_words([1], "uint32")
        with self.assertRaises(V7CodecError):
            encode_words(float("nan"), "float32")


if __name__ == "__main__":
    unittest.main()
