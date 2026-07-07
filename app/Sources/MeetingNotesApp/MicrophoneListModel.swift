// Keeps the microphone picker in step with reality: Core Audio notifies when
// the device list or the default devices change (AirPods connecting, a USB
// microphone unplugged), the list refreshes, and the remembered choice is
// re-selected when it comes back.

import CoreAudio
import Foundation
import MeetingNotesCore

/// Listens for audio hardware changes and calls back on the main queue.
final class AudioDeviceObserver {
    var onChange: (() -> Void)?

    private let selectors: [AudioObjectPropertySelector] = [
        kAudioHardwarePropertyDevices,
        kAudioHardwarePropertyDefaultInputDevice,
        kAudioHardwarePropertyDefaultOutputDevice,
    ]
    private var addresses: [AudioObjectPropertyAddress] = []
    private lazy var listener: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
        self?.onChange?()
    }

    init() {
        for selector in selectors {
            var address = AudioObjectPropertyAddress(
                mSelector: selector,
                mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain)
            let status = AudioObjectAddPropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, .main, listener)
            if status == noErr {
                addresses.append(address)
            }
        }
    }

    deinit {
        for var address in addresses {
            AudioObjectRemovePropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, .main, listener)
        }
    }
}

@MainActor
final class MicrophoneListModel: ObservableObject {
    @Published private(set) var devices: [InputDevice] = []
    @Published var selection: InputDevice? {
        didSet {
            guard let selection, selection.uid != oldValue?.uid else { return }
            preference.save(deviceUID: selection.uid)
        }
    }

    private let preference = MicrophonePreference(store: UserDefaults.standard)
    private let observer = AudioDeviceObserver()

    init() {
        observer.onChange = { [weak self] in
            Task { @MainActor in self?.refresh() }
        }
        refresh()
    }

    func refresh() {
        // The system-default entry is always first, so a fresh install
        // follows the Mac's input, and AirPods are used the moment they
        // become the default.
        devices = InputDevice.allWithDefault()
        let uid = MicrophoneSelection.choose(
            available: devices.map(\.uid),
            saved: preference.restore(),
            current: selection?.uid)
        let chosen = devices.first { $0.uid == uid } ?? InputDevice.systemDefault
        if chosen != selection {
            selection = chosen
        }
    }
}
