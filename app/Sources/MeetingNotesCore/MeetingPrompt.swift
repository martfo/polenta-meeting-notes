// The floating "record this meeting?" pop-up: where it sits and whether it is
// on. The panel itself is AppKit and lives in the app; the decisions it makes
// are here, where they can be tested.

import CoreGraphics
import Foundation

public enum MeetingPromptPreference {
    /// UserDefaults key for showing the pop-up. On unless turned off: a
    /// missed prompt is a lost recording, so the default errs towards asking.
    public static let enabledKey = "meetingPromptEnabled"

    public static func isEnabled(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: enabledKey) as? Bool ?? true
    }
}

public enum PromptPlacement {
    /// The top-right corner of the usable screen area (below the menu bar,
    /// clear of the Dock), inset by a margin: where macOS shows its own
    /// notifications, so the eye already looks there and the call's window,
    /// usually centred, stays uncovered.
    public static func topRightOrigin(
        size: CGSize, visibleFrame: CGRect, margin: CGFloat = 12
    ) -> CGPoint {
        CGPoint(
            x: visibleFrame.maxX - size.width - margin,
            y: visibleFrame.maxY - size.height - margin)
    }
}
