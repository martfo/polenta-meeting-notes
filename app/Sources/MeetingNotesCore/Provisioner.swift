// Backend provisioning at first run. The shipped app needs no Python or uv
// on the machine: on first launch it provisions the backend into Application
// Support, once per Mac, with a progress view rather than a terminal. The
// installer steps are injected so tests drive every outcome without a
// network or a real toolchain.

import Foundation

public enum RuntimeLocation {
    /// ~/Library/Application Support/MeetingNotes
    public static func applicationSupport() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MeetingNotes")
    }

    /// The provisioned environment, kept separate from the vault the user
    /// chooses.
    public static func runtimeDirectory(under support: URL? = nil) -> URL {
        (support ?? applicationSupport()).appendingPathComponent("runtime")
    }

    public static func markerFile(runtime: URL) -> URL {
        runtime.appendingPathComponent(".provisioned")
    }
}

/// The marker's content; bump to force re-provisioning after a breaking
/// runtime change. Re-provisioning over a complete runtime is quick: the
/// Python build and the dependencies are already in place, so only the
/// backend package reinstalls.
/// 2: the backend is installed with the pipeline and embeddings extras, so
///    transcription and library search work in the installed app.
/// 3: backend fixes: the bge-m3 repo id resolves, and the backend exits with
///    its parent app instead of lingering as an orphan.
/// 4: naming a speaker refreshes transcript.md and meeting.md.
/// 5: meetings can be renamed, and naming a speaker regenerates the summary
///    from the resolved transcript.
/// 6: the meeting detail carries its folder name for the filing menu.
/// 7: attendee pre-fill from calendar invites.
/// 8: naming a speaker re-embeds the search index, not just the summary, so
///    library chat knows the resolved names.
/// 9: editable summaries with in-place name patching, and multi-turn chat.
/// 10: library chat cites only the meetings the answer drew on.
/// 11: notes changes regenerate machine summaries and ask before touching
///     edited ones.
/// 12: meetings can be deleted, and call detection triggers on changes only.
/// 13: empty recordings are rejected and old empty-recording meetings are
///     purged at startup.
/// 14: pasted-image text is OCR'd at paste time and reaches chat and search.
/// 15: a folder-scoped library search that finds nothing widens to the vault.
/// 16: refiling a meeting moves its chunks in the search index too.
/// 17: the model's Sources trailer is always stripped from library answers.
/// 18: library chat prompt hardened against false negatives; wider retrieval.
/// 19: import meetings from a Granola CSV export.
/// 20: Granola-style bulleted summary prompt with a Decisions section; the
///     import reconciles every CSV row.
/// 21: endpoint to restore the bundled default summary prompt into a vault.
/// 22: silent recordings skip transcription and get a plain no-speech note
///     instead of a fabricated summary.
/// 23: summary prompt variables ({{meeting_datetime}}), folder suggestions use
///     the summary, and the library listing carries the full start time.
/// 24: dual-channel capture and pipeline (mic vs system transcribed
///     separately, remote-only diarisation), owner name, channel normalisation.
/// 25: audio is decoded for transcription and diarisation with the standard
///     library instead of WhisperX's ffmpeg shell-out, so the shipped app
///     needs no manual ffmpeg install; Whisper is fed an initial prompt of the
///     meeting's participant names and the configured glossary; folder
///     suggestions learn from the titles already filed in each folder; and the
///     summary prompt no longer attributes points to placeholder labels.
/// 26: per-channel normalisation targets speech loudness (voiced RMS) with a
///     limiter instead of scaling by peak, so the quiet remote channel is
///     actually lifted above the transcriber's voice-activity threshold.
/// 27: reprocessing a meeting replaces its speaker assignments instead of
///     failing their UNIQUE constraint, so Retry can re-run a ready meeting
///     end to end (needed to reprocess repaired audio).
public let runtimeVersion = "27"

public protocol RuntimeInstalling {
    /// Fetch the standalone CPython build for Apple Silicon.
    func fetchPython(into runtime: URL) throws
    /// Create the environment with uv.
    func createEnvironment(at runtime: URL) throws
    /// Install the pinned dependencies.
    func installDependencies(at runtime: URL) throws
    /// Start the backend once and check its health endpoint answers.
    func verifyBackendStarts(at runtime: URL) throws
}

public final class Provisioner {
    public enum State: Equatable {
        case notStarted
        case inProgress(step: String)
        case ready
        /// A plain message and a retryable state, never a half-built one
        /// treated as done.
        case failed(String)
    }

    public private(set) var state: State = .notStarted
    /// Observed by the progress view.
    public var onStep: ((String) -> Void)?

    private let runtime: URL
    private let installer: RuntimeInstalling

    public init(runtime: URL, installer: RuntimeInstalling) {
        self.runtime = runtime
        self.installer = installer
    }

    /// True when the runtime is absent or incomplete; false when present and
    /// valid. A directory without a valid marker is a partial install.
    public static func isFirstRun(runtime: URL) -> Bool {
        let marker = RuntimeLocation.markerFile(runtime: runtime)
        guard let content = try? String(contentsOf: marker, encoding: .utf8) else { return true }
        return content.trimmingCharacters(in: .whitespacesAndNewlines) != runtimeVersion
    }

    /// Runs every step in order. Steps are written to be idempotent, so a
    /// previous partial attempt is simply run over: provisioning resumes
    /// rather than failing. Only a complete run writes the marker.
    @discardableResult
    public func provision() -> State {
        let steps: [(String, (URL) throws -> Void)] = [
            ("Fetching Python", installer.fetchPython(into:)),
            ("Creating the environment", installer.createEnvironment(at:)),
            ("Installing the backend", installer.installDependencies(at:)),
            ("Checking the backend starts", installer.verifyBackendStarts(at:)),
        ]
        do {
            try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)
            for (name, step) in steps {
                state = .inProgress(step: name)
                onStep?(name)
                try step(runtime)
            }
            try runtimeVersion.write(
                to: RuntimeLocation.markerFile(runtime: runtime), atomically: true, encoding: .utf8)
            state = .ready
        } catch {
            state = .failed(
                "Setting up the backend did not finish: \(error.localizedDescription) "
                + "Check the network is available and press Retry.")
        }
        return state
    }
}
