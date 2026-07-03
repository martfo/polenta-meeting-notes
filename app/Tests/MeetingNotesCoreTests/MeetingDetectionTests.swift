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

    @Test("a call prompt fires on a change, never on a steady state")
    func test_call_app_detection() {
        let slack = ["Finder", "Slack", "Dock"]

        // Slack sitting idle in the Dock is not a call.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: slack, microphoneInUse: false,
            previousMicrophoneInUse: false, previousCallApps: ["Slack"]) == nil)

        // Joining a huddle: the microphone goes live with Slack around.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: slack, microphoneInUse: true,
            previousMicrophoneInUse: false, previousCallApps: ["Slack"]) == "Slack")

        // A machine where something holds the microphone all day: Slack
        // running is a steady state and never prompts by itself.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: slack, microphoneInUse: true,
            previousMicrophoneInUse: true, previousCallApps: ["Slack"]) == nil)

        // But Zoom launching into that steady busy state does prompt.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: slack + ["zoom.us"], microphoneInUse: true,
            previousMicrophoneInUse: true, previousCallApps: ["Slack"]) == "zoom.us")

        // The first sample after launch is a baseline, not a change.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: slack, microphoneInUse: true,
            previousMicrophoneInUse: nil, previousCallApps: ["Slack"]) == nil)

        // A busy microphone without a call app (dictation, say) never fires.
        #expect(MeetingDetection.callPromptTrigger(
            processNames: ["Finder", "Safari"], microphoneInUse: true,
            previousMicrophoneInUse: false, previousCallApps: []) == nil)
    }
}
