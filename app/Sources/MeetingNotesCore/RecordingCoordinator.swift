// Stopping a recording writes the audio into the vault and enqueues
// processing, then immediately allows a new recording. Capture never depends
// on the backend being up: if it is unreachable, the audio is kept and a
// pending job is recorded, then enqueued once the backend returns.

import Foundation

public struct PendingRecording: Codable, Equatable, Sendable {
    public let audioPath: String
    public let micPath: String?
    public let systemPath: String?
    public let title: String
    public let source: String
    public let recordedAt: Date

    public init(audioPath: String, micPath: String? = nil, systemPath: String? = nil,
                title: String, source: String, recordedAt: Date) {
        self.audioPath = audioPath
        self.micPath = micPath
        self.systemPath = systemPath
        self.title = title
        self.source = source
        self.recordedAt = recordedAt
    }
}

/// The microphone and system audio captured as separate channels, plus a
/// mixed stream for playback.
public struct CaptureResult: Sendable {
    public let mic: Data
    public let system: Data
    public let mixed: Data
    public let source: MeetingSource

    public init(mic: Data, system: Data, mixed: Data, source: MeetingSource) {
        self.mic = mic
        self.system = system
        self.mixed = mixed
        self.source = source
    }
}

/// What the coordinator needs from the backend: enqueue-and-return-at-once.
public protocol BackendEnqueuing {
    /// Throws when the backend is unreachable. micPath and systemPath carry
    /// the separate channels when the recording was captured as two streams.
    @discardableResult
    func importMeeting(audioPath: String, micPath: String?, systemPath: String?,
                       title: String, source: String) throws -> String
}

/// Pending recordings survive an app restart, so the store is a file.
public final class FilePendingJobStore {
    private let fileURL: URL

    public init(fileURL: URL) {
        self.fileURL = fileURL
    }

    public func all() -> [PendingRecording] {
        guard let data = try? Data(contentsOf: fileURL) else { return [] }
        return (try? JSONDecoder().decode([PendingRecording].self, from: data)) ?? []
    }

    public func replace(with jobs: [PendingRecording]) {
        let data = (try? JSONEncoder().encode(jobs)) ?? Data("[]".utf8)
        try? data.write(to: fileURL, options: .atomic)
    }

    public func add(_ job: PendingRecording) {
        replace(with: all() + [job])
    }
}

public enum StopOutcome: Equatable, Sendable {
    /// The backend accepted the meeting; processing is queued.
    case enqueued(meetingID: String)
    /// The backend was unreachable; the audio is safe and the job is pending.
    case pendingBackend
    /// The recording captured no audio, so no meeting was created.
    case emptyRecording
}

/// The smallest WAV that carries any audio. A 16 kHz mono PCM header is 44
/// bytes; anything at or below that captured nothing, so no meeting is made.
public let minimumRecordingBytes = 44

public final class RecordingCoordinator {
    public private(set) var isRecording = false

    private let capturesDirectory: URL
    private let backend: BackendEnqueuing
    private let pending: FilePendingJobStore
    private let clock: () -> Date

    public init(
        capturesDirectory: URL,
        backend: BackendEnqueuing,
        pending: FilePendingJobStore,
        clock: @escaping () -> Date = Date.init
    ) {
        self.capturesDirectory = capturesDirectory
        self.backend = backend
        self.pending = pending
        self.clock = clock
    }

    public func start() {
        isRecording = true
    }

    /// Abandon a recording that never captured anything, for example when the
    /// audio tap failed to start. No meeting is created and nothing is
    /// written, so a failed start leaves no empty-audio meeting behind.
    public func cancel() {
        isRecording = false
    }

    /// Write the mic, system, and mixed streams to the vault's captures folder
    /// and hand them to the backend. Returns at once either way; recording can
    /// start again immediately.
    @discardableResult
    public func stop(_ result: CaptureResult, title: String) throws -> StopOutcome {
        isRecording = false

        // A header-only or empty mixed buffer captured nothing (a tap that
        // never delivered, a permission quietly denied). Create no meeting
        // rather than a 0-byte one that only fails processing.
        guard result.mixed.count > minimumRecordingBytes else {
            return .emptyRecording
        }

        try FileManager.default.createDirectory(at: capturesDirectory, withIntermediateDirectories: true)
        let stamp = ISO8601DateFormatter().string(from: clock())
            .replacingOccurrences(of: ":", with: "")
        let audioURL = capturesDirectory.appendingPathComponent("capture-\(stamp).wav")
        let micURL = capturesDirectory.appendingPathComponent("mic-\(stamp).wav")
        let systemURL = capturesDirectory.appendingPathComponent("system-\(stamp).wav")
        try result.mixed.write(to: audioURL, options: .atomic)
        try result.mic.write(to: micURL, options: .atomic)
        try result.system.write(to: systemURL, options: .atomic)

        let recording = PendingRecording(
            audioPath: audioURL.path, micPath: micURL.path, systemPath: systemURL.path,
            title: title, source: result.source.rawValue, recordedAt: clock())
        do {
            return .enqueued(meetingID: try enqueue(recording))
        } catch {
            pending.add(recording)
            return .pendingBackend
        }
    }

    private func enqueue(_ recording: PendingRecording) throws -> String {
        try backend.importMeeting(
            audioPath: recording.audioPath, micPath: recording.micPath,
            systemPath: recording.systemPath, title: recording.title,
            source: recording.source)
    }

    /// Called when the backend becomes reachable: enqueue whatever capture
    /// saved while it was down. Jobs that still fail stay pending.
    @discardableResult
    public func flushPending() -> Int {
        var remaining: [PendingRecording] = []
        var flushed = 0
        for job in pending.all() {
            do {
                _ = try enqueue(job)
                flushed += 1
            } catch {
                remaining.append(job)
            }
        }
        pending.replace(with: remaining)
        return flushed
    }
}
