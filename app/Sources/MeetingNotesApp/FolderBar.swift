// Filing a meeting. Folders are flat and a meeting belongs to exactly one.
// The menu lists the existing folders and creates new ones; for an unfiled
// meeting the model's suggestion is offered pre-selected, to accept or
// ignore.

import SwiftUI

struct FolderBar: View {
    let meetingID: String
    let currentFolder: String?
    let onChanged: () async -> Void

    @EnvironmentObject var model: AppModel
    @State private var folders: [String] = []
    @State private var suggestion: String?
    @State private var askingForName = false
    @State private var newFolderName = ""

    var body: some View {
        HStack(spacing: 10) {
            Menu {
                ForEach(folders, id: \.self) { folder in
                    Button {
                        file(in: folder)
                    } label: {
                        if folder == currentFolder {
                            Label(folder, systemImage: "checkmark")
                        } else {
                            Text(folder)
                        }
                    }
                }
                if !folders.isEmpty { Divider() }
                Button("New folder…") {
                    newFolderName = ""
                    askingForName = true
                }
            } label: {
                Label(currentFolder ?? "File in a folder", systemImage: "folder")
            }
            .frame(maxWidth: 260, alignment: .leading)

            if currentFolder == nil, let suggestion {
                Text("Suggested: \(suggestion)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button("Accept") { file(in: suggestion) }
                    .controlSize(.small)
            }
            Spacer()
        }
        .task(id: meetingID) {
            folders = (try? await model.client.folders()) ?? []
            if currentFolder == nil {
                suggestion = try? await model.client.suggestFolder(meetingID)
            }
        }
        .alert("New folder", isPresented: $askingForName) {
            TextField("Folder name", text: $newFolderName)
            Button("Create and file") {
                let name = newFolderName.trimmingCharacters(in: .whitespaces)
                if !name.isEmpty { file(in: name) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Folders are flat: a name, no nesting. The meeting moves into it.")
        }
    }

    private func file(in folder: String) {
        Task {
            try? await model.client.fileMeeting(meetingID, folder: folder)
            folders = (try? await model.client.folders()) ?? folders
            suggestion = nil
            await onChanged()
        }
    }
}
