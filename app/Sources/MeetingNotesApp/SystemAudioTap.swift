// The Core Audio process tap: system audio without a bot in the call.
//
// The shape of this code follows how the macOS 14.4 tapping API actually
// behaves (see insidegui/AudioCap and makeusabrew/audiotee):
// - the first AudioHardwareCreateProcessTap call surfaces the TCC prompt;
// - the tap joins an aggregate device that has a real output device as its
//   main sub-device and the tap as a sub-tap, auto-started and private;
// - AVAudioEngine must NOT be pointed at the tap-backed aggregate device
//   (it quietly keeps reading the default input instead), so the aggregate
//   device is driven directly with an IO proc.

import CoreAudio
import Foundation
import MeetingNotesCore
import os

private let tapLog = Logger(subsystem: "co.uk.designturbine.meetingnotes", category: "system-audio-tap")

enum CaptureError: LocalizedError {
    case coreAudio(String, OSStatus)

    var errorDescription: String? {
        switch self {
        case .coreAudio(let what, let status):
            return "Audio capture failed while \(what) (Core Audio error \(status))."
        }
    }
}

final class SystemAudioTap {
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var ioProcID: AudioDeviceIOProcID?
    private(set) var sampleRate: Double = 48_000
    private var buffersReceived = 0

    /// Mono float samples at `sampleRate`, delivered from the IO thread.
    var onBuffer: (([Float]) -> Void)?

    func start() throws {
        let description = TapFactory.makeGlobalTapDescription()

        var tap = AudioObjectID(kAudioObjectUnknown)
        try check(AudioHardwareCreateProcessTap(description, &tap), "creating the system audio tap")
        tapID = tap
        tapLog.info("process tap created, id \(tap)")

        sampleRate = (try? tapFormat().mSampleRate) ?? 48_000
        tapLog.info("tap format sample rate \(self.sampleRate)")
        buffersReceived = 0

        let outputUID = try defaultOutputDeviceUID()
        let aggregateDescription: [String: Any] = [
            kAudioAggregateDeviceNameKey as String: "MeetingNotes capture device",
            kAudioAggregateDeviceUIDKey as String: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey as String: outputUID,
            kAudioAggregateDeviceIsPrivateKey as String: true,
            kAudioAggregateDeviceIsStackedKey as String: false,
            kAudioAggregateDeviceTapAutoStartKey as String: true,
            kAudioAggregateDeviceSubDeviceListKey as String: [
                [kAudioSubDeviceUIDKey as String: outputUID]
            ],
            kAudioAggregateDeviceTapListKey as String: [
                [
                    kAudioSubTapDriftCompensationKey as String: true,
                    kAudioSubTapUIDKey as String: description.uuid.uuidString,
                ]
            ],
        ]
        var aggregate = AudioObjectID(kAudioObjectUnknown)
        try check(
            AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregate),
            "creating the capture device")
        aggregateID = aggregate

        var procID: AudioDeviceIOProcID?
        try check(
            AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, nil) { [weak self] _, inputData, _, _, _ in
                self?.deliver(inputData.pointee)
            },
            "attaching to the capture device")
        ioProcID = procID
        try check(AudioDeviceStart(aggregateID, ioProcID), "starting the capture device")
        tapLog.info("capture device started, aggregate \(aggregate)")
    }

    func stop() {
        if buffersReceived == 0 {
            tapLog.warning("the system audio tap delivered no buffers for this recording; check Privacy and Security, Screen and System Audio Recording")
        } else {
            tapLog.info("tap delivered \(self.buffersReceived) buffers")
        }
        if aggregateID != AudioObjectID(kAudioObjectUnknown) {
            if let ioProcID {
                AudioDeviceStop(aggregateID, ioProcID)
                AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
            aggregateID = AudioObjectID(kAudioObjectUnknown)
        }
        if tapID != AudioObjectID(kAudioObjectUnknown) {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
        ioProcID = nil
    }

    // MARK: - Plumbing

    private func deliver(_ bufferList: AudioBufferList) {
        var list = bufferList
        let buffers = UnsafeMutableAudioBufferListPointer(&list)
        guard let onBuffer else { return }
        buffersReceived += 1
        if buffersReceived == 1 {
            tapLog.info("first tap buffer arrived")
        }
        for buffer in buffers {
            guard let data = buffer.mData else { continue }
            let channels = max(1, Int(buffer.mNumberChannels))
            let floatCount = Int(buffer.mDataByteSize) / MemoryLayout<Float>.size
            let frames = floatCount / channels
            guard frames > 0 else { continue }
            let floats = data.bindMemory(to: Float.self, capacity: floatCount)
            var mono = [Float](repeating: 0, count: frames)
            for frame in 0..<frames {
                var sum: Float = 0
                for channel in 0..<channels {
                    sum += floats[frame * channels + channel]
                }
                mono[frame] = sum / Float(channels)
            }
            onBuffer(mono)
        }
    }

    private func tapFormat() throws -> AudioStreamBasicDescription {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var format = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        try check(
            AudioObjectGetPropertyData(tapID, &address, 0, nil, &size, &format),
            "reading the tap format")
        return format
    }

    private func defaultOutputDeviceUID() throws -> String {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var deviceID = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        try check(
            AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID),
            "finding the output device")

        var uidAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var uid: CFString = "" as CFString
        var uidSize = UInt32(MemoryLayout<CFString>.size)
        try withUnsafeMutablePointer(to: &uid) { pointer in
            try check(
                AudioObjectGetPropertyData(deviceID, &uidAddress, 0, nil, &uidSize, pointer),
                "reading the output device identifier")
        }
        return uid as String
    }

    private func check(_ status: OSStatus, _ what: String) throws {
        guard status == noErr else { throw CaptureError.coreAudio(what, status) }
    }
}
