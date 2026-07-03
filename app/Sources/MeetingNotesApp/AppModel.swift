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
    let calendar = CalendarWatcher()
    let microphones = MicrophoneListModel()

    /// The title carried from an accepted calendar offer; the meeting can be
    /// renamed afterwards by clicking its title.
    var pendingTitle: String?
    private(set) var supervisor: BackendSupervisor?
    private(set) var coordinator: RecordingCoordinator?

    /// Attendees carried from an accepted calendar offer into the meeting
    /// that capture creates on Stop.
    var pendingAttendees: [MeetingAttendee] = []

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

        // The backend is a child of this app and stops with it.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak supervisor] _ in
            MainActor.assumeIsolated { supervisor?.stop() }
        }

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
        calendar.isRecording = { [weak self] in self?.capture.isCapturing ?? false }
        calendar.start()

        // Processing happens in the background, so the library keeps itself
        // fresh rather than showing stale statuses until the next click.
        libraryPoll?.cancel()
        libraryPoll = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                await refreshLibrary()
            }
        }
    }

    private var libraryPoll: Task<Void, Never>?

    func refreshLibrary() async {
        library = (try? await client.library()) ?? library
    }

    // MARK: - Recording

    func startRecording(microphone: InputDevice?) {
        guard let coordinator else { return }
        Task {
            // Ask for the microphone up front, so the consent prompt appears
            // the first time rather than the engine quietly running silent.
            let granted = await CaptureController.requestMicrophoneAccess()
            let readiness = CaptureReadiness.evaluate(
                microphone: granted ? .granted : .denied,
                systemAudio: .granted)  // no public query; the tap itself reports failure
            if case .blocked(let message) = readiness {
                lastRecordingMessage = message
                return
            }
            do {
                // Capture must come up before the coordinator is marked
                // recording, so a tap failure leaves no meeting behind.
                try capture.start(microphoneDeviceID: microphone?.id)
                coordinator.start()
                lastRecordingMessage = nil
            } catch {
                coordinator.cancel()
                lastRecordingMessage = "Recording could not start: \(error.localizedDescription)"
            }
        }
    }

    func stopRecording() {
        guard let coordinator else { return }
        let (wavData, source) = capture.stop()
        let title = pendingTitle ?? "Meeting"
        pendingTitle = nil
        do {
            let outcome = try coordinator.stop(
                wavData: wavData,
                title: title,
                source: source)
            switch outcome {
            case .enqueued(let meetingID):
                lastRecordingMessage = "Saved and queued for processing. You can start the next meeting now."
                if !pendingAttendees.isEmpty {
                    let attendees = pendingAttendees
                    Task {
                        try? await client.setAttendees(meetingID, attendees: attendees)
                        await refreshLibrary()
                    }
                }
            case .pendingBackend:
                lastRecordingMessage = "Saved. The backend is not running yet, so processing will start when it is."
            }
            pendingAttendees = []
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
