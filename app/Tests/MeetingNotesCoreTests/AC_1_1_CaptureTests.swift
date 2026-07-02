// Test inventory for sections 1.0 (app side) and 1.1. Stubs are filled in as
// slice 1.1 is built and must stay green after.

import Testing
@testable import MeetingNotesCore

struct AC_1_1_CaptureTests {
    @Test("AC-1.1-a tap description is global, private, unmuted, with a uuid",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_a_tap_description_factory() {}

    @Test("AC-1.1-b Info.plist carries both usage keys",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_b_info_plist_usage_keys() {}

    @Test("AC-1.1-c mixer produces a single 16 kHz mono WAV of the right length",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_c_mixer_16k_mono() {}

    @Test("AC-1.1-d input levels for microphone and system audio",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_d_input_levels() {}

    @Test("AC-1.1-e chosen microphone saved and restored",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_e_microphone_preference() {}

    @Test("AC-1.1-f silent system audio flags the meeting as in-person",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_f_in_person_classifier() {}

    @Test("AC-1.1-g stop enqueues and a new recording can start at once",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_g_stop_enqueues_and_restarts() {}

    @Test("AC-1.1-h denied permissions map to a clear error state",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_1_h_permission_error_states() {}

    @Test("AC-1.0-f backend down at capture: audio kept, job pending, enqueued later",
          .disabled("stub: slice 1.1 not yet built"))
    func test_ac_1_0_f_backend_down_at_capture() {}
}
