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

    /// Written through the security tool rather than SecItemAdd, for the same
    /// reason the backend reads through it: a token first stored from the
    /// terminal belongs to that tool's access list, and SecItemAdd from the
    /// app collides with it as an untouchable duplicate. The -U flag updates
    /// an existing item in place.
    static func save(token: String) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = [
            "add-generic-password", "-U",
            "-s", service, "-a", account, "-w", token,
        ]
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        do {
            try process.run()
        } catch {
            return false
        }
        process.waitUntilExit()
        return process.terminationStatus == 0
    }
}

struct TokenCheck: Identifiable {
    let id = UUID()
    let passed: Bool
    let message: String
}

@MainActor
final class FirstRunModel: ObservableObject {
    @Published var state: Provisioner.State = .notStarted
    @Published var currentStep = ""
    @Published var tokenChecks: [TokenCheck] = []
    @Published var checkingToken = false

    static let tokenPage = URL(string: "https://huggingface.co/settings/tokens")!
    static let gatedRepos = [
        "pyannote/speaker-diarization-community-1",
        "pyannote/embedding",
    ]

    func storeAndVerify(token: String) {
        tokenChecks = []
        guard KeychainTokenStore.save(token: token) else {
            tokenChecks = [TokenCheck(passed: false, message: "The token could not be stored in the Keychain.")]
            return
        }
        checkingToken = true
        Task {
            defer { checkingToken = false }
            tokenChecks = await Self.verify(token: token)
        }
    }

    /// Live checks against Hugging Face, so a wrong token or an unaccepted
    /// licence shows up here, not as a failed transcription later. First run
    /// is the online step, so the network is available.
    static func verify(token: String) async -> [TokenCheck] {
        var checks: [TokenCheck] = []

        var whoami = URLRequest(url: URL(string: "https://huggingface.co/api/whoami-v2")!)
        whoami.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await URLSession.shared.data(for: whoami)
            if (response as? HTTPURLResponse)?.statusCode == 200,
               let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let name = body["name"] as? String {
                checks.append(TokenCheck(passed: true, message: "Token stored and accepted. Signed in as \(name)."))
            } else {
                checks.append(TokenCheck(
                    passed: false,
                    message: "Hugging Face did not accept this token. Create a Read token with the link above and paste the whole hf_ value."))
                return checks
            }
        } catch {
            checks.append(TokenCheck(passed: false, message: "Hugging Face could not be reached. Check the network and try again."))
            return checks
        }

        for repo in gatedRepos {
            var probe = URLRequest(url: URL(string: "https://huggingface.co/\(repo)/resolve/main/config.yaml")!)
            probe.httpMethod = "HEAD"
            probe.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            let status = (try? await URLSession.shared.data(for: probe))
                .flatMap { ($0.1 as? HTTPURLResponse)?.statusCode } ?? 0
            if status == 200 {
                checks.append(TokenCheck(passed: true, message: "Access to \(repo) is granted."))
            } else {
                checks.append(TokenCheck(
                    passed: false,
                    message: "No access to \(repo) yet. Open its page with the link above, press "
                        + "\u{201C}Agree and access repository\u{201D}, then check again."))
            }
        }
        return checks
    }

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
    let onFinished: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("First-run setup").font(.title)
                Text("The app fetches its own backend and the speech models. This "
                     + "is the only time it uses the network; after setup it runs "
                     + "entirely on this Mac.")
                    .foregroundStyle(.secondary)

                GroupBox("Step 1: Hugging Face token") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("The speaker models come from Hugging Face. You need a free "
                             + "account, a one-time acceptance of each model's terms, and a "
                             + "Read token. The token is stored in the macOS Keychain, never "
                             + "in a file.")
                            .font(.callout)
                            .foregroundStyle(.secondary)

                        VStack(alignment: .leading, spacing: 6) {
                            Link("1. Create a free account and a Read token (huggingface.co/settings/tokens)",
                                 destination: FirstRunModel.tokenPage)
                            Link("2. Accept the terms for speaker-diarization-community-1",
                                 destination: URL(string: "https://huggingface.co/pyannote/speaker-diarization-community-1")!)
                            Link("3. Accept the terms for pyannote/embedding",
                                 destination: URL(string: "https://huggingface.co/pyannote/embedding")!)
                            Text("4. Paste the token below (it starts with hf_) and press Store and check.")
                        }
                        .font(.callout)

                        HStack {
                            SecureField("hf_...", text: $token)
                            Button("Store and check") {
                                model.storeAndVerify(token: token.trimmingCharacters(in: .whitespaces))
                            }
                            .disabled(token.trimmingCharacters(in: .whitespaces).isEmpty || model.checkingToken)
                            if model.checkingToken { ProgressView().controlSize(.small) }
                        }

                        ForEach(model.tokenChecks) { check in
                            Label {
                                Text(check.message).font(.callout)
                            } icon: {
                                Image(systemName: check.passed ? "checkmark.circle.fill" : "xmark.circle.fill")
                                    .foregroundStyle(check.passed ? .green : .red)
                            }
                        }
                    }
                    .padding(6)
                }

                GroupBox("Step 2: the backend") {
                    VStack(alignment: .leading, spacing: 8) {
                        switch model.state {
                        case .notStarted:
                            Text("The app installs its transcription backend into Application "
                                 + "Support. This downloads a few gigabytes the first time.")
                                .font(.callout).foregroundStyle(.secondary)
                            Button("Set up the backend") { model.provision() }
                        case .inProgress:
                            ProgressView(model.currentStep)
                        case .ready:
                            Label("The backend is ready.", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Button("Continue") { onFinished() }
                                .keyboardShortcut(.defaultAction)
                        case .failed(let message):
                            Text(message).foregroundStyle(.red).font(.callout)
                            Button("Retry") { model.provision() }
                        }
                    }
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(28)
            .frame(maxWidth: 620)
        }
    }
}
