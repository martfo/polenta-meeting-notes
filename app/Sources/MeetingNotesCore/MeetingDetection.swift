// Meeting detection rules. Pure logic: a due calendar meeting, or a call app
// starting to use the microphone, produces a prompt to start recording, never
// a recording. (The backend's calendar/detection.py is an older mirror kept
// for its AC tests; the app does not use it.)

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

    /// Apps that carry calls, by bundle identifier, and the name to show.
    ///
    /// Matched as a prefix, because an app's audio often runs in a helper
    /// process with its own identifier (new Teams captures the microphone in
    /// com.microsoft.teams2.modulehost, Chrome in com.google.Chrome.helper).
    /// Browsers are here for web calls (Google Meet, Teams or Zoom in a tab):
    /// a browser taking the microphone is nearly always one.
    ///
    /// Anything not listed is ignored, which is what keeps a machine quiet
    /// where something holds the microphone all day: a virtual desktop client
    /// (a remote-desktop client), another recorder (Granola), or this app itself.
    public static let callApps: [(bundlePrefix: String, name: String)] = [
        ("com.microsoft.teams2", "Microsoft Teams"),  // new Teams
        ("com.microsoft.teams", "Microsoft Teams"),   // classic Teams
        ("us.zoom.xos", "Zoom"),
        ("com.tinyspeck.slackmacgap", "Slack"),
        ("com.cisco.webexmeetingsapp", "Webex"),
        ("com.webex.meetingmanager", "Webex"),
        ("com.apple.FaceTime", "FaceTime"),
        ("com.apple.avconferenced", "FaceTime"),
        ("com.amazon.Amazon-Chime", "Amazon Chime"),
        ("com.hnc.Discord", "Discord"),
        ("com.google.Chrome", "Google Chrome"),
        ("com.microsoft.edgemac", "Microsoft Edge"),
        ("company.thebrowser.Browser", "Arc"),
        ("com.brave.Browser", "Brave"),
        ("org.mozilla.firefox", "Firefox"),
        ("com.apple.Safari", "Safari"),
        // Safari and other WebKit apps capture the microphone in a shared
        // WebKit process rather than their own.
        ("com.apple.WebKit.GPU", "Safari"),
    ]

    /// The call app a process belongs to, or nil for anything that is not one.
    /// A prefix must end at a component boundary, so com.apple.FaceTime does
    /// not also claim a hypothetical com.apple.FaceTimeHelperX.
    public static func callAppName(forBundleID bundleID: String) -> String? {
        for app in callApps {
            if bundleID == app.bundlePrefix || bundleID.hasPrefix(app.bundlePrefix + ".") {
                return app.name
            }
        }
        return nil
    }

    /// The call apps among the processes currently capturing audio input.
    public static func callAppsCapturing(bundleIDs: [String]) -> Set<String> {
        Set(bundleIDs.compactMap(callAppName(forBundleID:)))
    }

    /// The call app to prompt for, if one has just started using the
    /// microphone since the last look.
    ///
    /// Detected per app and on the change: a call app that was already
    /// capturing last time is a call already offered (or already refused),
    /// and an app merely running never counts. Where several start together
    /// the choice is stable (alphabetical), so the prompt does not flicker.
    public static func callPromptTrigger(
        capturing: Set<String>, previouslyCapturing: Set<String>
    ) -> String? {
        capturing.subtracting(previouslyCapturing).sorted().first
    }
}
