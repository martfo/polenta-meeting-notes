// Meeting detection rules. Pure logic, mirrored by the backend's detection
// module: a due calendar meeting or a running call app produces a prompt to
// start recording, never a recording.

import Foundation

public enum MeetingDetection {
    /// A meeting is due from shortly before its start until a grace period
    /// after it, so joining a call late still gets the offer.
    public static func isDue(
        start: Date, now: Date,
        lead: TimeInterval = 120, grace: TimeInterval = 600
    ) -> Bool {
        start.timeIntervalSince(now) <= lead && now.timeIntervalSince(start) <= grace
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
