// The backend runs as a supervised child process of the app. The supervisor
// launches it, health-checks it, restarts it if it dies, and publishes a
// clear state for the UI. LM Studio's state rides along from /health.

import Foundation
import MeetingNotesCore

@MainActor
final class BackendSupervisor: ObservableObject {
    enum State: Equatable {
        case starting
        case running(lmstudio: String)
        case down(String)
    }

    @Published private(set) var state: State = .starting

    private var process: Process?
    private let client: BackendClient
    private let configPath: String
    private var monitorTask: Task<Void, Never>?

    init(client: BackendClient, configPath: String) {
        self.client = client
        self.configPath = configPath
    }

    /// The Python interpreter to run the backend with, in order of
    /// preference: an explicit override, the provisioned runtime in
    /// Application Support, then a development checkout.
    static func pythonExecutable() -> String? {
        if let override = ProcessInfo.processInfo.environment["MEETINGNOTES_BACKEND_PYTHON"],
           FileManager.default.isExecutableFile(atPath: override) {
            return override
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let provisioned = support.appendingPathComponent("MeetingNotes/runtime/venv/bin/python3").path
        if FileManager.default.isExecutableFile(atPath: provisioned) {
            return provisioned
        }
        return nil
    }

    /// The backend package directory, for development runs from the repo.
    static func backendDirectory() -> String? {
        ProcessInfo.processInfo.environment["MEETINGNOTES_BACKEND_DIR"]
    }

    func start() {
        terminateOrphan()
        launchProcess()
        monitorTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.checkHealth()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    /// A previous app run (or version) may have left its backend serving on
    /// the port. It runs stale code with a stale environment, so it is
    /// replaced, never adopted.
    private func terminateOrphan() {
        guard process == nil else { return }
        let port = client.baseURL.port ?? 8765
        let lsof = Process()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-ti", "tcp:\(port)"]
        let stdout = Pipe()
        lsof.standardOutput = stdout
        lsof.standardError = Pipe()
        guard (try? lsof.run()) != nil else { return }
        lsof.waitUntilExit()
        let output = String(
            data: stdout.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        for line in output.split(separator: "\n") {
            if let pid = Int32(line.trimmingCharacters(in: .whitespaces)), pid != ProcessInfo.processInfo.processIdentifier {
                kill(pid, SIGTERM)
            }
        }
    }

    func stop() {
        monitorTask?.cancel()
        process?.terminate()
        process = nil
    }

    func checkHealth() async {
        do {
            let health = try await client.health()
            let lmstudio = (health["lmstudio"]?.value as? String) ?? "unknown"
            state = .running(lmstudio: lmstudio)
        } catch {
            if case .running = state {
                state = .down("The backend stopped answering. Restarting it.")
                launchProcess()
            } else if process == nil || process?.isRunning != true {
                state = .down(
                    "The backend is not running. Complete first-run setup, or start "
                    + "the app from a checkout with MEETINGNOTES_BACKEND_PYTHON set.")
            }
        }
    }

    private func launchProcess() {
        guard process?.isRunning != true else { return }
        guard let python = Self.pythonExecutable() else {
            state = .down(
                "No backend runtime found. First-run setup installs it into "
                + "Application Support.")
            return
        }
        let backendProcess = Process()
        backendProcess.executableURL = URL(fileURLWithPath: python)
        backendProcess.arguments = ["-m", "meetingnotes", configPath]
        if let backendDir = Self.backendDirectory() {
            backendProcess.currentDirectoryURL = URL(fileURLWithPath: backendDir)
        }
        // A GUI app's children get the minimal system PATH, which misses
        // Homebrew, and the transcription pipeline shells out to ffmpeg.
        var environment = ProcessInfo.processInfo.environment
        let path = environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        environment["PATH"] = path + ":/opt/homebrew/bin:/usr/local/bin"
        backendProcess.environment = environment
        do {
            try backendProcess.run()
            process = backendProcess
            state = .starting
        } catch {
            state = .down("The backend could not be launched: \(error.localizedDescription)")
        }
    }
}
