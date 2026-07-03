// Chat across the library. Retrieval is scoped: one folder by default, the
// whole vault on request. Answers cite the meetings they came from, and a
// citation jumps to that meeting.

import SwiftUI

struct LibraryChatSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var folders: [String] = []
    @State private var folder: String?
    @State private var allFolders = false
    @State private var question = ""
    @State private var answer: String?
    @State private var citations: [String] = []
    @State private var busy = false
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Ask the library").font(.title2).bold()

            HStack {
                Picker("Search in", selection: $allFolders) {
                    Text("One folder").tag(false)
                    Text("All folders").tag(true)
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 260)
                if !allFolders {
                    Picker("Folder", selection: $folder) {
                        ForEach(folders, id: \.self) { Text($0).tag(Optional($0)) }
                    }
                    .frame(maxWidth: 240)
                }
                Spacer()
            }

            HStack {
                TextField("What was said about…", text: $question)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { ask() }
                Button("Ask") { ask() }
                    .disabled(busy || question.isEmpty || (!allFolders && folder == nil))
                if busy { ProgressView().controlSize(.small) }
            }

            if let problem {
                Text(problem).font(.callout).foregroundStyle(.red)
            }

            if let answer {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(answer).textSelection(.enabled)
                        if !citations.isEmpty {
                            Text("From these meetings:").font(.caption).foregroundStyle(.secondary)
                            ForEach(citations, id: \.self) { meetingID in
                                Button(meetingID) {
                                    model.selectedMeetingID = meetingID
                                    dismiss()
                                }
                                .buttonStyle(.link)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Spacer()
            }

            HStack {
                Spacer()
                Button("Close") { dismiss() }
            }
        }
        .padding(20)
        .frame(width: 560, height: 440)
        .task {
            folders = (try? await model.client.folders()) ?? []
            if folder == nil { folder = folders.first }
        }
    }

    private func ask() {
        let text = question.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        busy = true
        problem = nil
        Task {
            defer { busy = false }
            do {
                let result = try await model.client.libraryChat(
                    question: text, allFolders: allFolders, folder: folder)
                answer = result.answer
                citations = result.citations
            } catch {
                problem = "The library could not be searched: \(error.localizedDescription)"
            }
        }
    }
}
