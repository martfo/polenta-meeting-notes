// Naming the voices in a meeting. Setting a name teaches the enrolment
// gallery, so a voice named once is recognised automatically in every future
// meeting. Confirming a suggested name strengthens it the same way.

import SwiftUI

struct SpeakersTab: View {
    let meetingID: String
    let onChanged: () async -> Void

    @EnvironmentObject var model: AppModel
    @State private var assignments: [SpeakerAssignment] = []
    @State private var drafts: [Int: String] = [:]
    @State private var busy = false

    var body: some View {
        List(assignments) { assignment in
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(assignment.display_name ?? assignment.diarised_label)
                        .fontWeight(.medium)
                    Text(provenance(assignment))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                TextField("Name this voice", text: draftBinding(assignment))
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 200)
                    .onSubmit { save(assignment) }
                Button("Save name") { save(assignment) }
                    .disabled(busy || draft(assignment).isEmpty)
                if assignment.assigned_by != nil && assignment.confirmed == 0 {
                    Button("Confirm") { confirm(assignment) }
                        .disabled(busy)
                }
            }
            .padding(.vertical, 4)
        }
        .overlay {
            if assignments.isEmpty {
                Text("Speakers appear here once the meeting has been diarised.")
                    .foregroundStyle(.secondary)
            }
        }
        .task(id: meetingID) { await refresh() }
    }

    private func provenance(_ assignment: SpeakerAssignment) -> String {
        var parts = [assignment.diarised_label]
        switch assignment.assigned_by {
        case "enrolment":
            let score = assignment.match_score.map { String(format: "%.2f", $0) } ?? "?"
            parts.append(assignment.confirmed == 1
                ? "recognised and confirmed (\(score))"
                : "recognised automatically (\(score)); confirm or rename")
        case "attendee":
            parts.append("named from the attendee list")
        case "manual":
            parts.append("named by you; this voice is now remembered")
        default:
            parts.append("not recognised; give it a name and it will be from now on")
        }
        return parts.joined(separator: " · ")
    }

    private func draft(_ assignment: SpeakerAssignment) -> String {
        (drafts[assignment.id] ?? "").trimmingCharacters(in: .whitespaces)
    }

    private func draftBinding(_ assignment: SpeakerAssignment) -> Binding<String> {
        Binding(
            get: { drafts[assignment.id] ?? "" },
            set: { drafts[assignment.id] = $0 })
    }

    private func refresh() async {
        assignments = (try? await model.client.meetingSpeakers(meetingID)) ?? []
    }

    private func save(_ assignment: SpeakerAssignment) {
        let name = draft(assignment)
        guard !name.isEmpty else { return }
        busy = true
        Task {
            defer { busy = false }
            try? await model.client.nameSpeaker(assignment.id, name: name)
            drafts[assignment.id] = ""
            await refresh()
            await onChanged()
        }
    }

    private func confirm(_ assignment: SpeakerAssignment) {
        busy = true
        Task {
            defer { busy = false }
            try? await model.client.confirmSpeaker(assignment.id)
            await refresh()
            await onChanged()
        }
    }
}
