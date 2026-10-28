// Watches the macOS calendar store and which apps are using the microphone,
// and offers to start recording when a meeting is due or a call starts. The
// offer carries the invite's title and attendees so speaker naming can use
// them. Auto-detection is a prompt to start, never an automatic recording.
//
// The calendar is read through EventKit, so any account synced into macOS
// Calendar (Google, Exchange, iCloud) works with one read-only permission
// and no OAuth setup.

import CoreAudio
import EventKit
import Foundation
import MeetingNotesCore

/// Which processes are capturing audio input right now, by bundle identifier.
///
/// Asked per process (Core Audio's process objects, macOS 14), not per device:
/// on a machine where something holds the microphone all day (a virtual
/// desktop client, another recorder), the device is always busy, so "the
/// microphone became busy" never happens and a call starting in an app that
/// was already running went unnoticed. Asking which app started capturing
/// sees the call itself.
enum MicrophoneActivity {
    static func processesCapturingInput() -> [String] {
        let system = AudioObjectID(kAudioObjectSystemObject)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyProcessObjectList,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr,
              size > 0 else { return [] }
        var processes = [AudioObjectID](
            repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &processes) == noErr
        else { return [] }
        return processes.compactMap { process in
            isCapturingInput(process) ? bundleID(of: process) : nil
        }
    }

    private static func isCapturingInput(_ process: AudioObjectID) -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyIsRunningInput,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var running: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        return AudioObjectGetPropertyData(process, &address, 0, nil, &size, &running) == noErr
            && running != 0
    }

    private static func bundleID(of process: AudioObjectID) -> String? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyBundleID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(process, &address, 0, nil, &size, &value) == noErr,
              let value else { return nil }
        let bundleID = value.takeRetainedValue() as String
        return bundleID.isEmpty ? nil : bundleID
    }
}

@MainActor
final class CalendarWatcher: ObservableObject {
    struct Offer: Equatable {
        let key: String
        /// What to call the meeting in the prompt.
        let title: String
        let reason: String
        let attendees: [OfferAttendee]
        var end: Date?
        /// A due calendar event, as opposed to a call app starting. Only a
        /// calendar offer fixes the meeting's title on accept; a call offer
        /// leaves it to the recording, which borrows the event happening now.
        var fromCalendar: Bool = false
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
    private var previousCallApps: Set<String> = []
    /// After "Not now" on a calendar meeting, the call that meeting starts
    /// should not ask again: the answer was already given.
    private var callPromptsQuietUntil: Date?

    func start() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            await self?.requestAccess()
            while let self, !Task.isCancelled {
                self.poll()
                // Often enough that a call is offered within seconds of
                // starting; each look is a few cheap Core Audio reads and one
                // calendar query.
                try? await Task.sleep(for: .seconds(5))
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
            if offer.fromCalendar {
                callPromptsQuietUntil = offer.end
            }
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

    /// The poll runs every five seconds and recomputes the offer each time;
    /// only a different one is published, so the recording bar and the
    /// pop-up are not redrawn for nothing.
    private func setOffer(_ new: Offer?) {
        if offer != new { offer = new }
    }

    private func poll() {
        // Sampled on every look, recording or not, so that stopping a
        // recording mid-call does not read the ongoing call as a new one.
        let capturing = MeetingDetection.callAppsCapturing(
            bundleIDs: MicrophoneActivity.processesCapturingInput())
        let previouslyCapturing = previousCallApps
        previousCallApps = capturing

        guard !isRecording() else {
            setOffer(nil)
            return
        }

        // A call app that stopped capturing has finished its call: its next
        // call can ask again, and an offer for this one goes away.
        dismissedKeys = dismissedKeys.filter { key in
            guard key.hasPrefix("app:") else { return true }
            return capturing.contains(String(key.dropFirst("app:".count)))
        }
        if let offer, offer.key.hasPrefix("app:"),
           !capturing.contains(String(offer.key.dropFirst("app:".count))) {
            setOffer(nil)
        }

        if accessGranted, let event = dueEvent() {
            let key = "calendar:\(event.eventIdentifier ?? event.title ?? "meeting")"
            if !dismissedKeys.contains(key) {
                let title = event.title ?? "Meeting"
                setOffer(Offer(
                    key: key,
                    title: title,
                    reason: "\(title) is due in your calendar.",
                    attendees: attendees(of: event),
                    end: event.endDate,
                    fromCalendar: true))
                return
            }
        }
        if offer?.fromCalendar == true {
            setOffer(nil)  // no longer due, or refused
        }

        if let quietUntil = callPromptsQuietUntil {
            if Date() < quietUntil { return }
            callPromptsQuietUntil = nil
        }
        if let app = MeetingDetection.callPromptTrigger(
            capturing: capturing, previouslyCapturing: previouslyCapturing) {
            let key = "app:\(app)"
            if !dismissedKeys.contains(key) {
                // Named for the calendar meeting happening now, where there
                // is one, so the prompt says which meeting it would record.
                let current = currentEvent()
                setOffer(Offer(
                    key: key,
                    title: current?.title ?? "Meeting",
                    reason: "\(app) is using the microphone.",
                    attendees: current?.attendees ?? []))
            }
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
