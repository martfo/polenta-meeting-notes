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

    /// In a call, not merely running: a call app counts only while something
    /// is actually holding the microphone open, which every live call does,
    /// muted or not.
    public static func runningCallApp(processNames: [String], microphoneInUse: Bool) -> String? {
        guard microphoneInUse else { return nil }
        return processNames.first { callAppNames.contains($0) }
    }
}
