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

    /// Process names that mean a call is probably happening.
    public static let callAppNames: Set<String> = [
        "zoom.us", "Microsoft Teams", "Teams", "Slack", "FaceTime", "webexmta",
    ]

    public static func runningCallApp(processNames: [String]) -> String? {
        processNames.first { callAppNames.contains($0) }
    }
}
