// The app's shared state: the vault, the supervised backend, capture, and
// the library.

import AppKit
import Foundation
import MeetingNotesCore
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @AppStorage("vaultPath") var vaultPath: String = ""

    @Published var library: [LibraryGroup] = []
    @Published var selectedMeetingID: String?
    @Published var lastRecordingMessage: String?

    let client = BackendClient()
    let capture = CaptureController()
    private(set) var supervisor: BackendSupervisor?
    private(set) var coordinator: RecordingCoordinator?

    var vaultURL: URL? {
        vaultPath.isEmpty ? nil : URL(fileURLWithPath: vaultPath)
    }

    func openVault(at url: URL) {
        let defaultPrompt = Bundle.module.url(forResource: "Resources/summary_prompt", withExtension: "md")
            .flatMap { try? String(contentsOf: $0, encoding: .utf8) }
        do {
            try VaultCreator.createOrOpen(at: url, defaultSummaryPrompt: defaultPrompt)
        } catch {
            lastRecordingMessage = "The vault could not be created: \(error.localizedDescription)"
            return
        }
        vaultPath = url.path
        bootBackend()
    }

    func bootBackend() {
        guard let vaultURL else { return }
        let coordinator = RecordingCoordinator(
            capturesDirectory: vaultURL.appendingPathComponent("captures"),
            backend: client,
            pending: FilePendingJobStore(
                fileURL: vaultURL.appendingPathComponent("settings/pending_recordings.json")))
        self.coordinator = coordinator

        let supervisor = BackendSupervisor(
            client: client, configPath: VaultCreator.configPath(for: vaultURL).path)
        self.supervisor = supervisor
        supervisor.start()

        Task {
            // Give the backend a moment, then load the library and enqueue
            // anything captured while it was down.
            for _ in 0..<20 {
                try? await Task.sleep(for: .seconds(1))
                if case .running = supervisor.state {
                    coordinator.flushPending()
                    await refreshLibrary()
                    break
                }
            }
        }
    }

    func refreshLibrary() async {
        library = (try? await client.library()) ?? library
    }

    // MARK: - Recording

    func startRecording(microphone: InputDevice?) {
        guard let coordinator else { return }
        do {
            coordinator.start()
            try capture.start(microphoneDeviceID: microphone?.id)
            lastRecordingMessage = nil
        } catch {
            _ = try? coordinator.stop(wavData: Data(), title: "aborted", source: .online)
            lastRecordingMessage = error.localizedDescription
        }
    }

    func stopRecording(title: String) {
        guard let coordinator else { return }
        let (wavData, source) = capture.stop()
        do {
            let outcome = try coordinator.stop(
                wavData: wavData,
                title: title.isEmpty ? "Meeting" : title,
                source: source)
            switch outcome {
            case .enqueued:
                lastRecordingMessage = "Saved and queued for processing. You can start the next meeting now."
            case .pendingBackend:
                lastRecordingMessage = "Saved. The backend is not running yet, so processing will start when it is."
            }
        } catch {
            lastRecordingMessage = "The recording could not be saved: \(error.localizedDescription)"
        }
        Task { await refreshLibrary() }
    }

    // MARK: - Shortcuts into the vault

    func revealInFinder(path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func revealLogs() {
        guard let vaultURL else { return }
        NSWorkspace.shared.activateFileViewerSelecting(
            [vaultURL.appendingPathComponent("logs")])
    }

    func editSummaryPrompt() {
        guard let vaultURL else { return }
        NSWorkspace.shared.open(VaultCreator.summaryPromptPath(for: vaultURL))
    }
}
