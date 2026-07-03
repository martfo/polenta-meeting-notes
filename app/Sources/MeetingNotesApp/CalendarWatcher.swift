// Watches the macOS calendar store and the running applications, and offers
// to start recording when a meeting is due or a call app is in use. The
// offer carries the invite's title and attendees so speaker naming can use
// them. Auto-detection is a prompt to start, never an automatic recording.
//
// The calendar is read through EventKit, so any account synced into macOS
// Calendar (Google, Exchange, iCloud) works with one read-only permission
// and no OAuth setup.

import AppKit
import CoreAudio
import EventKit
import Foundation
import MeetingNotesCore

/// Whether any process is capturing from the default input device right now.
/// Every live call holds the microphone open, muted or not, so this is the
/// difference between a call app running and a call actually happening.
enum MicrophoneActivity {
    static func defaultInputInUse() -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var deviceID = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID) == noErr,
            deviceID != AudioObjectID(kAudioObjectUnknown)
        else { return false }

        var runningAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var running: UInt32 = 0
        var runningSize = UInt32(MemoryLayout<UInt32>.size)
        guard AudioObjectGetPropertyData(
            deviceID, &runningAddress, 0, nil, &runningSize, &running) == noErr
        else { return false }
        return running != 0
    }
}

@MainActor
final class CalendarWatcher: ObservableObject {
    struct Offer: Equatable {
        let key: String
        let title: String
        let reason: String
        let attendees: [OfferAttendee]
    }

    struct OfferAttendee: Equatable {
        let name: String
        let email: String?
    }

    @Published private(set) var offer: Offer?

    /// Injected so no offer appears mid-recording.
    var isRecording: () -> Bool = { false }

    private let store = EKEventStore()
    private var accessGranted = false
    private var dismissedKeys: Set<String> = []
    private var pollTask: Task<Void, Never>?

    func start() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            await self?.requestAccess()
            while let self, !Task.isCancelled {
                self.poll()
                try? await Task.sleep(for: .seconds(30))
            }
        }
    }

    func stop() {
        pollTask?.cancel()
    }

    /// Not now: this event or call app stays quiet.
    func dismiss() {
        if let offer {
            dismissedKeys.insert(offer.key)
        }
        offer = nil
    }

    func accepted() {
        if let offer {
            dismissedKeys.insert(offer.key)
        }
        offer = nil
    }

    private func requestAccess() async {
        accessGranted = (try? await store.requestFullAccessToEvents()) ?? false
    }

    private func poll() {
        guard !isRecording() else {
            offer = nil
            return
        }
        if accessGranted, let event = dueEvent() {
            let key = "calendar:\(event.eventIdentifier ?? event.title ?? "meeting")"
            if !dismissedKeys.contains(key) {
                let title = event.title ?? "Meeting"
                offer = Offer(
                    key: key,
                    title: title,
                    reason: "\(title) is due in your calendar.",
                    attendees: attendees(of: event))
                return
            }
        }
        let names = NSWorkspace.shared.runningApplications.compactMap(\.localizedName)
        if let app = MeetingDetection.runningCallApp(
            processNames: names,
            microphoneInUse: MicrophoneActivity.defaultInputInUse()) {
            let key = "app:\(app)"
            if !dismissedKeys.contains(key) {
                offer = Offer(
                    key: key,
                    title: "Meeting",
                    reason: "\(app) looks like it is in a call.",
                    attendees: [])
                return
            }
        } else {
            // The call app quit; a future call can prompt again.
            dismissedKeys = dismissedKeys.filter { !$0.hasPrefix("app:") }
        }
        offer = nil
    }

    private func dueEvent() -> EKEvent? {
        let now = Date()
        let predicate = store.predicateForEvents(
            withStart: now.addingTimeInterval(-600),
            end: now.addingTimeInterval(300),
            calendars: nil)
        return store.events(matching: predicate)
            .filter { !$0.isAllDay }
            .sorted { $0.startDate < $1.startDate }
            .first { MeetingDetection.isDue(start: $0.startDate, now: now) }
    }

    private func attendees(of event: EKEvent) -> [OfferAttendee] {
        (event.attendees ?? []).compactMap { participant in
            guard participant.participantType == .person else { return nil }
            let url = participant.url.absoluteString
            let email = url.hasPrefix("mailto:") ? String(url.dropFirst("mailto:".count)) : nil
            guard let name = participant.name ?? email else { return nil }
            return OfferAttendee(name: name, email: email)
        }
    }
}
