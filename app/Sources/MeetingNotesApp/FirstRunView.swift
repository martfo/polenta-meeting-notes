// The guided first run: provision the backend into Application Support with
// a progress view (not a terminal), store the Hugging Face token in the
// Keychain, and point at LM Studio. A failure shows a plain message and a
// Retry, never a half-built state.

import MeetingNotesCore
import Security
import SwiftUI

enum KeychainTokenStore {
    static let service = "MeetingNotes"
    static let account = "huggingface-token"

    static func save(token: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var attributes = query
        attributes[kSecValueData as String] = Data(token.utf8)
        return SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess
    }
}

@MainActor
final class FirstRunModel: ObservableObject {
    @Published var state: Provisioner.State = .notStarted
    @Published var currentStep = ""

    func provision() {
        let runtime = RuntimeLocation.runtimeDirectory()
        guard let installer = RealRuntimeInstaller() else {
            state = .failed(
                "This build has no bundled installer. Run from a checkout with "
                + "MEETINGNOTES_BACKEND_PYTHON set instead.")
            return
        }
        let provisioner = Provisioner(runtime: runtime, installer: installer)
        provisioner.onStep = { [weak self] step in
            Task { @MainActor in self?.currentStep = step }
        }
        state = .inProgress(step: "Starting")
        Task.detached(priority: .userInitiated) {
            let result = provisioner.provision()
            await MainActor.run { self.state = result }
        }
    }
}

struct FirstRunView: View {
    @StateObject private var model = FirstRunModel()
    @State private var token = ""
    @State private var tokenSaved = false
    let onFinished: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("First-run setup").font(.title)
            Text("The app fetches its own backend and, on the next screen, the "
                 + "speech models. This is the only time it uses the network.")
                .foregroundStyle(.secondary)

            GroupBox("Hugging Face token") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("The speaker model needs a Hugging Face token and a "
                         + "one-time licence acceptance. The token is stored in "
                         + "the macOS Keychain, never in a file.")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        SecureField("hf_...", text: $token)
                        Button("Store in Keychain") {
                            tokenSaved = KeychainTokenStore.save(token: token)
                        }
                        .disabled(token.isEmpty)
                        if tokenSaved { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green) }
                    }
                }
                .padding(6)
            }

            GroupBox("Backend") {
                VStack(alignment: .leading, spacing: 8) {
                    switch model.state {
                    case .notStarted:
                        Button("Set up the backend") { model.provision() }
                    case .inProgress:
                        ProgressView(model.currentStep)
                    case .ready:
                        Label("The backend is ready.", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                        Button("Continue") { onFinished() }
                    case .failed(let message):
                        Text(message).foregroundStyle(.red).font(.caption)
                        Button("Retry") { model.provision() }
                    }
                }
                .padding(6)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(28)
        .frame(maxWidth: 560)
    }
}
