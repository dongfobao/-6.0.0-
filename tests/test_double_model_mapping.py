from pathlib import Path
import importlib.util
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_double_channel_digital_twin_glb",
    ROOT / "scripts" / "build_double_channel_digital_twin_glb.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DoubleModelMappingTests(unittest.TestCase):
    def test_rendered_sensor_plugs_are_mirrored_to_front_facing_sides(self):
        source_low_x_low = np.array([7.8, 12.6, -31.5], dtype=np.float32)
        source_low_x_high = np.array([19.4, 30.6, -13.5], dtype=np.float32)
        source_high_x_low = np.array([60.8, 12.6, -31.5], dtype=np.float32)
        source_high_x_high = np.array([72.4, 30.6, -13.5], dtype=np.float32)

        self.assertEqual(
            MODULE.classify_part(source_low_x_low, source_low_x_high),
            ("valve_or_sensor", "right_humidity_sensor", 2),
        )
        self.assertEqual(
            MODULE.classify_part(source_high_x_low, source_high_x_high),
            ("valve_or_sensor", "left_humidity_sensor", 1),
        )

    def test_rendered_process_columns_are_mirrored_to_front_facing_channels(self):
        left_low = np.array([-153.3, -68.4, 1.5], dtype=np.float32)
        left_high = np.array([26.6, 111.6, 265.5], dtype=np.float32)
        right_low = np.array([46.6, -68.4, 1.5], dtype=np.float32)
        right_high = np.array([226.6, 111.6, 265.5], dtype=np.float32)

        self.assertEqual(MODULE.classify_part(left_low, left_high)[1:], ("main_process_glass_2", 2))
        self.assertEqual(MODULE.classify_part(right_low, right_high)[1:], ("main_process_glass_1", 1))

    def test_oil_cups_keep_the_same_mirrored_channel_mapping(self):
        rendered_left_low = np.array([-100.0, -100.0, 270.0], dtype=np.float32)
        rendered_left_high = np.array([-25.0, -25.0, 350.0], dtype=np.float32)
        rendered_right_low = np.array([99.0, -100.0, 270.0], dtype=np.float32)
        rendered_right_high = np.array([174.0, -25.0, 350.0], dtype=np.float32)

        self.assertEqual(
            MODULE.classify_part(rendered_left_low, rendered_left_high),
            ("outer_shell", "oil_cup_2", 2),
        )
        self.assertEqual(
            MODULE.classify_part(rendered_right_low, rendered_right_high),
            ("outer_shell", "oil_cup_1", 1),
        )


if __name__ == "__main__":
    unittest.main()
