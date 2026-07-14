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
    private var rateEstimator = SampleRateEstimator(initialRate: 48_000)
    private var lastLoggedRate: Double = 0

    /// Mono float samples with the host time (seconds) of the buffer's first
    /// sample and the stream's measured delivery rate. The host time puts the
    /// system channel on the same clock as the microphone; the per-buffer rate
    /// follows mid-recording device rate switches (a Bluetooth headset dropping
    /// to telephony rates when its microphone engages), which a rate read once
    /// at start silently mislabels into double-speed chirp.
    var onBuffer: (([Float], Double, Double) -> Void)?

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

        // The IO proc delivers at the aggregate device's rate, which follows
        // its main sub-device (the output), not the tap's own format — and it
        // can change mid-recording. Seed the estimator with the device's
        // nominal rate and let the per-buffer timestamps track the truth.
        let nominal = nominalSampleRate(of: aggregateID) ?? sampleRate
        rateEstimator = SampleRateEstimator(initialRate: nominal)
        lastLoggedRate = nominal
        tapLog.info("aggregate nominal sample rate \(nominal)")

        var procID: AudioDeviceIOProcID?
        try check(
            AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, nil) { [weak self] _, inputData, inputTime, _, _ in
                self?.deliver(inputData.pointee, at: inputTime.pointee)
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

    private func deliver(_ bufferList: AudioBufferList, at inputTime: AudioTimeStamp) {
        var list = bufferList
        let buffers = UnsafeMutableAudioBufferListPointer(&list)
        guard let onBuffer else { return }
        buffersReceived += 1
        if buffersReceived == 1 {
            tapLog.info("first tap buffer arrived")
        }
        // The IO proc stamps each buffer with the host time of its first frame;
        // fall back to now if the driver leaves it invalid, so the system
        // channel still shares the microphone's clock.
        let hostValid = inputTime.mFlags.contains(.hostTimeValid)
        let hostSeconds = HostClock.seconds(hostValid ? inputTime.mHostTime : mach_absolute_time())
        // Sample time against host time measures the true delivery rate, so a
        // mid-recording device rate switch is followed instead of mislabelled.
        var rate = rateEstimator.rate
        if hostValid, inputTime.mFlags.contains(.sampleTimeValid) {
            rate = rateEstimator.update(sampleTime: inputTime.mSampleTime, hostSeconds: hostSeconds)
        }
        if abs(rate - lastLoggedRate) / max(lastLoggedRate, 1) > 0.05 {
            tapLog.warning("system audio delivery rate changed \(self.lastLoggedRate) -> \(rate)")
            lastLoggedRate = rate
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
            onBuffer(mono, hostSeconds, rate)
        }
    }

    private func nominalSampleRate(of deviceID: AudioObjectID) -> Double? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyNominalSampleRate,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var rate = Float64(0)
        var size = UInt32(MemoryLayout<Float64>.size)
        let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &rate)
        return status == noErr && rate > 0 ? rate : nil
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
