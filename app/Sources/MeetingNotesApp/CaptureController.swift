// Drives one recording: the process tap for system audio plus AVAudioEngine
// for the microphone, live level meters for both, and the mixdown to one
// 16 kHz mono WAV on stop. In-person meetings are the same path with system
// audio silent; the classifier notices and labels the meeting. The
// microphone is restarted whenever macOS stops it (see MicrophoneWatchdog), so
// the owner's side is kept for the whole meeting.

import AVFoundation
import CoreAudio
import Foundation
import MeetingNotesCore
import ObjCSupport
import os

private let captureLog = Logger(
    subsystem: Bundle.main.bundleIdentifier ?? "polenta", category: "capture")

@MainActor
final class CaptureController: ObservableObject {
    @Published var microphoneLevel: Float = 0
    @Published var systemLevel: Float = 0
    @Published private(set) var isCapturing = false
    /// The microphone has delivered nothing for a while and is being
    /// restarted; shown beside the level meters.
    @Published private(set) var microphoneWarning = false

    // The audio machinery is driven off the main thread (see start/stop), so
    // that Core Audio setup, which can block while the tap and aggregate
    // device are created, never freezes the UI. Access is serialised by
    // ioQueue and accumulationQueue.
    nonisolated(unsafe) private let tap = SystemAudioTap()
    // Replaced on every microphone (re)start: an engine that has seen its
    // input change keeps the old format, and a fresh one reads the current one.
    nonisolated(unsafe) private var engine = AVAudioEngine()
    nonisolated(unsafe) private var configurationObserver: NSObjectProtocol?
    nonisolated(unsafe) private var watchdog: DispatchSourceTimer?
    // Recording state for the watchdog, touched only on ioQueue. nil follows
    // the system default input.
    nonisolated(unsafe) private var microphoneDeviceID: AudioDeviceID?
    nonisolated(unsafe) private var recording = false
    nonisolated(unsafe) private var restartPending = false
    nonisolated(unsafe) private var warningShown = false
    nonisolated(unsafe) private var recordingStartedSeconds: Double = 0
    nonisolated(unsafe) private var lastMicrophoneRestartSeconds: Double = 0
    // When microphone audio last arrived (0 for none yet), written on the
    // audio thread and read by the watchdog; a plain Double is atomic on 64-bit.
    nonisolated(unsafe) private var lastMicrophoneBufferSeconds: Double = 0
    nonisolated(unsafe) private let classifier = SourceClassifier()

    // Streams are resampled to 16 kHz as they arrive and accumulated as
    // floats, so an hour of audio stays modest in memory. Each buffer is
    // placed at its true time against `originHostSeconds`, a single origin
    // shared by both channels (set by whichever buffer arrives first), so the
    // microphone and system streams stay on one clock and their WAVs line up.
    nonisolated(unsafe) private var microphoneSamples: [Float] = []
    nonisolated(unsafe) private var systemSamples: [Float] = []
    nonisolated(unsafe) private var originHostSeconds: Double?
    // When the system-audio stream last carried real signal, as a reference
    // timestamp. A plain Double load/store is atomic on 64-bit, so the auto-
    // stop timer can read it off the main thread without a lock. Used to tell
    // whether a call is still live past its scheduled end.
    nonisolated(unsafe) private var lastSystemActivitySeconds = Date().timeIntervalSinceReferenceDate
    private static let activityThreshold: Float = 0.004
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
            originHostSeconds = nil
        }
        let now = Date().timeIntervalSinceReferenceDate
        lastSystemActivitySeconds = now
        recordingStartedSeconds = now
        lastMicrophoneBufferSeconds = 0
        self.microphoneDeviceID = microphoneDeviceID
        recording = true

        try tap.start()
        // The delivery rate arrives per buffer, measured from the stream's own
        // timestamps: a Bluetooth output dropping to telephony rates mid-call
        // is resampled correctly instead of becoming double-speed chirp that
        // the transcriber's voice detection rejects.
        tap.onBuffer = { [weak self] mono, hostSeconds, rate in
            guard let self else { return }
            let level = LevelMeter.level(of: mono)
            if level > Self.activityThreshold {
                self.lastSystemActivitySeconds = Date().timeIntervalSinceReferenceDate
            }
            let resampled = AudioMixer.resample(mono, from: rate)
            self.accumulationQueue.async {
                self.classifier.observeSystem(mono)
                self.place(resampled, into: &self.systemSamples, atHostSeconds: hostSeconds)
            }
            Task { @MainActor in self.systemLevel = level }
        }

        // A microphone that cannot start yet does not stop the recording: the
        // watchdog keeps retrying it, and the person sees a warning meanwhile.
        startMicrophone()
        startWatchdog()
    }

    /// Starts, or restarts, the microphone on a fresh engine. Called on ioQueue.
    nonisolated private func startMicrophone() {
        lastMicrophoneRestartSeconds = Date().timeIntervalSinceReferenceDate
        stopMicrophone()
        engine = AVAudioEngine()
        // macOS stops the engine when its input changes (AirPods switching to
        // call mode, a device plugged in or removed). Restart once the change
        // has settled; several notices in a row become one restart.
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil
        ) { [weak self] _ in
            guard let self else { return }
            self.ioQueue.async { self.scheduleRestartAfterConfigurationChange() }
        }
        do {
            if let microphoneDeviceID {
                try selectInput(device: microphoneDeviceID)
            }
            try installMicTapAndStart()
        } catch {
            captureLog.error("could not start the microphone: \(error.localizedDescription, privacy: .public); retrying")
        }
    }

    nonisolated private func stopMicrophone() {
        if let configurationObserver {
            NotificationCenter.default.removeObserver(configurationObserver)
        }
        configurationObserver = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    nonisolated private func scheduleRestartAfterConfigurationChange() {
        guard recording, !restartPending else { return }
        restartPending = true
        captureLog.notice("microphone input changed; restarting it")
        ioQueue.asyncAfter(deadline: .now() + 0.5) {
            self.restartPending = false
            if self.recording { self.startMicrophone() }
        }
    }

    /// Once a second, restart a microphone that has stopped delivering and
    /// tell the person while it is not being recorded.
    nonisolated private func startWatchdog() {
        let timer = DispatchSource.makeTimerSource(queue: ioQueue)
        timer.schedule(deadline: .now() + 1, repeating: 1)
        timer.setEventHandler { [weak self] in self?.checkMicrophone() }
        timer.resume()
        watchdog = timer
    }

    nonisolated private func checkMicrophone() {
        guard recording else { return }
        let last = lastMicrophoneBufferSeconds
        let verdict = MicrophoneWatchdog.check(
            now: Date().timeIntervalSinceReferenceDate,
            lastBufferAt: last > 0 ? last : nil,
            startedAt: recordingStartedSeconds,
            lastRestartAt: lastMicrophoneRestartSeconds)
        if verdict.restart {
            captureLog.warning("no microphone audio is arriving; restarting the microphone")
            startMicrophone()
        }
        if verdict.warn != warningShown {
            warningShown = verdict.warn
            let warn = verdict.warn
            Task { @MainActor in self.microphoneWarning = warn }
        }
    }

    nonisolated private func installMicTapAndStart() throws {
        let input = engine.inputNode
        let output = input.outputFormat(forBus: 0)
        let hardware = input.inputFormat(forBus: 0)
        // AVAudioEngine aborts the whole app with an uncatchable NSException if
        // the tap format is invalid or its sample rate disagrees with the input
        // hardware -- exactly what a Bluetooth microphone (AirPods) does when it
        // switches rate as it becomes active. Two defences: only attempt the tap
        // when the formats are valid and agree, and wrap installTap so any
        // exception that still slips through (a device change mid-call) is
        // caught. A tap format of nil makes the engine use the node's own
        // format, so there is no stale format to mismatch. If the microphone
        // cannot be tapped safely yet, carry on with the system audio rather
        // than crash; the watchdog tries again on a fresh engine.
        let micUsable = output.channelCount > 0 && output.sampleRate > 0
            && hardware.sampleRate > 0 && hardware.sampleRate == output.sampleRate
        if micUsable {
            let failure = ObjCTryCatch {
                input.installTap(onBus: 0, bufferSize: 4096, format: nil) { [weak self] buffer, when in
                    guard let self, let channel = buffer.floatChannelData?[0] else { return }
                    self.lastMicrophoneBufferSeconds = Date().timeIntervalSinceReferenceDate
                    let mono = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
                    let level = LevelMeter.level(of: mono)
                    let resampled = AudioMixer.resample(mono, from: buffer.format.sampleRate)
                    let hostSeconds = Self.hostSeconds(when)
                    self.accumulationQueue.async {
                        self.place(resampled, into: &self.microphoneSamples, atHostSeconds: hostSeconds)
                    }
                    Task { @MainActor in self.microphoneLevel = level }
                }
            }
            if failure != nil {
                captureLog.error("could not tap the microphone; retrying")
            }
        } else {
            captureLog.warning("microphone format unavailable or mismatched; retrying")
        }
        engine.prepare()
        try engine.start()
    }

    /// Places a resampled buffer into a channel on the shared capture clock,
    /// initialising the origin from the first buffer of either channel. Called
    /// on `accumulationQueue`, so the origin and the sample arrays are only
    /// touched by one thread.
    nonisolated private func place(
        _ block: [Float], into samples: inout [Float], atHostSeconds hostSeconds: Double
    ) {
        let origin: Double
        if let existing = originHostSeconds {
            origin = existing
        } else {
            originHostSeconds = hostSeconds
            origin = hostSeconds
        }
        AudioMixer.place(block, into: &samples, atHostSeconds: hostSeconds, origin: origin)
    }

    /// The host time of an AVAudioTime in seconds, falling back to now when the
    /// engine does not stamp a valid host time.
    nonisolated private static func hostSeconds(_ when: AVAudioTime) -> Double {
        HostClock.seconds(when.isHostTimeValid ? when.hostTime : mach_absolute_time())
    }

    /// How long the system-audio (call) stream has been silent, for the auto-
    /// stop timer to tell whether a call is still live past its scheduled end.
    nonisolated func secondsSinceSystemActivity() -> TimeInterval {
        Date().timeIntervalSinceReferenceDate - lastSystemActivitySeconds
    }

    /// Switch the microphone mid-recording without stopping. System audio is
    /// unaffected; the microphone has a brief gap while the engine restarts.
    /// nil follows the system default input.
    func switchInput(to deviceID: AudioDeviceID?) async {
        guard isCapturing else { return }
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            ioQueue.async {
                self.performSwitchInput(to: deviceID)
                continuation.resume()
            }
        }
    }

    nonisolated private func performSwitchInput(to deviceID: AudioDeviceID?) {
        // A fresh engine follows the system default by itself when deviceID
        // is nil. A failure here is retried by the watchdog.
        microphoneDeviceID = deviceID
        startMicrophone()
    }

    /// Stops capture off the main thread and returns the microphone and system
    /// channels separately, a mixed stream for playback, and the source.
    func stop() async -> CaptureResult {
        let result = await withCheckedContinuation { (continuation: CheckedContinuation<CaptureResult, Never>) in
            ioQueue.async {
                continuation.resume(returning: self.performStop())
            }
        }
        isCapturing = false
        microphoneWarning = false
        microphoneLevel = 0
        systemLevel = 0
        return result
    }

    nonisolated private func performStop() -> CaptureResult {
        recording = false
        watchdog?.cancel()
        watchdog = nil
        warningShown = false
        stopMicrophone()
        tap.onBuffer = nil
        tap.stop()

        let (mic, system, source) = accumulationQueue.sync {
            (microphoneSamples, systemSamples, classifier.source)
        }
        let mixed = AudioMixer.mixToMono16k(
            microphone: mic, microphoneRate: Double(AudioMixer.targetSampleRate),
            system: system, systemRate: Double(AudioMixer.targetSampleRate))
        return CaptureResult(
            mic: AudioMixer.monoWav(from: mic),
            system: AudioMixer.monoWav(from: system),
            mixed: AudioMixer.wavData(samples: mixed),
            source: source)
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

    static let systemDefaultUID = "system-default"

    /// Follows whatever the Mac's default input is, so AirPods are used
    /// automatically once they are the system default.
    static let systemDefault = InputDevice(
        id: AudioDeviceID(kAudioObjectUnknown),
        uid: systemDefaultUID,
        name: "System default (follows the Mac)")

    /// The device id to hand to capture, or nil to let the engine follow the
    /// system default.
    var captureDeviceID: AudioDeviceID? {
        uid == InputDevice.systemDefaultUID ? nil : id
    }

    /// The system-default entry first, then the specific devices.
    static func allWithDefault() -> [InputDevice] {
        [systemDefault] + all()
    }

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
