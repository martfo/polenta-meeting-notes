// Denied permissions map to a clear state the UI shows, never a silent
// failure.

import Foundation

public enum PermissionStatus: Sendable {
    case granted, denied, undetermined
}

public enum CaptureReadiness: Equatable, Sendable {
    case ready
    /// The system will ask for consent when recording starts.
    case awaitingConsent
    /// Something is switched off; the message says what and where to fix it.
    case blocked(String)

    public static func evaluate(microphone: PermissionStatus, systemAudio: PermissionStatus) -> CaptureReadiness {
        var problems: [String] = []
        if microphone == .denied {
            problems.append(
                "Microphone access is turned off. Allow it in System Settings, "
                + "Privacy and Security, Microphone, then try again.")
        }
        if systemAudio == .denied {
            problems.append(
                "System audio recording is turned off, so the other people on "
                + "a call cannot be captured. Allow it in System Settings, "
                + "Privacy and Security, Screen and System Audio Recording.")
        }
        if !problems.isEmpty {
            return .blocked(problems.joined(separator: "\n\n"))
        }
        if microphone == .undetermined || systemAudio == .undetermined {
            return .awaitingConsent
        }
        return .ready
    }
}
