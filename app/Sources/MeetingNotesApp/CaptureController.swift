// Drives one recording: the process tap for system audio plus AVAudioEngine
// for the microphone, live level meters for both, and the mixdown to one
// 16 kHz mono WAV on stop. In-person meetings are the same path with system
// audio silent; the classifier notices and labels the meeting.

import AVFoundation
import CoreAudio
import Foundation
import MeetingNotesCore

@MainActor
final class CaptureController: ObservableObject {
    @Published var microphoneLevel: Float = 0
    @Published var systemLevel: Float = 0
    @Published private(set) var isCapturing = false

    // The audio machinery is driven off the main thread (see start/stop), so
    // that Core Audio setup, which can block while the tap and aggregate
    // device are created, never freezes the UI. Access is serialised by
    // ioQueue and accumulationQueue.
    nonisolated(unsafe) private let tap = SystemAudioTap()
    nonisolated(unsafe) private let engine = AVAudioEngine()
    nonisolated(unsafe) private let classifier = SourceClassifier()

    // Streams are resampled to 16 kHz as they arrive and accumulated as
    // floats, so an hour of audio stays modest in memory.
    nonisolated(unsafe) private var microphoneSamples: [Float] = []
    nonisolated(unsafe) private var systemSamples: [Float] = []
    private let accumulationQueue = DispatchQueue(label: "capture.accumulate")
    private let ioQueue = DispatchQueue(label: "capture.io")

    static func requestMicrophoneAccess() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .audio)
    }

    static func microphonePermission() -> PermissionStatus {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return .granted
        case .denied, .restricted: return .denied
        default: return .undetermined
        }
    }

    /// Starts capture off the main thread, so blocking Core Audio setup never
    /// beachballs the UI. `isCapturing` flips on the main actor once ready.
    func start(microphoneDeviceID: AudioDeviceID?) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            ioQueue.async {
                do {
                    try self.performStart(microphoneDeviceID: microphoneDeviceID)
                    continuation.resume()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
        isCapturing = true
    }

    nonisolated private func performStart(microphoneDeviceID: AudioDeviceID?) throws {
        accumulationQueue.sync {
            microphoneSamples = []
            systemSamples = []
        }

        try tap.start()
        let tapRate = tap.sampleRate
        tap.onBuffer = { [weak self] mono in
            guard let self else { return }
            let level = LevelMeter.level(of: mono)
            let resampled = AudioMixer.resample(mono, from: tapRate)
            self.accumulationQueue.async {
                self.classifier.observeSystem(mono)
                self.systemSamples.append(contentsOf: resampled)
            }
            Task { @MainActor in self.systemLevel = level }
        }

        if let microphoneDeviceID {
            try selectInput(device: microphoneDeviceID)
        }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        let inputRate = format.sampleRate
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            guard let self, let channel = buffer.floatChannelData?[0] else { return }
            let mono = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
            let level = LevelMeter.level(of: mono)
            let resampled = AudioMixer.resample(mono, from: inputRate)
            self.accumulationQueue.async {
                self.microphoneSamples.append(contentsOf: resampled)
            }
            Task { @MainActor in self.microphoneLevel = level }
        }
        engine.prepare()
        try engine.start()
    }

    /// Stops capture off the main thread and returns the mixed WAV plus the
    /// detected source.
    func stop() async -> (wavData: Data, source: MeetingSource) {
        let result = await withCheckedContinuation { (continuation: CheckedContinuation<(Data, MeetingSource), Never>) in
            ioQueue.async {
                continuation.resume(returning: self.performStop())
            }
        }
        isCapturing = false
        microphoneLevel = 0
        systemLevel = 0
        return result
    }

    nonisolated private func performStop() -> (wavData: Data, source: MeetingSource) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        tap.onBuffer = nil
        tap.stop()

        let (mic, system, source) = accumulationQueue.sync {
            (microphoneSamples, systemSamples, classifier.source)
        }
        let mixed = AudioMixer.mixToMono16k(
            microphone: mic, microphoneRate: Double(AudioMixer.targetSampleRate),
            system: system, systemRate: Double(AudioMixer.targetSampleRate))
        return (AudioMixer.wavData(samples: mixed), source)
    }

    nonisolated private func selectInput(device: AudioDeviceID) throws {
        guard let unit = engine.inputNode.audioUnit else { return }
        var deviceID = device
        let status = AudioUnitSetProperty(
            unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global,
            0, &deviceID, UInt32(MemoryLayout<AudioDeviceID>.size))
        guard status == noErr else { throw CaptureError.coreAudio("choosing the microphone", status) }
    }
}

// MARK: - Input device listing for the picker

struct InputDevice: Identifiable, Hashable {
    let id: AudioDeviceID
    let uid: String
    let name: String

    static func all() -> [InputDevice] {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size) == noErr else { return [] }
        var deviceIDs = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceIDs) == noErr else { return [] }

        return deviceIDs.compactMap { deviceID in
            guard inputChannelCount(deviceID) > 0,
                  let name = stringProperty(deviceID, kAudioObjectPropertyName),
                  let uid = stringProperty(deviceID, kAudioDevicePropertyDeviceUID)
            else { return nil }
            return InputDevice(id: deviceID, uid: uid, name: name)
        }
    }

    private static func inputChannelCount(_ deviceID: AudioDeviceID) -> Int {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: kAudioDevicePropertyScopeInput,
            mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let listPointer = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { listPointer.deallocate() }
        guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, listPointer) == noErr else { return 0 }
        let buffers = UnsafeMutableAudioBufferListPointer(listPointer.assumingMemoryBound(to: AudioBufferList.self))
        return buffers.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    private static func stringProperty(_ deviceID: AudioDeviceID, _ selector: AudioObjectPropertySelector) -> String? {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var value: CFString = "" as CFString
        var size = UInt32(MemoryLayout<CFString>.size)
        let status = withUnsafeMutablePointer(to: &value) {
            AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, $0)
        }
        return status == noErr ? (value as String) : nil
    }
}
