"""Test inventory for the acceptance criteria in this file.

Stubs are filled in as their slice is built and must stay green after.
"""
import pytest

pytestmark = pytest.mark.manual_hardware


@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_1_1_i_real_capture_prompts_and_both_sources():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_1_8_c_reveal_opens_finder():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_3_1_e_first_run_provisions_backend():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_3_3_b_codesign_verify():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_3_3_c_permissions_persist_across_rebuild():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_3_4_c_drag_install_and_right_click_open():
    ...

@pytest.mark.skip(reason="manual-hardware: run from the written checklist on a real Mac")
def test_ac_3_5_b_new_mac_flow_end_to_end():
    ...
