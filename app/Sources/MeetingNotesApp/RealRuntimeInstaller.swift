// The production installer behind first-run provisioning: the bundled uv
// binary fetches a standalone CPython build for Apple Silicon, creates the
// environment, and installs the backend that ships inside the app bundle.
// Each step is idempotent, so a retry after a failure simply runs over
// whatever the previous attempt left behind.

import Foundation
import MeetingNotesCore

struct InstallerFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class RealRuntimeInstaller: RuntimeInstalling {
    private let bundledUV: URL
    private let bundledBackend: URL

    init?(bundle: Bundle = .main) {
        guard let uv = bundle.url(forResource: "uv", withExtension: nil),
              let backend = bundle.url(forResource: "backend", withExtension: nil)
        else { return nil }
        self.bundledUV = uv
        self.bundledBackend = backend
    }

    private func pythonInstallDirectory(_ runtime: URL) -> URL {
        runtime.appendingPathComponent("python")
    }

    private func venv(_ runtime: URL) -> URL {
        runtime.appendingPathComponent("venv")
    }

    func fetchPython(into runtime: URL) throws {
        try runUV(["python", "install", "3.11",
                   "--install-dir", pythonInstallDirectory(runtime).path],
                  step: "fetching Python")
    }

    func createEnvironment(at runtime: URL) throws {
        try runUV(["venv", venv(runtime).path, "--python", "3.11",
                   "--allow-existing"],
                  extraEnvironment: ["UV_PYTHON_INSTALL_DIR": pythonInstallDirectory(runtime).path],
                  step: "creating the environment")
    }

    func installDependencies(at runtime: URL) throws {
        try runUV(["pip", "install", "--python", venvPython(runtime).path,
                   bundledBackend.path],
                  step: "installing the backend")
    }

    func verifyBackendStarts(at runtime: URL) throws {
        let process = Process()
        process.executableURL = venvPython(runtime)
        process.arguments = ["-c", "import meetingnotes, fastapi, uvicorn"]
        try run(process, step: "checking the backend")
    }

    // MARK: - Plumbing

    private func venvPython(_ runtime: URL) -> URL {
        venv(runtime).appendingPathComponent("bin/python3")
    }

    private func runUV(_ arguments: [String],
                       extraEnvironment: [String: String] = [:],
                       step: String) throws {
        let process = Process()
        process.executableURL = bundledUV
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment.merge(extraEnvironment) { _, new in new }
        process.environment = environment
        try run(process, step: step)
    }

    private func run(_ process: Process, step: String) throws {
        let stderrPipe = Pipe()
        process.standardError = stderrPipe
        process.standardOutput = Pipe()
        do {
            try process.run()
        } catch {
            throw InstallerFailure(message: "\(step) could not start: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = String(
                data: stderrPipe.fileHandleForReading.readDataToEndOfFile(),
                encoding: .utf8)?.suffix(300) ?? ""
            throw InstallerFailure(message: "\(step) failed. \(detail)")
        }
    }
}
