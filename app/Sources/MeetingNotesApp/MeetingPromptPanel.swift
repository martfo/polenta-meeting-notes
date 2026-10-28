// The floating "record this meeting?" pop-up.
//
// A detected meeting used to be offered only in a strip inside the main
// window, which is behind the call during a call, so the offer was never seen
// and every recording was started by hand. This panel floats over whatever is
// in front, including a full-screen Teams or Zoom, in the top-right corner,
// without taking focus: the call keeps the keyboard and the pop-up is one
// click. It stays until answered, until the meeting is no longer due, or
// until the call ends. Recording still only ever starts on that click.

import AppKit
import Combine
import MeetingNotesCore
import SwiftUI

@MainActor
final class MeetingPromptController {
    private weak var model: AppModel?
    private var panel: MeetingPromptPanel?
    private var shownKey: String?
    private var cancellables: Set<AnyCancellable> = []

    init(model: AppModel) {
        self.model = model
    }

    func start() {
        guard let model, cancellables.isEmpty else { return }
        // The calendar republishes an unchanged offer on every look, so only
        // real changes reach the panel; otherwise it would jump back to the
        // corner every few seconds after being dragged aside.
        model.calendar.$offer
            .combineLatest(model.capture.$isCapturing)
            .removeDuplicates { $0.0 == $1.0 && $0.1 == $1.1 }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] offer, capturing in
                self?.update(offer: offer, capturing: capturing)
            }
            .store(in: &cancellables)
    }

    /// Re-read the on/off setting and the current offer.
    func refresh() {
        guard let model else { return }
        update(offer: model.calendar.offer, capturing: model.capture.isCapturing)
    }

    /// Show what the pop-up looks like and where it appears, from Settings.
    /// Both buttons simply close it.
    func showSample() {
        let content = MeetingPromptContent(
            heading: "Record this meeting?",
            title: "Weekly sync",
            reason: "This is a sample. The real one appears when a meeting is due "
                + "or a call starts.",
            attendees: nil)
        present(content, key: "sample", onAccept: { [weak self] in self?.hide() },
                onDismiss: { [weak self] in self?.hide() })
    }

    private func update(offer: CalendarWatcher.Offer?, capturing: Bool) {
        guard let offer, !capturing, MeetingPromptPreference.isEnabled() else {
            // A sample stays until closed; everything else follows the offer.
            if shownKey != "sample" { hide() }
            return
        }
        let content = MeetingPromptContent(
            heading: "Record this meeting?",
            title: offer.title,
            reason: offer.reason,
            attendees: offer.attendees.isEmpty
                ? nil : offer.attendees.map(\.name).joined(separator: ", "))
        present(content, key: offer.key,
                onAccept: { [weak self] in self?.model?.acceptOffer(offer) },
                onDismiss: { [weak self] in self?.model?.calendar.dismiss() })
    }

    private func present(
        _ content: MeetingPromptContent, key: String,
        onAccept: @escaping () -> Void, onDismiss: @escaping () -> Void
    ) {
        let panel = self.panel ?? MeetingPromptPanel()
        self.panel = panel
        let view = MeetingPromptView(content: content, onAccept: onAccept, onDismiss: onDismiss)
        panel.setContent(view)

        let isNew = shownKey != key || !panel.isVisible
        shownKey = key
        if isNew {
            panel.placeTopRight(on: Self.screenUnderPointer())
            panel.alphaValue = 0
            panel.orderFrontRegardless()
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.2
                panel.animator().alphaValue = 1
            }
        }
    }

    private func hide() {
        shownKey = nil
        guard let panel, panel.isVisible else { return }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.15
            panel.animator().alphaValue = 0
        }, completionHandler: {
            MainActor.assumeIsolated {
                // Only if nothing new was shown during the fade.
                if self.shownKey == nil { panel.orderOut(nil) }
            }
        })
    }

    /// The screen the user is looking at: the one under the pointer.
    private static func screenUnderPointer() -> NSScreen? {
        let pointer = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(pointer, $0.frame, false) } ?? NSScreen.main
    }
}

/// A floating panel that never takes focus and shows on every Space,
/// including over full-screen apps.
final class MeetingPromptPanel: NSPanel {
    init() {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 140),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: true)
        isFloatingPanel = true
        level = .statusBar
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        hidesOnDeactivate = false
        becomesKeyOnlyIfNeeded = true
        isMovableByWindowBackground = true
        isReleasedWhenClosed = false
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true
    }

    func setContent(_ view: MeetingPromptView) {
        if let hosting = contentView as? FirstClickHostingView<MeetingPromptView> {
            hosting.rootView = view
        } else {
            contentView = FirstClickHostingView(rootView: view)
        }
        if let size = contentView?.fittingSize {
            setContentSize(size)
        }
    }

    func placeTopRight(on screen: NSScreen?) {
        guard let screen else { return }
        setFrameOrigin(PromptPlacement.topRightOrigin(
            size: frame.size, visibleFrame: screen.visibleFrame))
    }
}

/// A hosting view whose buttons respond to the first click, even though the
/// panel is never the key window. Without this the first click would only
/// focus the panel and "Start recording" would need pressing twice.
final class FirstClickHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

struct MeetingPromptContent: Equatable {
    let heading: String
    let title: String
    let reason: String
    let attendees: String?
}

struct MeetingPromptView: View {
    let content: MeetingPromptContent
    let onAccept: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .interpolation(.high)
                .frame(width: 38, height: 38)
            VStack(alignment: .leading, spacing: 4) {
                Text(content.heading)
                    .font(.system(size: 13, weight: .semibold))
                Text(content.title)
                    .font(.system(size: 13))
                    .lineLimit(2)
                Text(content.reason)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let attendees = content.attendees {
                    Text(attendees)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                HStack(spacing: 8) {
                    Button("Start recording", action: onAccept)
                        .buttonStyle(PillButtonStyle(background: .red, foreground: .white))
                    Button("Not now", action: onDismiss)
                        .buttonStyle(PillButtonStyle(
                            background: Color.secondary.opacity(0.18), foreground: .primary))
                }
                .padding(.top, 6)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(width: 360, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08)))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Record this meeting? \(content.title)")
    }
}
