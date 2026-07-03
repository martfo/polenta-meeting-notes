// Sections 3.1, 3.2, and 3.3 (app side): first-run provisioning, vault
// creation, and the declared entitlements.

import Foundation
import Testing
@testable import MeetingNotesCore

// MARK: - A fake installer that records steps and can fail on demand

final class FakeInstaller: RuntimeInstalling {
    var failOn: String?
    private(set) var steps: [String] = []

    struct StepFailure: LocalizedError {
        let step: String
        var errorDescription: String? { "no network while \(step)" }
    }

    private func run(_ name: String, at runtime: URL) throws {
        steps.append(name)
        if failOn == name { throw StepFailure(step: name) }
        // Each step leaves an idempotent artefact, like the real one.
        try? "done".write(
            to: runtime.appendingPathComponent(name), atomically: true, encoding: .utf8)
    }

    func fetchPython(into runtime: URL) throws { try run("python", at: runtime) }
    func createEnvironment(at runtime: URL) throws { try run("venv", at: runtime) }
    func installDependencies(at runtime: URL) throws { try run("deps", at: runtime) }
    func verifyBackendStarts(at runtime: URL) throws { try run("verify", at: runtime) }
}

private func supportRoot() -> URL {
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("mn-support-\(UUID().uuidString)/Application Support/MeetingNotes")
    try! FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}

struct AC_3_ProvisioningAndVaultTests {
    @Test("AC-3.1-a first-run detection by runtime presence and validity")
    func test_ac_3_1_a_first_run_detection() throws {
        let runtime = RuntimeLocation.runtimeDirectory(under: supportRoot())

        // Absent: first run.
        #expect(Provisioner.isFirstRun(runtime: runtime))

        // Present but incomplete (no valid marker): still first run.
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)
        try "partial".write(
            to: runtime.appendingPathComponent("python"), atomically: true, encoding: .utf8)
        #expect(Provisioner.isFirstRun(runtime: runtime))

        // Present and valid: not first run.
        try runtimeVersion.write(
            to: RuntimeLocation.markerFile(runtime: runtime), atomically: true, encoding: .utf8)
        #expect(Provisioner.isFirstRun(runtime: runtime) == false)

        // A stale marker from an old runtime version counts as incomplete.
        try "0".write(
            to: RuntimeLocation.markerFile(runtime: runtime), atomically: true, encoding: .utf8)
        #expect(Provisioner.isFirstRun(runtime: runtime))
    }

    @Test("AC-3.1-b provisioning resumes over a partial runtime")
    func test_ac_3_1_b_provisioning_resumes() throws {
        let runtime = RuntimeLocation.runtimeDirectory(under: supportRoot())
        // A previous attempt left a partial runtime and no marker.
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)
        try "half-finished".write(
            to: runtime.appendingPathComponent("python"), atomically: true, encoding: .utf8)

        let provisioner = Provisioner(runtime: runtime, installer: FakeInstaller())
        let state = provisioner.provision()

        #expect(state == .ready)
        #expect(Provisioner.isFirstRun(runtime: runtime) == false, "marked ready")
    }

    @Test("AC-3.1-c provisioning failure is a clear, retryable state")
    func test_ac_3_1_c_provisioning_failure_retryable() {
        let runtime = RuntimeLocation.runtimeDirectory(under: supportRoot())
        let installer = FakeInstaller()
        installer.failOn = "python"  // no network at the download step

        let provisioner = Provisioner(runtime: runtime, installer: installer)
        guard case .failed(let message) = provisioner.provision() else {
            Issue.record("expected a failed state"); return
        }
        #expect(message.contains("Retry"))
        #expect(Provisioner.isFirstRun(runtime: runtime), "no half-built state marked done")

        // The retry succeeds once the network is back.
        installer.failOn = nil
        #expect(provisioner.provision() == .ready)
    }

    @Test("AC-3.1-d runtime path under Application Support, separate from the vault")
    func test_ac_3_1_d_runtime_path() {
        let runtime = RuntimeLocation.runtimeDirectory()
        #expect(runtime.path.contains("Library/Application Support/MeetingNotes/runtime"))

        // The vault is wherever the user chose; the runtime never sits in it.
        let vault = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("MeetingVault")
        #expect(!runtime.path.hasPrefix(vault.path))
        #expect(!vault.path.hasPrefix(runtime.path))
    }

    @Test("AC-3.2-a vault creation makes the folders, prompt, and config")
    func test_ac_3_2_a_vault_creation() throws {
        let root = temporaryDirectory().appendingPathComponent("MeetingVault")

        let created = try VaultCreator.createOrOpen(
            at: root, defaultSummaryPrompt: "Default prompt text.")

        #expect(created)
        for folder in ["settings", "meetings", "speakers", "lancedb", "logs"] {
            var isDirectory: ObjCBool = false
            let exists = FileManager.default.fileExists(
                atPath: root.appendingPathComponent(folder).path, isDirectory: &isDirectory)
            #expect(exists && isDirectory.boolValue, "missing \(folder)")
        }
        let prompt = try String(contentsOf: VaultCreator.summaryPromptPath(for: root), encoding: .utf8)
        #expect(prompt == "Default prompt text.")

        let config = try JSONSerialization.jsonObject(
            with: Data(contentsOf: VaultCreator.configPath(for: root))) as? [String: Any]
        #expect(config?["vault_path"] as? String == root.path)
        #expect(config?["backend_port"] as? Int == 8765)
        #expect(config?["audio_retention_days"] as? Int == 30)
        #expect(config?["match_threshold"] as? Double == 0.75)
    }

    @Test("AC-3.2-b opening an existing vault overwrites nothing")
    func test_ac_3_2_b_existing_vault_untouched() throws {
        let root = temporaryDirectory().appendingPathComponent("MeetingVault")
        try VaultCreator.createOrOpen(at: root, defaultSummaryPrompt: "Original prompt.")

        // The user has edited their prompt and config, and has data.
        try "My edited prompt.".write(
            to: VaultCreator.summaryPromptPath(for: root), atomically: true, encoding: .utf8)
        let editedConfig = VaultCreator.defaultConfigJSON(vaultPath: root.path)
            .replacingOccurrences(of: "\"audio_retention_days\": 30", with: "\"audio_retention_days\": 90")
        try editedConfig.write(to: VaultCreator.configPath(for: root), atomically: true, encoding: .utf8)
        let meeting = root.appendingPathComponent("meetings/2026-07-02_1400_client-review")
        try FileManager.default.createDirectory(at: meeting, withIntermediateDirectories: true)
        try "notes".write(
            to: meeting.appendingPathComponent("notes.md"), atomically: true, encoding: .utf8)

        let created = try VaultCreator.createOrOpen(at: root, defaultSummaryPrompt: "Another default.")

        #expect(created == false, "an existing vault opens as it is")
        #expect(try String(contentsOf: VaultCreator.summaryPromptPath(for: root), encoding: .utf8)
                == "My edited prompt.")
        #expect(try String(contentsOf: VaultCreator.configPath(for: root), encoding: .utf8)
                .contains("\"audio_retention_days\": 90"))
        #expect(try String(contentsOf: meeting.appendingPathComponent("notes.md"), encoding: .utf8)
                == "notes")
    }

    @Test("AC-3.3-a entitlements and usage strings are declared")
    func test_ac_3_3_a_entitlements_declared() throws {
        let support = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Support")

        let entitlements = try PropertyListSerialization.propertyList(
            from: Data(contentsOf: support.appendingPathComponent("MeetingNotes.entitlements")),
            format: nil) as? [String: Any]
        #expect(entitlements?["com.apple.security.device.audio-input"] as? Bool == true)

        let info = try PropertyListSerialization.propertyList(
            from: Data(contentsOf: support.appendingPathComponent("Info.plist")),
            format: nil) as? [String: Any]
        for key in ["NSAudioCaptureUsageDescription", "NSMicrophoneUsageDescription"] {
            let value = info?[key] as? String
            #expect(value?.isEmpty == false, "missing \(key)")
        }
    }
}
