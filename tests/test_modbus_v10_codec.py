from pathlib import Path
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from modbus_v10_codec import V10CodecError, decode_words, encode_words


class ModbusV10CodecTests(unittest.TestCase):
    def test_big_endian_roundtrip(self) -> None:
        for value, kind in ((65535, "uint16"), (-1234, "int16"), (0x12345678, "uint32"), (-1234567, "int32"), (0x123456789ABCDEF0, "uint64"), (36.25, "float32")):
            decoded = decode_words(encode_words(value, kind), kind)
            self.assertAlmostEqual(decoded, value, places=5) if kind == "float32" else self.assertEqual(decoded, value)

    def test_rejects_invalid_values_and_lengths(self) -> None:
        with self.assertRaises(V10CodecError): decode_words([1], "float32")
        with self.assertRaises(V10CodecError): decode_words([2], "bool")
        with self.assertRaises(V10CodecError): encode_words(math.nan, "float32")
        with self.assertRaises(V10CodecError): encode_words(65536, "uint16")


if __name__ == "__main__":
    unittest.main()
