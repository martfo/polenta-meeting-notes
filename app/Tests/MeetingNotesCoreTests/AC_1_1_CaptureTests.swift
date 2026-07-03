// Sections 1.0 (app side) and 1.1: audio capture logic.

import Foundation
import Testing
@testable import MeetingNotesCore

// MARK: - Test doubles

final class MemoryStore: KeyValueStore {
    private var values: [String: String] = [:]
    func string(forKey key: String) -> String? { values[key] }
    func set(_ value: String?, forKey key: String) { values[key] = value }
}

final class FakeBackend: BackendEnqueuing {
    var reachable = true
    private(set) var imported: [(audioPath: String, title: String, source: String)] = []

    struct Down: Error {}

    @discardableResult
    func importMeeting(audioPath: String, title: String, source: String) throws -> String {
        guard reachable else { throw Down() }
        imported.append((audioPath, title, source))
        return "meeting-\(imported.count)"
    }
}

func temporaryDirectory() -> URL {
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("meetingnotes-tests-\(UUID().uuidString)")
    try! FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}

func makeCoordinator(backend: FakeBackend) -> RecordingCoordinator {
    let dir = temporaryDirectory()
    return RecordingCoordinator(
        capturesDirectory: dir.appendingPathComponent("captures"),
        backend: backend,
        pending: FilePendingJobStore(fileURL: dir.appendingPathComponent("pending.json"))
    )
}

// MARK: - Tests

struct AC_1_1_CaptureTests {
    @Test("AC-1.1-a tap description is global, private, unmuted, with a uuid")
    func test_ac_1_1_a_tap_description_factory() {
        let description = TapFactory.makeGlobalTapDescription()
        #expect(description.isPrivate)
        #expect(description.muteBehavior == .unmuted)
        #expect(description.uuid.uuidString.isEmpty == false)
        #expect(description.name.isEmpty == false)
        #expect(description.processes.isEmpty, "a global tap excludes nothing")
        #expect(description.isExclusive, "global-but-exclude form captures everything else")
    }

    @Test("AC-1.1-b Info.plist carries both usage keys")
    func test_ac_1_1_b_info_plist_usage_keys() throws {
        let plistURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // MeetingNotesCoreTests
            .deletingLastPathComponent()  // Tests
            .deletingLastPathComponent()  // app
            .appendingPathComponent("Support/Info.plist")
        let data = try Data(contentsOf: plistURL)
        let plist = try PropertyListSerialization.propertyList(from: data, format: nil)
        let dict = try #require(plist as? [String: Any])

        let audio = try #require(dict["NSAudioCaptureUsageDescription"] as? String)
        let microphone = try #require(dict["NSMicrophoneUsageDescription"] as? String)
        #expect(!audio.isEmpty)
        #expect(!microphone.isEmpty)
    }

    @Test("AC-1.1-c mixer produces a single 16 kHz mono WAV of the right length")
    func test_ac_1_1_c_mixer_16k_mono() {
        // One second of microphone at 48 kHz, one second of system audio at
        // 44.1 kHz, constant amplitudes so the mix is predictable.
        let mic = [Float](repeating: 0.5, count: 48_000)
        let system = [Float](repeating: -0.25, count: 44_100)

        let samples = AudioMixer.mixToMono16k(
            microphone: mic, microphoneRate: 48_000,
            system: system, systemRate: 44_100)

        #expect(abs(samples.count - 16_000) <= 1, "one second at 16 kHz")
        let expected = Int16((0.5 - 0.25) * 0.5 * Float(Int16.max))
        #expect(abs(Int(samples[8_000]) - Int(expected)) <= 1)

        let wav = AudioMixer.wavData(samples: samples)
        #expect(wav.count == 44 + samples.count * 2)
        #expect(String(data: wav.prefix(4), encoding: .ascii) == "RIFF")
        let channels = wav.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 22, as: UInt16.self) }
        let rate = wav.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 24, as: UInt32.self) }
        let bits = wav.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 34, as: UInt16.self) }
        #expect(channels == 1)
        #expect(rate == 16_000)
        #expect(bits == 16)
    }

    @Test("AC-1.1-d input levels for microphone and system audio")
    func test_ac_1_1_d_input_levels() {
        let loud = [Float](repeating: 0.5, count: 1_000)
        let quiet = [Float](repeating: 0.01, count: 1_000)
        let silent = [Float](repeating: 0, count: 1_000)

        #expect(abs(LevelMeter.level(of: loud) - 0.5) < 0.001)
        #expect(abs(LevelMeter.level(of: quiet) - 0.01) < 0.001)
        #expect(LevelMeter.level(of: silent) == 0)
        #expect(LevelMeter.level(of: []) == 0)
        // Both streams are metered the same way: one level per buffer.
        #expect(LevelMeter.level(of: loud) > LevelMeter.level(of: quiet))
    }

    @Test("AC-1.1-e chosen microphone saved and restored")
    func test_ac_1_1_e_microphone_preference() {
        let store = MemoryStore()
        MicrophonePreference(store: store).save(deviceUID: "BuiltInMicrophoneDevice-UID")

        // A fresh preference over the same store is "the next launch".
        let restored = MicrophonePreference(store: store).restore()
        #expect(restored == "BuiltInMicrophoneDevice-UID")
        #expect(MicrophonePreference(store: MemoryStore()).restore() == nil)
    }

    @Test("AC-1.1-f silent system audio flags the meeting as in-person")
    func test_ac_1_1_f_in_person_classifier() {
        let silent = SourceClassifier()
        for _ in 0..<50 { silent.observeSystem([Float](repeating: 0, count: 512)) }
        #expect(silent.source == .inPerson)

        let call = SourceClassifier()
        call.observeSystem([Float](repeating: 0, count: 512))
        call.observeSystem([0, 0.2, -0.1, 0])
        #expect(call.source == .online)
    }

    @Test("AC-1.1-g stop enqueues and a new recording can start at once")
    func test_ac_1_1_g_stop_enqueues_and_restarts() throws {
        let backend = FakeBackend()
        let coordinator = makeCoordinator(backend: backend)
        let wav = AudioMixer.wavData(samples: [Int16](repeating: 0, count: 160))

        coordinator.start()
        let outcome = try coordinator.stop(wavData: wav, title: "Meeting A", source: .online)

        #expect(outcome == .enqueued(meetingID: "meeting-1"))
        #expect(backend.imported.count == 1)
        #expect(coordinator.isRecording == false)
        // Meeting A is only queued, not processed, and B can start now.
        coordinator.start()
        #expect(coordinator.isRecording)
    }

    @Test("AC-1.1-h denied permissions map to a clear error state")
    func test_ac_1_1_h_permission_error_states() {
        #expect(CaptureReadiness.evaluate(microphone: .granted, systemAudio: .granted) == .ready)
        #expect(CaptureReadiness.evaluate(microphone: .undetermined, systemAudio: .granted) == .awaitingConsent)

        for (mic, sys, needle) in [
            (PermissionStatus.denied, PermissionStatus.granted, "Microphone"),
            (.granted, .denied, "System audio"),
        ] {
            guard case .blocked(let message) = CaptureReadiness.evaluate(microphone: mic, systemAudio: sys) else {
                Issue.record("expected a blocked state for \(mic)/\(sys)")
                continue
            }
            #expect(message.contains(needle))
            #expect(message.contains("System Settings"), "the message says where to fix it")
        }

        // Both denied: both problems reported at once.
        guard case .blocked(let message) = CaptureReadiness.evaluate(microphone: .denied, systemAudio: .denied) else {
            Issue.record("expected a blocked state"); return
        }
        #expect(message.contains("Microphone") && message.contains("System audio"))
    }

    @Test("AC-1.0-f backend down at capture: audio kept, job pending, enqueued later")
    func test_ac_1_0_f_backend_down_at_capture() throws {
        let backend = FakeBackend()
        backend.reachable = false
        let coordinator = makeCoordinator(backend: backend)
        let wav = AudioMixer.wavData(samples: [Int16](repeating: 0, count: 160))

        coordinator.start()
        let outcome = try coordinator.stop(wavData: wav, title: "Offline capture", source: .inPerson)

        #expect(outcome == .pendingBackend)
        #expect(backend.imported.isEmpty)

        // The audio is safe on disk even though the backend never saw it.
        coordinator.start()
        let second = try coordinator.stop(wavData: wav, title: "Second", source: .online)
        #expect(second == .pendingBackend)

        // The backend comes back: everything pending is enqueued.
        backend.reachable = true
        let flushed = coordinator.flushPending()
        #expect(flushed == 2)
        #expect(backend.imported.map(\.title) == ["Offline capture", "Second"])
        #expect(FileManager.default.fileExists(atPath: backend.imported[0].audioPath))
        #expect(coordinator.flushPending() == 0, "nothing left pending")
    }
}
