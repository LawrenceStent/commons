"""R0: the golden master. Every run in RUNS must reproduce its fixture exactly, stream by stream."""

import pytest

from tests.golden.harness import RUNS, capture, first_difference, load

pytestmark = pytest.mark.golden


@pytest.mark.parametrize("name", sorted(RUNS))
def test_behaviour_is_unchanged(name):
    expected, actual = load(name), capture(name)
    for stream in ("postings", "telemetry", "activity", "told", "summary"):
        assert expected[stream] == actual[stream], f"{name} {stream} changed at {first_difference(expected[stream], actual[stream])}"
