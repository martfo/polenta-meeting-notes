import Foundation
import Testing
@testable import MeetingNotesCore

struct AutoStopTests {
    let start = Date(timeIntervalSinceReferenceDate: 1_000_000)
    var maxStopAt: Date { start.addingTimeInterval(180 * 60) }

    @Test("an overrunning meeting keeps recording while the call is live")
    func test_keeps_recording_past_scheduled_end_when_active() {
        let scheduledEnd = start.addingTimeInterval(15 * 60)
        // Ten minutes past the scheduled end, but the call was audible 30s ago.
        let decision = AutoStop.decide(
            now: start.addingTimeInterval(25 * 60),
            windDownAt: scheduledEnd, maxStopAt: maxStopAt,
            secondsSinceSystemActivity: 30, quietThreshold: 5 * 60)
        #expect(decision == .keepRecording)
    }

    @Test("the call ending after the scheduled end stops the recording")
    func test_stops_when_quiet_past_scheduled_end() {
        let scheduledEnd = start.addingTimeInterval(15 * 60)
        let decision = AutoStop.decide(
            now: start.addingTimeInterval(25 * 60),
            windDownAt: scheduledEnd, maxStopAt: maxStopAt,
            secondsSinceSystemActivity: 6 * 60, quietThreshold: 5 * 60)
        #expect(decision == .stop(reason: "the call ended"))
    }

    @Test("a lull before the scheduled end never ends the meeting")
    func test_quiet_before_scheduled_end_keeps_recording() {
        let scheduledEnd = start.addingTimeInterval(30 * 60)
        // Only 10 minutes in, silent for 6 minutes, but the meeting is not
        // scheduled to end yet, so a quiet stretch must not end it.
        let decision = AutoStop.decide(
            now: start.addingTimeInterval(10 * 60),
            windDownAt: scheduledEnd, maxStopAt: maxStopAt,
            secondsSinceSystemActivity: 6 * 60, quietThreshold: 5 * 60)
        #expect(decision == .keepRecording)
    }

    @Test("the maximum length stops even a still-active recording")
    func test_max_length_is_a_hard_cap() {
        let decision = AutoStop.decide(
            now: start.addingTimeInterval(181 * 60),
            windDownAt: .distantFuture, maxStopAt: maxStopAt,
            secondsSinceSystemActivity: 1, quietThreshold: 5 * 60)
        #expect(decision == .stop(reason: "the maximum recording length was reached"))
    }

    @Test("with no calendar end, only the max length stops it")
    func test_no_calendar_end_relies_on_max_cap() {
        let decision = AutoStop.decide(
            now: start.addingTimeInterval(60 * 60),
            windDownAt: .distantFuture, maxStopAt: maxStopAt,
            secondsSinceSystemActivity: 60 * 60, quietThreshold: 5 * 60)
        #expect(decision == .keepRecording)  // silent, but no scheduled end to wind down from
    }
}
