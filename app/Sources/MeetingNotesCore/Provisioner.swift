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
public let runtimeVersion = "4"

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
