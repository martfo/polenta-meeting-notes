// When to stop a recording on its own. A calendar meeting's scheduled end is
// no longer a hard cutoff: past it, recording continues while the call is still
// audible and only stops once the audio has gone quiet (the call really ended)
// or the maximum length is reached. Pure logic, decided on a timer tick, so it
// is tested without real audio.

import Foundation

public enum AutoStopDecision: Equatable {
    case keepRecording
    case stop(reason: String)
}

public enum AutoStop {
    /// Decide, at `now`, whether the recording should stop.
    ///
    /// - `windDownAt`: the scheduled end (use `.distantFuture` when the
    ///   recording is not tied to a calendar meeting, so only the cap applies).
    ///   Before it, the recording never stops for quiet, so an early lull in a
    ///   meeting that is still going does not end it.
    /// - `maxStopAt`: the hard cap, a safety net for a forgotten recording.
    /// - `secondsSinceSystemActivity`: how long the call audio has been silent.
    /// - `quietThreshold`: how long that silence must last, past the scheduled
    ///   end, before the call is judged over.
    public static func decide(
        now: Date,
        windDownAt: Date,
        maxStopAt: Date,
        secondsSinceSystemActivity: TimeInterval,
        quietThreshold: TimeInterval
    ) -> AutoStopDecision {
        if now >= maxStopAt {
            return .stop(reason: "the maximum recording length was reached")
        }
        if now >= windDownAt, secondsSinceSystemActivity >= quietThreshold {
            return .stop(reason: "the call ended")
        }
        return .keepRecording
    }
}
