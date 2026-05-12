"""
Tests para conversión de timecodes.
"""
import pytest
from basketball_highlights.utils import seconds_to_timecode, timecode_to_seconds


class TestSecondsToTimecode:
    def test_zero(self):
        assert seconds_to_timecode(0.0) == "00:00:00.000"

    def test_one_minute(self):
        assert seconds_to_timecode(60.0) == "00:01:00.000"

    def test_one_hour(self):
        assert seconds_to_timecode(3600.0) == "01:00:00.000"

    def test_complex(self):
        result = seconds_to_timecode(734.2)
        assert result.startswith("00:12:14")

    def test_with_milliseconds(self):
        result = seconds_to_timecode(734.567)
        assert "567" in result


class TestTimecodeToSeconds:
    def test_simple_seconds(self):
        assert timecode_to_seconds("45.5") == 45.5

    def test_mm_ss(self):
        assert timecode_to_seconds("01:30") == 90.0

    def test_hh_mm_ss(self):
        assert timecode_to_seconds("01:00:00") == 3600.0

    def test_with_fractional(self):
        assert abs(timecode_to_seconds("00:12:14.567") - 734.567) < 0.001


class TestRoundtrip:
    def test_roundtrip(self):
        original = 1234.567
        tc = seconds_to_timecode(original)
        recovered = timecode_to_seconds(tc)
        assert abs(recovered - original) < 0.001
