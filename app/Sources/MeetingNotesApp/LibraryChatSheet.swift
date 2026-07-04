// Chat across the library, as a full-window panel shaped like the
// single-meeting chat: a scrolling conversation with the input at the bottom.
// Retrieval is scoped, one folder by default or the whole vault. Each answer
// cites the meetings it drew on, as links that jump to the meeting summary.
// The conversation persists while the app is open, so leaving to read a cited
// meeting and coming back keeps the history; a Clear button resets it.

import SwiftUI

struct LibraryTurn: Identifiable {
    let id = UUID()
    let question: String
    let answer: String
    let citations: [String]  // meeting ids
}

@MainActor
final class LibraryChatModel: ObservableObject {
    @Published var history: [LibraryTurn] = []
    @Published var allFolders = false
    @Published var folder: String?
    @Published var question = ""
    @Published var busy = false
    @Published var problem: String?

    func clear() {
        history = []
        problem = nil
    }
}

struct LibraryChatPanel: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var chat: LibraryChatModel
    let onOpenMeeting: (String) -> Void
    let onClose: () -> Void

    @State private var folders: [String] = []

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            conversation
            Divider()
            inputBar
        }
        .background(.background)
        .task {
            folders = (try? await model.client.folders()) ?? []
            if chat.folder == nil { chat.folder = folders.first }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Text("Ask the library").font(.title2).bold()
            Picker("Search in", selection: $chat.allFolders) {
                Text("One folder").tag(false)
                Text("All folders").tag(true)
            }
            .pickerStyle(.segmented)
            .fixedSize()
            if !chat.allFolders {
                Picker("Folder", selection: $chat.folder) {
                    ForEach(folders, id: \.self) { Text($0).tag(Optional($0)) }
                }
                .frame(maxWidth: 220)
            }
            Spacer()
            Button("Clear") { chat.clear() }
                .disabled(chat.history.isEmpty)
            Button("Close") { onClose() }
        }
        .padding(12)
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if chat.history.isEmpty && chat.problem == nil {
                        Text("Ask a question to search across your meetings, for "
                             + "example what someone said or which meeting a topic "
                             + "came up in.")
                            .foregroundStyle(.secondary)
                            .padding(.top, 40)
                    }
                    ForEach(chat.history) { turn in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(turn.question).bold()
                            Text(LocalizedStringKey(turn.answer)).textSelection(.enabled)
                            if !turn.citations.isEmpty {
                                SourcesLine(citations: turn.citations, onOpenMeeting: onOpenMeeting)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id(turn.id)
                    }
                    if chat.busy { ProgressView().controlSize(.small) }
                    if let problem = chat.problem {
                        Text(problem).font(.callout).foregroundStyle(.red)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .onChange(of: chat.history.count) { _, _ in
                if let last = chat.history.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var inputBar: some View {
        HStack {
            TextField("What was said about…", text: $chat.question)
                .textFieldStyle(.roundedBorder)
                .onSubmit { ask() }
            Button("Ask") { ask() }
                .keyboardShortcut(.defaultAction)
                .disabled(chat.busy || chat.question.trimmingCharacters(in: .whitespaces).isEmpty
                          || (!chat.allFolders && chat.folder == nil))
            if chat.busy { ProgressView().controlSize(.small) }
        }
        .padding(12)
    }

    private func ask() {
        let text = chat.question.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, !chat.busy else { return }
        chat.question = ""
        chat.busy = true
        chat.problem = nil
        Task {
            defer { chat.busy = false }
            do {
                let result = try await model.client.libraryChat(
                    question: text, allFolders: chat.allFolders, folder: chat.folder)
                chat.history.append(LibraryTurn(
                    question: text, answer: result.answer, citations: result.citations))
            } catch {
                chat.problem = "The library could not be searched: \(error.localizedDescription)"
            }
        }
    }
}

/// "Sources: Meeting one, Meeting two" with each name a link to its meeting.
struct SourcesLine: View {
    @EnvironmentObject var model: AppModel
    let citations: [String]
    let onOpenMeeting: (String) -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text("Sources:").font(.caption).foregroundStyle(.secondary)
            ForEach(Array(citations.enumerated()), id: \.element) { index, meetingID in
                Button {
                    onOpenMeeting(meetingID)
                } label: {
                    Text(model.title(for: meetingID))
                        + Text(index < citations.count - 1 ? "," : "")
                }
                .buttonStyle(.link)
                .font(.caption)
            }
        }
    }
}
