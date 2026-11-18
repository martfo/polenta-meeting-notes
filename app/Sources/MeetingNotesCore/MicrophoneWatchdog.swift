// Keeps the microphone recording for the whole meeting. macOS stops an audio
// engine without warning when its input changes under it: AirPods switching
// to their call mode as a call app takes the microphone, a device plugged in
// or removed, a sample rate that has not settled when recording starts. Left
// alone, the owner's side of the meeting is silently lost. The watchdog
// notices when microphone audio stops arriving, asks for the microphone to be
// restarted (not too often), and says when to warn the person. Pure logic,
// decided on a timer tick, so it is tested without real audio.

import Foundation

public struct MicrophoneVerdict: Equatable {
    /// Restart the microphone now.
    public let restart: Bool
    /// Tell the person their microphone is not being recorded.
    public let warn: Bool

    public init(restart: Bool, warn: Bool) {
        self.restart = restart
        self.warn = warn
    }
}

public enum MicrophoneWatchdog {
    /// Buffers arrive several times a second, even when the room is silent,
    /// so a gap this long means the microphone has stopped.
    public static let stallSeconds: TimeInterval = 2
    /// The least time between restarts, so a device that keeps failing is
    /// retried steadily rather than in a tight loop.
    public static let retrySeconds: TimeInterval = 3
    /// A gap this long is shown to the person; a restart that recovers within
    /// it (the usual case) passes without alarm.
    public static let warnSeconds: TimeInterval = 6

    /// Decide, at `now`, what to do about the microphone.
    ///
    /// - `lastBufferAt`: when microphone audio last arrived, or nil if none
    ///   has arrived since recording started.
    /// - `startedAt`: when recording started.
    /// - `lastRestartAt`: when the microphone was last (re)started.
    public static func check(
        now: TimeInterval,
        lastBufferAt: TimeInterval?,
        startedAt: TimeInterval,
        lastRestartAt: TimeInterval
    ) -> MicrophoneVerdict {
        let silentFor = now - max(lastBufferAt ?? startedAt, startedAt)
        let stalled = silentFor >= stallSeconds
        let restartDue = now - lastRestartAt >= retrySeconds
        return MicrophoneVerdict(restart: stalled && restartDue, warn: silentFor >= warnSeconds)
    }
}
