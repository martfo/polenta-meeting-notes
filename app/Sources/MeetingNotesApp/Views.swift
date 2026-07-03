// The window: library on the left, meeting detail on the right, the
// recording bar along the bottom, and plain status lines when the backend or
// LM Studio needs attention. No silent failures.

import MeetingNotesCore
import SwiftUI

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

    var body: some View {
        if model.vaultURL == nil {
            VaultPicker()
        } else {
            MainSplit()
        }
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

    var body: some View {
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
            RecordingBar()
        }
        .toolbar {
            Button("Edit summary prompt") { model.editSummaryPrompt() }
            Button("Reveal logs in Finder") { model.revealLogs() }
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

    var body: some View {
        List(selection: $model.selectedMeetingID) {
            ForEach(model.library) { group in
                Section(group.folder ?? "Unfiled") {
                    ForEach(group.meetings) { meeting in
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
                        .tag(meeting.id)
                    }
                }
            }
        }
        .refreshable { await model.refreshLibrary() }
        .task { await model.refreshLibrary() }
        .navigationSplitViewColumnWidth(min: 240, ideal: 300)
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
    @State private var title = ""
    @State private var devices = InputDevice.all()
    @State private var microphone: InputDevice?

    var body: some View {
        HStack(spacing: 14) {
            if model.capture.isCapturing {
                Button {
                    model.stopRecording(title: title)
                    title = ""
                } label: {
                    Label("Stop", systemImage: "stop.circle.fill")
                }
                .tint(.red)
                LevelBar(label: "Microphone", level: model.capture.microphoneLevel)
                LevelBar(label: "System audio", level: model.capture.systemLevel)
            } else {
                Button {
                    model.startRecording(microphone: microphone)
                } label: {
                    Label("Start recording", systemImage: "record.circle")
                }
                .keyboardShortcut("r")
                TextField("Meeting title", text: $title)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 260)
                Picker("Microphone", selection: $microphone) {
                    ForEach(devices) { device in
                        Text(device.name).tag(Optional(device))
                    }
                }
                .frame(maxWidth: 280)
                .onAppear { restoreMicrophoneChoice() }
                .onChange(of: microphone) { _, chosen in
                    if let chosen {
                        MicrophonePreference(store: UserDefaults.standard).save(deviceUID: chosen.uid)
                    }
                }
            }
            Spacer()
            if let message = model.lastRecordingMessage {
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(10)
    }

    private func restoreMicrophoneChoice() {
        devices = InputDevice.all()
        let savedUID = MicrophonePreference(store: UserDefaults.standard).restore()
        microphone = devices.first { $0.uid == savedUID } ?? devices.first
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
