// Meeting detection rules. Pure logic, mirrored by the backend's detection
// module: a due calendar meeting or a running call app produces a prompt to
// start recording, never a recording.

import Foundation

public enum MeetingDetection {
    /// A meeting is due from a few minutes before its start until well into
    /// it, so joining a call late still gets the offer. The window is
    /// deliberately generous, since a missed prompt means a lost recording.
    public static func isDue(
        start: Date, now: Date,
        lead: TimeInterval = 300, grace: TimeInterval = 1500
    ) -> Bool {
        start.timeIntervalSince(now) <= lead && now.timeIntervalSince(start) <= grace
    }

    /// Whether an event is happening right now, used to title a recording
    /// started by hand. True from just before the start until just after the
    /// end.
    public static func isHappeningNow(
        start: Date, end: Date, now: Date, margin: TimeInterval = 300
    ) -> Bool {
        now >= start.addingTimeInterval(-margin) && now <= end.addingTimeInterval(margin)
    }

    /// Apps that carry calls. Most of them run all day, so their presence
    /// alone means nothing.
    public static let callAppNames: Set<String> = [
        "zoom.us", "Microsoft Teams", "Teams", "Slack", "FaceTime", "webexmta",
    ]

    /// In a call, not merely running, detected on the change rather than the
    /// state: a prompt fires when the microphone becomes busy while a call
    /// app runs, or a call app appears while the microphone is busy. A
    /// steadily busy microphone (Siri listening, another resident app) never
    /// triggers on its own, so an idle Slack cannot keep prompting.
    public static func callPromptTrigger(
        processNames: [String], microphoneInUse: Bool,
        previousMicrophoneInUse: Bool?, previousCallApps: Set<String>
    ) -> String? {
        guard microphoneInUse else { return nil }
        let apps = processNames.filter { callAppNames.contains($0) }
        // The microphone just went live with a call app around.
        if previousMicrophoneInUse == false, let app = apps.first {
            return app
        }
        // A call app just appeared while the microphone is live.
        return apps.first { !previousCallApps.contains($0) }
    }
}
