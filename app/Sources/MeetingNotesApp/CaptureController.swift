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

    private let tap = SystemAudioTap()
    private let engine = AVAudioEngine()
    private let classifier = SourceClassifier()

    // Streams are resampled to 16 kHz as they arrive and accumulated as
    // floats, so an hour of audio stays modest in memory.
    private var microphoneSamples: [Float] = []
    private var systemSamples: [Float] = []
    private let accumulationQueue = DispatchQueue(label: "capture.accumulate")

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

    func start(microphoneDeviceID: AudioDeviceID?) throws {
        microphoneSamples = []
        systemSamples = []

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
        isCapturing = true
    }

    /// Stops capture and returns the mixed WAV plus the detected source.
    func stop() -> (wavData: Data, source: MeetingSource) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        tap.onBuffer = nil
        tap.stop()
        isCapturing = false
        microphoneLevel = 0
        systemLevel = 0

        let (mic, system, source) = accumulationQueue.sync {
            (microphoneSamples, systemSamples, classifier.source)
        }
        let mixed = AudioMixer.mixToMono16k(
            microphone: mic, microphoneRate: Double(AudioMixer.targetSampleRate),
            system: system, systemRate: Double(AudioMixer.targetSampleRate))
        return (AudioMixer.wavData(samples: mixed), source)
    }

    private func selectInput(device: AudioDeviceID) throws {
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
