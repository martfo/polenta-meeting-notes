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
        var end: Date?
    }

    struct OfferAttendee: Equatable {
        let name: String
        let email: String?
    }

    /// A calendar event in progress right now, for titling and auto-stop.
    struct CurrentEvent {
        let title: String
        let end: Date
        let attendees: [OfferAttendee]
    }

    @Published private(set) var offer: Offer?

    /// Injected so no offer appears mid-recording.
    var isRecording: () -> Bool = { false }

    private let store = EKEventStore()
    private var accessGranted = false
    private var dismissedKeys: Set<String> = []
    private var pollTask: Task<Void, Never>?
    private var previousMicrophoneInUse: Bool?
    private var previousCallApps: Set<String> = []

    func start() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            await self?.requestAccess()
            while let self, !Task.isCancelled {
                self.poll()
                try? await Task.sleep(for: .seconds(15))
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
                    attendees: attendees(of: event),
                    end: event.endDate)
                return
            }
        }
        let names = NSWorkspace.shared.runningApplications.compactMap(\.localizedName)
        let microphoneInUse = MicrophoneActivity.defaultInputInUse()
        let callApps = Set(names.filter { MeetingDetection.callAppNames.contains($0) })
        defer {
            previousMicrophoneInUse = microphoneInUse
            previousCallApps = callApps
        }
        if let app = MeetingDetection.callPromptTrigger(
            processNames: names,
            microphoneInUse: microphoneInUse,
            previousMicrophoneInUse: previousMicrophoneInUse,
            previousCallApps: previousCallApps) {
            let key = "app:\(app)"
            if !dismissedKeys.contains(key) {
                offer = Offer(
                    key: key,
                    title: "Meeting",
                    reason: "\(app) looks like it is in a call.",
                    attendees: [])
                return
            }
        }
        if !microphoneInUse {
            // The call ended; the next one can prompt again.
            dismissedKeys = dismissedKeys.filter { !$0.hasPrefix("app:") }
            if offer?.key.hasPrefix("app:") == true {
                offer = nil  // the banner does not outlive the call
            }
        }
        if offer?.key.hasPrefix("calendar:") == true {
            offer = nil
        }
    }

    private func dueEvent() -> EKEvent? {
        let now = Date()
        let predicate = store.predicateForEvents(
            withStart: now.addingTimeInterval(-1500),
            end: now.addingTimeInterval(300),
            calendars: nil)
        return store.events(matching: predicate)
            .filter { !$0.isAllDay }
            .sorted { $0.startDate < $1.startDate }
            .first { MeetingDetection.isDue(start: $0.startDate, now: now) }
    }

    /// The event in progress right now, if any: the one whose start is closest
    /// to now among those currently happening. Used to title a hand-started
    /// recording and to schedule its auto-stop.
    func currentEvent() -> CurrentEvent? {
        guard accessGranted else { return nil }
        let now = Date()
        let predicate = store.predicateForEvents(
            withStart: now.addingTimeInterval(-4 * 3600),
            end: now.addingTimeInterval(600),
            calendars: nil)
        let event = store.events(matching: predicate)
            .filter { !$0.isAllDay }
            .filter { MeetingDetection.isHappeningNow(start: $0.startDate, end: $0.endDate, now: now) }
            .min { abs($0.startDate.timeIntervalSince(now)) < abs($1.startDate.timeIntervalSince(now)) }
        guard let event else { return nil }
        return CurrentEvent(
            title: event.title ?? "Meeting", end: event.endDate,
            attendees: attendees(of: event))
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
