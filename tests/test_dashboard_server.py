from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from dashboard_server import DashboardRequestHandler


class DashboardServerTests(unittest.TestCase):
    def test_series_query_accepts_seven_day_window(self):
        value = DashboardRequestHandler._query_int(
            {"windowMs": ["604800000"]},
            "windowMs",
            900000,
            10000,
            604800000,
        )

        self.assertEqual(value, 604800000)

    def test_integer_query_rejects_invalid_and_out_of_range_values(self):
        for raw in ("abc", "9", "604800001"):
            with self.assertRaises(ValueError):
                DashboardRequestHandler._query_int(
                    {"windowMs": [raw]}, "windowMs", 900000, 10000, 604800000,
                )


if __name__ == "__main__":
    unittest.main()
