import unittest

from trainer.api.ranges import ByteRange, RangeNotSatisfiable, parse_single_byte_range


class ByteRangeTest(unittest.TestCase):
    def test_parses_closed_open_and_suffix_byte_ranges(self):
        self.assertEqual(parse_single_byte_range("bytes=2-5", 10), ByteRange(2, 5))
        self.assertEqual(parse_single_byte_range("bytes=7-", 10), ByteRange(7, 9))
        self.assertEqual(parse_single_byte_range("bytes=-3", 10), ByteRange(7, 9))

    def test_parses_byte_range_unit_case_insensitively(self):
        self.assertEqual(parse_single_byte_range("Bytes=0-1", 10), ByteRange(0, 1))
        self.assertEqual(parse_single_byte_range("BYTES=0-1", 10), ByteRange(0, 1))

    def test_rejects_multiple_malformed_and_unsatisfiable_ranges(self):
        for value in (
            "bytes=0-1,4-5",
            "items=0-1",
            "bytes=8-3",
            "bytes=10-",
            "bytes=-0",
        ):
            with self.assertRaises(RangeNotSatisfiable):
                parse_single_byte_range(value, 10)

    def test_returns_none_without_a_range_header(self):
        self.assertIsNone(parse_single_byte_range(None, 10))

    def test_clamps_suffix_larger_than_object(self):
        self.assertEqual(parse_single_byte_range("bytes=-100", 10), ByteRange(0, 9))

    def test_rejects_whitespace_extra_units_non_decimal_and_non_positive_size(self):
        for value, size in (
            ("", 10),
            ("   ", 10),
            ("bytes= 1-2", 10),
            ("bytes=1-2 bytes=3-4", 10),
            ("bytes=-1-2", 10),
            ("bytes=a-b", 10),
            ("bytes=1-2", 0),
            ("bytes=1-2", -1),
        ):
            with self.assertRaises(RangeNotSatisfiable):
                parse_single_byte_range(value, size)

    def test_rejects_numeric_values_too_large_for_integer_conversion(self):
        with self.assertRaises(RangeNotSatisfiable):
            parse_single_byte_range("bytes=" + "9" * 5000 + "-", 10)


if __name__ == "__main__":
    unittest.main()
