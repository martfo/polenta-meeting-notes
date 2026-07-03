// Input level readings for the microphone and system-audio streams, so the
// user can confirm both are being captured before relying on the recording.

import Foundation

public enum LevelMeter {
    /// Root-mean-square level of a buffer, 0 to 1.
    public static func level(of samples: [Float]) -> Float {
        guard !samples.isEmpty else { return 0 }
        let sumOfSquares = samples.reduce(Float(0)) { $0 + $1 * $1 }
        return min(1, (sumOfSquares / Float(samples.count)).squareRoot())
    }
}

/// Tracks whether the system-audio stream carried any signal. A recording
/// whose system audio stayed silent throughout is an in-person meeting.
public final class SourceClassifier {
    public static let silenceThreshold: Float = 0.001

    private var systemPeak: Float = 0

    public init() {}

    public func observeSystem(_ samples: [Float]) {
        for sample in samples {
            let magnitude = abs(sample)
            if magnitude > systemPeak { systemPeak = magnitude }
        }
    }

    public var source: MeetingSource {
        systemPeak > Self.silenceThreshold ? .online : .inPerson
    }
}

public enum MeetingSource: String, Sendable {
    case online = "online"
    case inPerson = "in-person"
}
