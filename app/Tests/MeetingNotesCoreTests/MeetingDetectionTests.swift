// Detection rules for section 2.2, app side. The backend's AC tests cover
// the same rules; these keep the Swift mirror honest.

import Foundation
import Testing
@testable import MeetingNotesCore

struct MeetingDetectionTests {
    @Test("a meeting is due from just before its start until the grace runs out")
    func test_due_window() {
        let start = Date(timeIntervalSince1970: 10_000)
        #expect(MeetingDetection.isDue(start: start, now: start.addingTimeInterval(-60)))
        #expect(MeetingDetection.isDue(start: start, now: start))
        #expect(MeetingDetection.isDue(start: start, now: start.addingTimeInterval(500)))
        #expect(!MeetingDetection.isDue(start: start, now: start.addingTimeInterval(-3_000)), "not due yet")
        #expect(!MeetingDetection.isDue(start: start, now: start.addingTimeInterval(3_000)), "long started")
    }

    @Test("a call app only triggers while the microphone is actually held open")
    func test_call_app_detection() {
        // Slack sitting idle in the Dock is not a call.
        #expect(MeetingDetection.runningCallApp(
            processNames: ["Finder", "Slack", "Dock"], microphoneInUse: false) == nil)
        // Slack plus a live microphone is.
        #expect(MeetingDetection.runningCallApp(
            processNames: ["Finder", "Slack", "Dock"], microphoneInUse: true) == "Slack")
        #expect(MeetingDetection.runningCallApp(
            processNames: ["Finder", "zoom.us"], microphoneInUse: true) == "zoom.us")
        // A busy microphone without a call app (dictation, say) is not either.
        #expect(MeetingDetection.runningCallApp(
            processNames: ["Finder", "Safari"], microphoneInUse: true) == nil)
    }
}
