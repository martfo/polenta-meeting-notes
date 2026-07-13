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
                    // The global hotkey toggles recording even when another
                    // app has focus.
                    GlobalHotKey.shared.action = { [weak model] in model?.toggleRecording() }
                    GlobalHotKey.shared.applyFromDefaults()
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
        .navigationTitle("Polenta Meeting Notes")
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 22, height: 22)
                    .padding(.trailing, 2)
            }
            ToolbarItemGroup(placement: .primaryAction) {
                Button("Ask the library") { showLibraryChat.toggle() }
                RecordToolbarButton(capture: model.capture)
            }
        }
    }
}

struct RecordToolbarButton: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var capture: CaptureController
    // The keys are read so the tooltip updates when the shortcut changes.
    @AppStorage(RecordShortcut.key) private var shortcutKey = RecordShortcut.defaultKey
    @AppStorage(RecordShortcut.modifiersKey) private var modifierRaw = RecordShortcut.defaultModifiers.rawValue

    var body: some View {
        if capture.isCapturing {
            Button {
                model.stopRecording()
            } label: {
                Label("Stop recording", systemImage: "stop.fill")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(PillButtonStyle(background: .red, foreground: .white))
            .help("Stop recording (\(RecordShortcut.displayString()))")
        } else {
            Button {
                model.startRecording(microphone: model.microphones.selection)
            } label: {
                Label("Start recording", systemImage: "record.circle")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(PillButtonStyle(background: Color(white: 0.96), foreground: .black))
            .help("Start recording (\(RecordShortcut.displayString()))")
        }
    }
}

/// A text input with a fill slightly lighter than its surround and a soft
/// border, so the box stays visible against the dark background rather than
/// melting into it.
struct SoftFieldBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .textFieldStyle(.plain)
            .padding(.horizontal, 11)
            .padding(.vertical, 8)
            .background(Color.primary.opacity(0.07))
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).stroke(Color.primary.opacity(0.12)))
    }
}

extension View {
    func softField() -> some View { modifier(SoftFieldBackground()) }
}

/// A rounded, filled pill: a light background with dark text stands out in the
/// toolbar, as the record control should.
struct PillButtonStyle: ButtonStyle {
    var background: Color
    var foreground: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(foreground)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(background.opacity(configuration.isPressed ? 0.8 : 1.0))
            .clipShape(Capsule())
            .contentShape(Capsule())
    }
}

struct SettingsSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage(Appearance.sizeKey) private var baseFontSize = Appearance.defaultSize
    @AppStorage(Appearance.designKey) private var fontDesign = "system"
    @State private var importStatus: String?
    @State private var importing = false
    @State private var promptRestored = false

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

                RecordingShortcutSection()

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

                OwnerNameSection()

                Section("Summaries") {
                    LabeledContent {
                        Button("Open") { model.editSummaryPrompt() }
                    } label: {
                        Label("Summary prompt", systemImage: "square.and.pencil")
                        Text("Changes take effect on the next summary, no restart.")
                    }
                    LabeledContent {
                        Button(promptRestored ? "Restored" : "Restore") { restorePrompt() }
                            .disabled(promptRestored)
                    } label: {
                        Label("Granola-style default", systemImage: "sparkles")
                        Text("Replace this vault's summary prompt with the latest "
                             + "bullet-point default, then use Regenerate on a meeting.")
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

    private func restorePrompt() {
        Task {
            try? await model.client.restoreDefaultSummaryPrompt()
            promptRestored = true
        }
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

struct OwnerNameSection: View {
    @EnvironmentObject var model: AppModel
    @State private var name = ""
    @State private var loaded = false

    var body: some View {
        Section("Your name") {
            Text("Recordings capture your microphone and the call audio as two "
                 + "separate channels. Your microphone is labelled with this name, "
                 + "so you never need naming, and only the remote voices are "
                 + "separated.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField("Your name", text: $name)
                    .softField()
                Button("Save") {
                    Task { try? await model.client.setOwnerName(name) }
                }
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .task {
            guard !loaded else { return }
            loaded = true
            name = (try? await model.client.ownerName()) ?? "Me"
        }
    }
}

struct RecordingShortcutSection: View {
    @AppStorage(RecordShortcut.key) private var recordShortcutKey = RecordShortcut.defaultKey
    @AppStorage(RecordShortcut.modifiersKey) private var modifierRaw = RecordShortcut.defaultModifiers.rawValue
    @State private var registered = true

    private let keyChoices: [String] =
        (UnicodeScalar("a").value...UnicodeScalar("z").value).compactMap { UnicodeScalar($0).map(String.init) }
        + (0...9).map(String.init)

    var body: some View {
        Section("Recording shortcut") {
            Text("A system-wide shortcut that starts and stops recording even when "
                 + "another app, such as your call, has focus. Changes are saved and "
                 + "take effect immediately.")
                .font(.caption).foregroundStyle(.secondary)
            modifiers
            Picker("Key", selection: $recordShortcutKey) {
                ForEach(keyChoices, id: \.self) { Text($0.uppercased()).tag($0) }
            }
            .frame(maxWidth: 160)
            LabeledContent("Shortcut") {
                Text(RecordShortcut.displayString())
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(registered ? Color.primary : Color.orange)
            }
            if !registered {
                Label("This combination could not be registered. It needs at least one "
                      + "modifier, or another app may already use it.",
                      systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
        .onChange(of: recordShortcutKey) { _, _ in apply() }
        .onChange(of: modifierRaw) { _, _ in apply() }
        .onAppear { registered = GlobalHotKey.shared.applyFromDefaults() }
    }

    private var modifiers: some View {
        HStack(spacing: 14) {
            Text("Modifiers").foregroundStyle(.secondary)
            Toggle("\u{2303}", isOn: modifier(.control)).help("Control")
            Toggle("\u{2325}", isOn: modifier(.option)).help("Option")
            Toggle("\u{21E7}", isOn: modifier(.shift)).help("Shift")
            Toggle("\u{2318}", isOn: modifier(.command)).help("Command")
        }
        .toggleStyle(.checkbox)
    }

    private func modifier(_ mod: ShortcutModifiers) -> Binding<Bool> {
        Binding(
            get: { ShortcutModifiers(rawValue: modifierRaw).contains(mod) },
            set: { on in
                var set = ShortcutModifiers(rawValue: modifierRaw)
                if on { set.insert(mod) } else { set.remove(mod) }
                modifierRaw = set.rawValue
            })
    }

    private func apply() {
        registered = GlobalHotKey.shared.applyFromDefaults()
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
    @AppStorage("libraryGrouping") private var grouping = "folders"

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $grouping) {
                Text("Folders").tag("folders")
                Text("Date").tag("date")
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            Divider()
            if grouping == "date" { dateList } else { folderList }
        }
        .navigationSplitViewColumnWidth(min: 240, ideal: 300)
    }

    private var folderList: some View {
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
    }

    private var dateBuckets: [(name: String, meetings: [MeetingSummaryRow])] {
        let now = Date()
        let all = model.library.flatMap(\.meetings)
            .sorted { $0.started_at > $1.started_at }
        var byBucket: [String: [MeetingSummaryRow]] = [:]
        for meeting in all {
            byBucket[DateGrouping.bucket(for: meeting.started_at, now: now), default: []].append(meeting)
        }
        return byBucket
            .sorted { DateGrouping.sortIndex(of: $0.key) < DateGrouping.sortIndex(of: $1.key) }
            .map { ($0.key, $0.value) }
    }

    private var dateList: some View {
        List(selection: $model.selectedMeetingID) {
            ForEach(dateBuckets, id: \.name) { bucket in
                Section(bucket.name) {
                    ForEach(bucket.meetings) { meeting in
                        meetingRow(meeting, showFolder: true, showTime: true).tag(meeting.id)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .refreshable { await model.refreshLibrary() }
    }

    private func expanded(_ id: String) -> Binding<Bool> {
        Binding(
            get: { !collapsed.contains(id) },
            set: { isExpanded in
                if isExpanded { collapsed.remove(id) } else { collapsed.insert(id) }
            })
    }

    private func meetingRow(_ meeting: MeetingSummaryRow, showFolder: Bool = false,
                            showTime: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(meeting.title).fontWeight(.medium)
            HStack(spacing: 6) {
                Text(meeting.date)
                if showTime, let time = DateGrouping.timeOfDay(meeting.started_at) {
                    Text(time)
                }
                if showFolder, let folder = meeting.folder {
                    Text(folder)
                } else if !meeting.attendees.isEmpty {
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
        model.pendingAutoStopEnd = offer.end
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
            }
            // The microphone can be changed at any time, including mid-recording.
            Picker("Microphone", selection: $microphones.selection) {
                ForEach(microphones.devices) { device in
                    Text(device.name).tag(Optional(device))
                }
            }
            .frame(maxWidth: capture.isCapturing ? 220 : 300)
            .onChange(of: microphones.selection) { _, newValue in
                if capture.isCapturing, let device = newValue {
                    Task { await capture.switchInput(to: device.captureDeviceID) }
                }
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
