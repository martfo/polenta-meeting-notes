"""Test inventory for the acceptance criteria in this file.

Stubs are filled in as their slice is built and must stay green after.
"""
import pytest

pytestmark = pytest.mark.pipeline


@pytest.mark.skip(reason="stub: pipeline tier, slice 1.2 not yet built")
def test_ac_1_2_a_segment_shape():
    ...

@pytest.mark.skip(reason="stub: pipeline tier, slice 1.2 not yet built")
def test_ac_1_2_b_word_timestamps_monotonic():
    ...

@pytest.mark.skip(reason="stub: pipeline tier, slice 1.2 not yet built")
def test_ac_1_2_c_two_speaker_labels():
    ...

@pytest.mark.skip(reason="stub: pipeline tier, slice 1.2 not yet built")
def test_ac_1_2_d_keyword_present():
    ...
