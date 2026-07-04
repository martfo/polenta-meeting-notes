// The window: library on the left, meeting detail on the right, the
// recording bar along the bottom, and plain status lines when the backend or
// LM Studio needs attention. No silent failures.

import MeetingNotesCore
import SwiftUI
import UniformTypeIdentifiers

@main
struct MeetingNotesApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 980, minHeight: 640)
                .onAppear {
                    if model.vaultURL != nil { model.bootBackend() }
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var needsFirstRun = RootView.firstRunNeeded()
    @AppStorage(Appearance.sizeKey) private var baseFontSize = Appearance.defaultSize
    @AppStorage(Appearance.designKey) private var fontDesign = "system"

    /// First run is decided by the provisioning marker and its version, not
    /// by whether some runtime happens to exist: an outdated runtime must be
    /// provisioned over, not reused.
    static func firstRunNeeded() -> Bool {
        if ProcessInfo.processInfo.environment["MEETINGNOTES_BACKEND_PYTHON"] != nil {
            return false  // a development checkout supplies its own backend
        }
        return Provisioner.isFirstRun(runtime: RuntimeLocation.runtimeDirectory())
    }

    var body: some View {
        Group {
            if model.vaultURL == nil {
                VaultPicker()
            } else if needsFirstRun {
                FirstRunView {
                    needsFirstRun = false
                    model.bootBackend()
                }
            } else {
                MainSplit()
            }
        }
        .font(Appearance.font(size: baseFontSize, design: fontDesign))
    }
}

struct VaultPicker: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 16) {
            Text("Choose where your meeting vault lives")
                .font(.title2)
            Text("Everything the app stores, meetings, transcripts, summaries, "
                 + "and notes, goes into this one folder. Pick an existing vault "
                 + "to open it as it is.")
                .frame(maxWidth: 460)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Choose a folder") {
                let panel = NSOpenPanel()
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.canCreateDirectories = true
                panel.prompt = "Use this folder"
                if panel.runModal() == .OK, let url = panel.url {
                    model.openVault(at: url)
                }
            }
            .keyboardShortcut(.defaultAction)
        }
        .padding(40)
    }
}

struct MainSplit: View {
    @EnvironmentObject var model: AppModel
    @State private var showLibraryChat = false

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                StatusBanner()
                NavigationSplitView {
                    LibraryList()
                } detail: {
                    if let meetingID = model.selectedMeetingID {
                        MeetingDetailScreen(meetingID: meetingID)
                            .id(meetingID)
                    } else {
                        Text("Choose a meeting, or press Start to record one.")
                            .foregroundStyle(.secondary)
                    }
                }
                Divider()
                RecordingBar(capture: model.capture, calendar: model.calendar,
                             microphones: model.microphones)
            }

            // The library chat fills the whole app area, so leaving it to read
            // a cited meeting and returning keeps the conversation.
            if showLibraryChat {
                LibraryChatPanel(
                    chat: model.libraryChat,
                    onOpenMeeting: { meetingID in
                        model.selectedMeetingID = meetingID
                        showLibraryChat = false
                    },
                    onClose: { showLibraryChat = false })
                    .environmentObject(model)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.15), value: showLibraryChat)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button("Ask the library") { showLibraryChat = true }
                RecordToolbarButton(capture: model.capture)
            }
        }
    }
}

struct RecordToolbarButton: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var capture: CaptureController

    var body: some View {
        if capture.isCapturing {
            Button {
                model.stopRecording()
            } label: {
                Label("Stop recording", systemImage: "stop.circle.fill")
                    .labelStyle(.titleAndIcon)
            }
            .tint(.red)
        } else {
            Button {
                model.startRecording(microphone: model.microphones.selection)
            } label: {
                Label("Start recording", systemImage: "record.circle")
                    .labelStyle(.titleAndIcon)
            }
            .keyboardShortcut("r")
        }
    }
}

struct SettingsSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage(Appearance.sizeKey) private var baseFontSize = Appearance.defaultSize
    @AppStorage(Appearance.designKey) private var fontDesign = "system"
    @State private var importStatus: String?
    @State private var importing = false

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("Import") {
                    LabeledContent {
                        Button(importing ? "Importing…" : "Choose CSV…") { chooseGranolaCSV() }
                            .disabled(importing)
                    } label: {
                        Label("Import from Granola", systemImage: "square.and.arrow.down")
                        Text("Import the CSV export from Granola (Settings, Profile, "
                             + "Generate CSV). Meetings come in with their transcript, "
                             + "summary, and folder, ready to search and chat.")
                    }
                    if let importStatus {
                        Text(importStatus).font(.caption).foregroundStyle(.secondary)
                    }
                }

                Section("Appearance") {
                    Picker("Font", selection: $fontDesign) {
                        ForEach(Appearance.designs, id: \.raw) { design in
                            Text(design.name).tag(design.raw)
                        }
                    }
                    HStack {
                        Text("Size")
                        Slider(value: $baseFontSize, in: 11...18, step: 1)
                        Text("\(Int(baseFontSize)) pt")
                            .monospacedDigit()
                            .frame(width: 44, alignment: .trailing)
                    }
                    Text("The quick brown fox jumps over the lazy dog.")
                        .font(Appearance.font(size: baseFontSize, design: fontDesign))
                        .foregroundStyle(.secondary)
                }

                Section("Summaries") {
                    LabeledContent {
                        Button("Open") { model.editSummaryPrompt() }
                    } label: {
                        Label("Summary prompt", systemImage: "square.and.pencil")
                        Text("Changes take effect on the next summary, no restart.")
                    }
                }

                Section("Troubleshooting") {
                    LabeledContent {
                        Button("Show") { model.revealLogs() }
                    } label: {
                        Label("Logs", systemImage: "doc.text.magnifyingglass")
                        Text("What happened and where, never meeting content.")
                    }
                }
            }
            .formStyle(.grouped)
            Divider()
            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding(12)
        }
        .frame(width: 480, height: 520)
    }

    private func chooseGranolaCSV() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.prompt = "Import"
        guard panel.runModal() == .OK, let url = panel.url,
              let csv = try? String(contentsOf: url, encoding: .utf8) else { return }
        importing = true
        importStatus = "Importing…"
        Task {
            defer { importing = false }
            do {
                let result = try await model.client.importGranolaCSV(csv)
                await model.refreshLibrary()
                if result.imported == 0 && result.total_rows == 0 && !result.warnings.isEmpty {
                    importStatus = result.warnings.joined(separator: " ")
                } else {
                    // A full tally, so every line of the CSV is accounted for.
                    var parts = ["\(result.total_rows) rows: \(result.imported) imported"]
                    if result.skipped > 0 { parts.append("\(result.skipped) already present") }
                    if result.empty > 0 { parts.append("\(result.empty) empty") }
                    if result.failed > 0 { parts.append("\(result.failed) failed") }
                    var status = parts.joined(separator: ", ") + "."
                    if !result.folders_created.isEmpty {
                        status += " New folders: \(result.folders_created.joined(separator: ", "))."
                    }
                    if !result.reconciled {
                        status += " Warning: the totals did not reconcile; see logs."
                    }
                    if let firstFailure = result.failures.first {
                        status += " First failure: row \(firstFailure.row) (\(firstFailure.title)): \(firstFailure.reason)"
                    }
                    importStatus = status
                }
            } catch {
                importStatus = "Import failed: \(error.localizedDescription)"
            }
        }
    }
}

struct StatusBanner: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let supervisor = model.supervisor {
            SupervisorBanner(supervisor: supervisor)
        }
    }
}

struct SupervisorBanner: View {
    @ObservedObject var supervisor: BackendSupervisor

    var message: String? {
        switch supervisor.state {
        case .starting:
            return "Starting the backend."
        case .running(let lmstudio) where lmstudio == "unreachable":
            return "LM Studio is not reachable on port 1234. Transcripts still "
                 + "process; summaries wait until it is back."
        case .running(let lmstudio) where lmstudio == "no_model_loaded":
            return "LM Studio is running with no model loaded. Load one to get summaries."
        case .running:
            return nil
        case .down(let reason):
            return reason
        }
    }

    var body: some View {
        if let message {
            Text(message)
                .padding(8)
                .frame(maxWidth: .infinity)
                .background(.yellow.opacity(0.2))
        }
    }
}

struct LibraryList: View {
    @EnvironmentObject var model: AppModel
    // Folders start expanded; a folder the user collapses is remembered here.
    @State private var collapsed: Set<String> = []

    var body: some View {
        List(selection: $model.selectedMeetingID) {
            ForEach(model.library) { group in
                Section(isExpanded: expanded(group.id)) {
                    ForEach(group.meetings) { meeting in
                        meetingRow(meeting).tag(meeting.id)
                    }
                } header: {
                    Text(group.folder ?? "Unfiled")
                }
            }
        }
        .listStyle(.sidebar)
        .refreshable { await model.refreshLibrary() }
        .task { await model.refreshLibrary() }
        .navigationSplitViewColumnWidth(min: 240, ideal: 300)
    }

    private func expanded(_ id: String) -> Binding<Bool> {
        Binding(
            get: { !collapsed.contains(id) },
            set: { isExpanded in
                if isExpanded { collapsed.remove(id) } else { collapsed.insert(id) }
            })
    }

    private func meetingRow(_ meeting: MeetingSummaryRow) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(meeting.title).fontWeight(.medium)
            HStack(spacing: 6) {
                Text(meeting.date)
                if !meeting.attendees.isEmpty {
                    Text(meeting.attendees.joined(separator: ", "))
                        .lineLimit(1)
                }
                StatusLabel(meeting: meeting)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }
}

struct StatusLabel: View {
    let meeting: MeetingSummaryRow

    var body: some View {
        switch meeting.processing_status {
        case "ready" where meeting.summary_status == "pending":
            Text("summary pending").foregroundStyle(.orange)
        case "ready":
            EmptyView()
        case "failed":
            Text("failed: \(meeting.failed_stage ?? "processing")").foregroundStyle(.red)
        default:
            Text(meeting.processing_status).foregroundStyle(.blue)
        }
    }
}

struct RecordingBar: View {
    @EnvironmentObject var model: AppModel
    // Observed directly: the level meters live on the capture controller, and
    // a nested ObservableObject does not republish through AppModel.
    @ObservedObject var capture: CaptureController
    @ObservedObject var calendar: CalendarWatcher
    @ObservedObject var microphones: MicrophoneListModel
    @State private var showSettings = false

    var body: some View {
        VStack(spacing: 0) {
            if let offer = calendar.offer, !capture.isCapturing {
                HStack(spacing: 10) {
                    Image(systemName: "calendar.badge.clock")
                    Text(offer.reason)
                    if !offer.attendees.isEmpty {
                        Text(offer.attendees.map(\.name).joined(separator: ", "))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Button("Start recording") { accept(offer) }
                        .buttonStyle(.borderedProminent)
                    Button("Not now") { calendar.dismiss() }
                }
                .font(.callout)
                .padding(8)
                .background(.blue.opacity(0.12))
            }
            recordingControls
        }
    }

    private func accept(_ offer: CalendarWatcher.Offer) {
        model.pendingTitle = offer.title
        model.pendingAttendees = offer.attendees.map {
            MeetingAttendee(name: $0.name, email: $0.email)
        }
        calendar.accepted()
        model.startRecording(microphone: microphones.selection)
    }

    private var recordingControls: some View {
        HStack(spacing: 14) {
            if capture.isCapturing {
                Label("Recording", systemImage: "record.circle.fill")
                    .foregroundStyle(.red)
                LevelBar(label: "Microphone", level: capture.microphoneLevel)
                LevelBar(label: "System audio", level: capture.systemLevel)
            } else {
                Picker("Microphone", selection: $microphones.selection) {
                    ForEach(microphones.devices) { device in
                        Text(device.name).tag(Optional(device))
                    }
                }
                .frame(maxWidth: 300)
            }
            Spacer()
            if let message = model.lastRecordingMessage {
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape")
            }
            .buttonStyle(.borderless)
            .help("Settings")
        }
        .padding(10)
        .sheet(isPresented: $showSettings) {
            SettingsSheet().environmentObject(model)
        }
    }
}

struct LevelBar: View {
    let label: String
    let level: Float

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            ProgressView(value: min(1, level * 3))
                .frame(width: 130)
        }
    }
}
