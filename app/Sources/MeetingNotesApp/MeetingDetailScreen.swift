// One meeting: summary, transcript, notes, chat, and speakers, with Reveal
// in Finder and Retry where processing failed.

import MeetingNotesCore
import SwiftUI

struct MeetingDetailScreen: View {
    @EnvironmentObject var model: AppModel
    let meetingID: String

    @State private var detail: MeetingDetail?
    @State private var tab = "Summary"
    @State private var notesDraft = ""
    @State private var chatHistory: [(question: String, answer: String)] = []
    @State private var chatQuestion = ""
    @State private var chatBusy = false

    var body: some View {
        VStack(spacing: 0) {
            if let detail {
                header(detail)
                Picker("", selection: $tab) {
                    ForEach(["Summary", "Transcript", "Notes", "Chat", "Speakers"], id: \.self) { Text($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                content(detail)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: meetingID) {
            await reload()
            // Keep the open meeting fresh while it is being processed, so a
            // stage change or failure shows without a click.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                await reload(keepingDraft: true)
            }
        }
    }

    private func reload(keepingDraft: Bool = false) async {
        guard let fresh = try? await model.client.meeting(meetingID) else { return }
        detail = fresh
        if !keepingDraft || notesDraft.isEmpty {
            notesDraft = fresh.notes
        }
    }

    @ViewBuilder
    private func header(_ detail: MeetingDetail) -> some View {
        // The buttons keep a fixed position; the error message sits on its
        // own line underneath rather than pushing them around.
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(detail.title).font(.title2).bold()
                Spacer()
                if detail.processing_status == "failed" {
                    Button("Retry from \(detail.failed_stage ?? "the failed stage")") {
                        Task {
                            try? await model.client.retry(meetingID)
                            await reload()
                            await model.refreshLibrary()
                        }
                    }
                }
                Button("Reveal in Finder") {
                    model.revealInFinder(path: detail.reveal_path)
                }
            }
            if detail.processing_status == "failed" {
                Text(detail.last_error ?? "Processing failed.")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .padding()
    }

    @ViewBuilder
    private func content(_ detail: MeetingDetail) -> some View {
        switch tab {
        case "Transcript":
            MarkdownPane(text: detail.transcript ?? "No transcript yet. It appears when processing reaches that stage.")
        case "Notes":
            VStack(alignment: .leading) {
                TextEditor(text: $notesDraft)
                    .font(.body)
                HStack {
                    Text("Your notes feed into the summary and are never rewritten.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Save notes") {
                        Task { try? await model.client.saveNotes(meetingID, text: notesDraft) }
                    }
                }
            }
            .padding()
        case "Chat":
            VStack(alignment: .leading, spacing: 8) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(chatHistory.indices, id: \.self) { index in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(chatHistory[index].question).bold()
                                Text(chatHistory[index].answer)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack {
                    TextField("Ask about this meeting", text: $chatQuestion)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { ask() }
                    Button("Ask") { ask() }.disabled(chatBusy || chatQuestion.isEmpty)
                    if chatBusy { ProgressView().controlSize(.small) }
                }
            }
            .padding()
        case "Speakers":
            SpeakersTab(meetingID: meetingID) {
                await reload(keepingDraft: true)
            }
        default:
            MarkdownPane(text: summaryBody(detail))
        }
    }

    private func summaryBody(_ detail: MeetingDetail) -> String {
        guard let summary = detail.summary else {
            if detail.summary_status == "pending" {
                return "The summary is pending. It is written when LM Studio is reachable with a model loaded."
            }
            return "No summary yet."
        }
        // meeting.md carries front matter; show only the body here.
        if summary.hasPrefix("---\n"),
           let range = summary.range(of: "\n---\n", range: summary.index(summary.startIndex, offsetBy: 4)..<summary.endIndex) {
            return String(summary[range.upperBound...])
        }
        return summary
    }

    private func ask() {
        let question = chatQuestion.trimmingCharacters(in: .whitespaces)
        guard !question.isEmpty else { return }
        chatQuestion = ""
        chatBusy = true
        Task {
            defer { chatBusy = false }
            do {
                let answer = try await model.client.chat(meetingID, question: question)
                chatHistory.append((question, answer))
            } catch {
                chatHistory.append((question, "The model could not answer: \(error.localizedDescription)"))
            }
        }
    }
}

struct MarkdownPane: View {
    let text: String

    var body: some View {
        ScrollView {
            Text(LocalizedStringKey(text))
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding()
        }
    }
}
