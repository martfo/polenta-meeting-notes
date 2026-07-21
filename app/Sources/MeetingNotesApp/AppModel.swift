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
    let libraryChat = LibraryChatModel()

    /// The meeting's title for a citation link, falling back to the id while
    /// the library list has not loaded it.
    func title(for meetingID: String) -> String {
        for group in library {
            if let meeting = group.meetings.first(where: { $0.id == meetingID }) {
                return meeting.title
            }
        }
        return meetingID
    }

    /// The title carried from an accepted calendar offer; the meeting can be
    /// renamed afterwards by clicking its title.
    var pendingTitle: String?
    private(set) var supervisor: BackendSupervisor?
    private(set) var coordinator: RecordingCoordinator?

    /// Attendees carried from an accepted calendar offer into the meeting
    /// that capture creates on Stop.
    var pendingAttendees: [MeetingAttendee] = []

    /// The calendar meeting's end time carried from an accepted offer, for
    /// scheduling auto-stop.
    var pendingAutoStopEnd: Date?

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

    /// Guards start/stop so a rapid double press (button plus hotkey, or a
    /// hotkey repeat) cannot start or stop twice and crash the audio engine.
    private var isTransitioning = false

    func startRecording(microphone: InputDevice?) {
        guard let coordinator, !capture.isCapturing, !isTransitioning else { return }
        isTransitioning = true
        // If this recording was not started from an accepted calendar offer,
        // borrow the title, attendees, and end time from a meeting happening
        // right now, so hand-started recordings are named and auto-stop too.
        var autoStopEnd = pendingAutoStopEnd
        if pendingTitle == nil, let current = calendar.currentEvent() {
            pendingTitle = current.title
            pendingAttendees = current.attendees.map { MeetingAttendee(name: $0.name, email: $0.email) }
            autoStopEnd = current.end
        }
        Task {
            defer { isTransitioning = false }
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
                try await capture.start(microphoneDeviceID: microphone.flatMap(\.captureDeviceID))
                coordinator.start()
                scheduleAutoStop(meetingEnd: autoStopEnd)
                pendingAutoStopEnd = nil
                lastRecordingMessage = nil
            } catch {
                coordinator.cancel()
                lastRecordingMessage = "Recording could not start: \(error.localizedDescription)"
            }
        }
    }

    // MARK: - Auto-stop

    /// Auto-stop a forgotten or ended recording. A calendar meeting's scheduled
    /// end is not a hard cutoff: past it the recording keeps going while the
    /// call is still audible, and stops only once the call audio has been quiet
    /// for a few minutes (the meeting really ended) or the maximum length is
    /// reached. A timer re-checks every minute rather than sleeping to a fixed
    /// deadline, so an overrunning meeting is recorded in full.
    private var autoStopTask: Task<Void, Never>?
    /// How long the call must be silent, past the scheduled end, to be judged
    /// over. Long enough to ride out a lull in conversation.
    private static let quietThreshold: TimeInterval = 5 * 60

    private func scheduleAutoStop(meetingEnd: Date?) {
        autoStopTask?.cancel()
        let maxMinutes = UserDefaults.standard.object(forKey: "maxRecordingMinutes") as? Int ?? 180
        let maxStopAt = Date().addingTimeInterval(Double(maxMinutes) * 60)
        let windDownAt = meetingEnd ?? .distantFuture
        autoStopTask = Task { [weak self] in
            while true {
                try? await Task.sleep(for: .seconds(60))
                guard let self, !Task.isCancelled, self.capture.isCapturing else { return }
                let decision = AutoStop.decide(
                    now: Date(), windDownAt: windDownAt, maxStopAt: maxStopAt,
                    secondsSinceSystemActivity: self.capture.secondsSinceSystemActivity(),
                    quietThreshold: Self.quietThreshold)
                if case .stop(let reason) = decision {
                    self.lastRecordingMessage = "Recording stopped automatically because \(reason)."
                    self.stopRecording()
                    return
                }
            }
        }
    }

    /// Start or stop, whichever is not current. Driven by the global hotkey,
    /// so pressing it again stops the recording.
    func toggleRecording() {
        guard coordinator != nil, !isTransitioning else { return }
        if capture.isCapturing {
            stopRecording()
        } else {
            startRecording(microphone: microphones.selection)
        }
    }

    func stopRecording() {
        guard let coordinator, capture.isCapturing, !isTransitioning else { return }
        isTransitioning = true
        autoStopTask?.cancel()
        Task {
            defer { isTransitioning = false }
            let result = await capture.stop()
            let title = pendingTitle ?? "Meeting"
            pendingTitle = nil
            do {
                let outcome = try coordinator.stop(result, title: title)
                switch outcome {
                case .enqueued(let meetingID):
                    lastRecordingMessage = "Saved and queued for processing. You can start the next meeting now."
                    if !pendingAttendees.isEmpty {
                        let attendees = pendingAttendees
                        try? await client.setAttendees(meetingID, attendees: attendees)
                    }
                case .pendingBackend:
                    lastRecordingMessage = "Saved. The backend is not running yet, so processing will start when it is."
                case .emptyRecording:
                    lastRecordingMessage = "That recording captured no audio, so nothing was saved. "
                        + "Check the microphone and system-audio permissions and the input levels."
                }
                pendingAttendees = []
            } catch {
                lastRecordingMessage = "The recording could not be saved: \(error.localizedDescription)"
            }
            await refreshLibrary()
        }
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
