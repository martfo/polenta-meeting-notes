// The notes editor. Notes are stored as markdown, with each pasted image as a
// relative link to the meeting's assets folder; here those links show as the
// images themselves, inline where they were pasted, scaled to the width of
// the pane. Everything typed stays plain text, and what is saved is the same
// markdown as before, so the summary, search and OCR read it unchanged.
// Dragging an image's corner handle resizes it; the width is kept in the
// link the way Obsidian writes it, ![pasted image|320](assets/x.png).

import AppKit
import MeetingNotesCore
import SwiftUI
import UniformTypeIdentifiers

/// Lets the screen act on the editor: insert a just-stored image at the
/// cursor, or put the cursor in the notes.
@MainActor
final class NotesEditorController {
    fileprivate weak var textView: NotesTextView?
    fileprivate var baseURL: URL?
    fileprivate var wantsFocus = false

    /// Inserts the image at `path` (relative to the meeting folder) at the
    /// cursor, on a line of its own. Returns false when the editor is not
    /// showing or the file cannot be read, so the caller can fall back.
    @discardableResult
    func insertImage(path: String, alt: String = NoteImages.defaultAlt) -> Bool {
        guard let textView, let baseURL,
              let attachment = NoteImageAttachment.load(alt: alt, path: path, base: baseURL)
        else { return false }
        let range = textView.selectedRange()
        let text = textView.string
        let before = NoteImages.padding(forInsertAt: range.location, in: text).before
        let after = NoteImages.padding(forInsertAt: range.location + range.length, in: text).after
        let attributes = textView.typingAttributes.filter { $0.key != .attachment }
        let insert = NSMutableAttributedString(string: before, attributes: attributes)
        let image = NSMutableAttributedString(attachment: attachment)
        image.addAttributes(attributes, range: NSRange(location: 0, length: image.length))
        insert.append(image)
        insert.append(NSAttributedString(string: after, attributes: attributes))
        textView.window?.makeFirstResponder(textView)
        textView.insertText(insert, replacementRange: range)
        textView.scrollRangeToVisible(textView.selectedRange())
        return true
    }

    func focus() {
        wantsFocus = true
        textView.map(applyFocus)
    }

    fileprivate func applyFocus(_ textView: NotesTextView) {
        guard wantsFocus else { return }
        DispatchQueue.main.async { [weak self, weak textView] in
            guard let textView, let window = textView.window else { return }
            window.makeFirstResponder(textView)
            self?.wantsFocus = false
        }
    }
}

struct NotesTextEditor: NSViewRepresentable {
    @Binding var text: String
    /// The meeting folder, which image links are relative to.
    let baseURL: URL
    let font: NSFont
    let controller: NotesEditorController
    /// The editor lost focus after an edit.
    var onEndEditing: () -> Void = {}
    /// A paste whose content is an image rather than text.
    var onPasteImage: () -> Void = {}
    /// An image was resized (or put back to its own size), so the notes
    /// can be saved.
    var onImageResized: () -> Void = {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let textView = NotesTextView(usingTextLayoutManager: true)
        textView.delegate = context.coordinator
        textView.isRichText = true  // needed to hold the image attachments
        textView.importsGraphics = false
        textView.allowsUndo = true
        textView.isEditable = true
        textView.isSelectable = true
        textView.drawsBackground = true
        textView.backgroundColor = .textBackgroundColor
        textView.textContainerInset = NSSize(width: 2, height: 6)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.minSize = .zero
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude,
                                  height: CGFloat.greatestFiniteMagnitude)
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(
            width: 0, height: CGFloat.greatestFiniteMagnitude)

        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.borderType = .noBorder
        scrollView.documentView = textView

        context.coordinator.textView = textView
        textView.textStorage?.delegate = context.coordinator
        context.coordinator.load(text, into: textView)
        controller.textView = textView
        controller.baseURL = baseURL
        controller.applyFocus(textView)
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        let coordinator = context.coordinator
        coordinator.parent = self
        controller.baseURL = baseURL
        guard let textView = coordinator.textView else { return }
        controller.textView = textView
        // Rebuild only for a change made outside the editor (a reload, find
        // and replace) or a new font; typing already matches.
        if text != coordinator.lastMarkdown || font != coordinator.font
            || baseURL != coordinator.baseURL {
            coordinator.load(text, into: textView)
        }
        controller.applyFocus(textView)
    }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate, NSTextStorageDelegate {
        var parent: NotesTextEditor
        weak var textView: NotesTextView?
        private(set) var lastMarkdown = ""
        private(set) var font: NSFont?
        private(set) var baseURL: URL?
        private var loading = false

        init(_ parent: NotesTextEditor) { self.parent = parent }

        var attributes: [NSAttributedString.Key: Any] {
            [.font: parent.font, .foregroundColor: NSColor.textColor]
        }

        /// Markdown in, text with images out. A link whose file is missing
        /// stays as its text, so nothing is lost.
        func attributed(_ markdown: String) -> NSAttributedString {
            let result = NSMutableAttributedString()
            for segment in NoteImages.segments(in: markdown) {
                switch segment {
                case .text(let text):
                    result.append(NSAttributedString(string: text, attributes: attributes))
                case .image(let alt, let path):
                    if let attachment = NoteImageAttachment.load(
                        alt: alt, path: path, base: parent.baseURL) {
                        let image = NSMutableAttributedString(attachment: attachment)
                        image.addAttributes(attributes, range: NSRange(location: 0, length: image.length))
                        result.append(image)
                    } else {
                        result.append(NSAttributedString(
                            string: NoteImages.markdown(alt: alt, path: path),
                            attributes: attributes))
                    }
                }
            }
            return result
        }

        func load(_ markdown: String, into textView: NotesTextView) {
            loading = true
            defer { loading = false }
            let selection = textView.selectedRange()
            textView.textStorage?.setAttributedString(attributed(markdown))
            textView.typingAttributes = attributes
            let length = (textView.string as NSString).length
            textView.setSelectedRange(NSRange(location: min(selection.location, length), length: 0))
            lastMarkdown = markdown
            font = parent.font
            baseURL = parent.baseURL
            textView.onPasteImage = { [weak self] in self?.parent.onPasteImage() }
            textView.onImageResized = { [weak self] in self?.parent.onImageResized() }
            textView.makeAttributed = { [weak self] in
                self?.attributed($0) ?? NSAttributedString(string: $0)
            }
        }

        /// Every change to the text, typing and undo alike (undo does not
        /// send textDidChange), goes back to the binding as markdown.
        nonisolated func textStorage(
            _ textStorage: NSTextStorage, didProcessEditing editedMask: NSTextStorageEditActions,
            range editedRange: NSRange, changeInLength delta: Int
        ) {
            MainActor.assumeIsolated { textView?.refreshImageViews() }
            // Attribute edits carry an image's new width.
            guard editedMask.contains(.editedCharacters)
                || editedMask.contains(.editedAttributes) else { return }
            MainActor.assumeIsolated { sync(from: textStorage) }
        }

        private func sync(from textStorage: NSTextStorage) {
            // Mid-drag the width changes on every mouse move; the notes take
            // the final width once, when the drag ends.
            guard !loading, textView?.isResizingImage != true else { return }
            let markdown = NotesTextView.markdown(from: textStorage)
            lastMarkdown = markdown
            if parent.text != markdown { parent.text = markdown }
        }

        func textDidEndEditing(_ notification: Notification) {
            parent.onEndEditing()
        }
    }
}

/// The text view under the editor. Copy, cut, drag and paste carry markdown,
/// so an image moved or copied within the notes keeps its link, and pasted
/// rich text arrives as plain text in the notes' own font.
final class NotesTextView: NSTextView {
    var onPasteImage: (() -> Void)?
    var onImageResized: (() -> Void)?
    var makeAttributed: ((String) -> NSAttributedString)?
    private(set) var isResizingImage = false
    private var imageRefreshQueued = false

    /// TextKit 2 makes the view for a newly inserted image only at its next
    /// viewport layout, which an insert alone does not bring about: a pasted
    /// image showed as an empty gap until something else changed. After each
    /// edit, once the edit has finished, lay the visible part out again.
    func refreshImageViews() {
        guard !imageRefreshQueued else { return }
        imageRefreshQueued = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.imageRefreshQueued = false
            self.textLayoutManager?.textViewportLayoutController.layoutViewport()
        }
    }

    // MARK: Resizing images

    /// The widest an image can be shown: the text column.
    var imageWidthLimit: CGFloat {
        let container = textContainer
        return max(NoteImageAttachment.minWidth,
                   (container?.size.width ?? bounds.width) - 2 * (container?.lineFragmentPadding ?? 0))
    }

    private func range(of attachment: NoteImageAttachment) -> NSRange? {
        guard let storage = textStorage else { return nil }
        var found: NSRange?
        storage.enumerateAttribute(
            .attachment, in: NSRange(location: 0, length: storage.length)
        ) { value, range, stop in
            if (value as? NoteImageAttachment) === attachment {
                found = range
                stop.pointee = true
            }
        }
        return found
    }

    /// Lays the image out again at its current width. As an attribute edit,
    /// it also brings the notes' markdown up to date (unless mid-drag).
    private func relayout(_ attachment: NoteImageAttachment) {
        guard let storage = textStorage, let range = range(of: attachment) else { return }
        storage.beginEditing()
        storage.edited(.editedAttributes, range: range, changeInLength: 0)
        storage.endEditing()
    }

    func beginImageResize() { isResizingImage = true }

    /// Live, while dragging: nothing is saved or undoable yet.
    func previewImageWidth(_ attachment: NoteImageAttachment, _ width: CGFloat) {
        attachment.width = Int(min(max(width, NoteImageAttachment.minWidth), imageWidthLimit).rounded())
        relayout(attachment)
    }

    /// The drag ended: the width is kept, can be undone, and is saved.
    func endImageResize(_ attachment: NoteImageAttachment, from previous: Int?) {
        isResizingImage = false
        let final = attachment.width
        attachment.width = previous
        setImageWidth(attachment, final)
    }

    /// Sets a width (nil: the image's own size, fitted to the column) as one
    /// undoable step.
    func setImageWidth(_ attachment: NoteImageAttachment, _ width: Int?) {
        let previous = attachment.width
        guard previous != width else { relayout(attachment); return }
        undoManager?.registerUndo(withTarget: self) { textView in
            textView.setImageWidth(attachment, previous)
        }
        undoManager?.setActionName("Resize Image")
        attachment.width = width
        relayout(attachment)
        onImageResized?()
    }

    static func markdown(from text: NSAttributedString) -> String {
        var markdown = ""
        let whole = NSRange(location: 0, length: text.length)
        text.enumerateAttribute(.attachment, in: whole) { value, range, _ in
            if let image = value as? NoteImageAttachment {
                // One attachment character per image; a run can hold several.
                for _ in 0..<range.length {
                    markdown += NoteImages.markdown(
                        alt: NoteImages.alt(label: image.label, width: image.width),
                        path: image.path)
                }
            } else if value == nil {
                markdown += text.attributedSubstring(from: range).string
            }
            // Any other attachment cannot be stored in notes.md, so it is dropped.
        }
        return markdown
    }

    override func paste(_ sender: Any?) {
        if Self.pasteboardIsImage(.general) {
            onPasteImage?()
        } else {
            super.paste(sender)
        }
    }

    override func pasteAsRichText(_ sender: Any?) { paste(sender) }

    /// An image with no text alongside it: a screenshot, or a copied image.
    /// Copying from an office app puts both a picture and the text on the
    /// pasteboard, and there the text is what is wanted.
    static func pasteboardIsImage(_ pasteboard: NSPasteboard) -> Bool {
        pasteboard.string(forType: .string) == nil
            && pasteboard.canReadItem(withDataConformingToTypes: [
                UTType.png.identifier, UTType.tiff.identifier,
            ])
    }

    override var writablePasteboardTypes: [NSPasteboard.PasteboardType] { [.string] }

    override func writeSelection(to pboard: NSPasteboard, type: NSPasteboard.PasteboardType) -> Bool {
        guard type == .string, let storage = textStorage else { return false }
        let markdown = selectedRanges.map(\.rangeValue)
            .filter { $0.length > 0 && NSMaxRange($0) <= storage.length }
            .map { Self.markdown(from: storage.attributedSubstring(from: $0)) }
            .joined(separator: "\n")
        return pboard.setString(markdown, forType: .string)
    }

    override var readablePasteboardTypes: [NSPasteboard.PasteboardType] { [.string] }

    override func readSelection(from pboard: NSPasteboard, type: NSPasteboard.PasteboardType) -> Bool {
        guard type == .string, let string = pboard.string(forType: .string) else { return false }
        let insert = makeAttributed?(string) ?? NSAttributedString(string: string)
        insertText(insert, replacementRange: rangeForUserTextChange)
        return true
    }
}

/// A pasted image shown in the notes, remembering the link it came from and
/// the width it was sized to, if any.
final class NoteImageAttachment: NSTextAttachment {
    let label: String
    let path: String
    /// Points wide, as dragged; nil shows the image at its own size.
    var width: Int?

    /// Unsized tall screenshots are shown shorter, so one image never fills
    /// the pane. A width the user dragged to is kept as chosen.
    static let maxHeight: CGFloat = 480
    static let minWidth: CGFloat = 40

    init(alt: String, path: String, image: NSImage) {
        let parts = NoteImages.splitAlt(alt)
        self.label = parts.label
        self.width = parts.width
        self.path = path
        super.init(data: nil, ofType: nil)
        self.image = image
    }

    required init?(coder: NSCoder) { nil }

    static func load(alt: String, path: String, base: URL) -> NoteImageAttachment? {
        let url = base.appendingPathComponent(path)
        guard FileManager.default.fileExists(atPath: url.path),
              let image = NSImage(contentsOf: url) else { return nil }
        return NoteImageAttachment(alt: alt, path: path, image: image)
    }

    /// The size to show the image at: the dragged width if there is one,
    /// otherwise its own size made smaller to fit the height limit; always
    /// within the line's width, and keeping its proportions.
    func fitted(lineWidth: CGFloat, padding: CGFloat) -> CGRect {
        guard let size = image?.size, size.width > 0, size.height > 0 else { return .zero }
        let available = max(Self.minWidth, lineWidth - 2 * padding)
        let shown: CGFloat
        if let width {
            shown = min(max(CGFloat(width), Self.minWidth), available)
        } else {
            shown = size.width * min(1, available / size.width, Self.maxHeight / size.height)
        }
        return CGRect(x: 0, y: 0, width: shown, height: (shown * size.height / size.width).rounded())
    }

    override func attachmentBounds(
        for attributes: [NSAttributedString.Key: Any], location: NSTextLocation,
        textContainer: NSTextContainer?, proposedLineFragment: CGRect, position: CGPoint
    ) -> CGRect {
        fitted(lineWidth: textContainer?.size.width ?? proposedLineFragment.width,
               padding: textContainer?.lineFragmentPadding ?? 0)
    }

    override func attachmentBounds(
        for textContainer: NSTextContainer?, proposedLineFragment lineFrag: NSRect,
        glyphPosition position: CGPoint, characterIndex charIndex: Int
    ) -> NSRect {
        fitted(lineWidth: textContainer?.size.width ?? lineFrag.width,
               padding: textContainer?.lineFragmentPadding ?? 0)
    }

    override func viewProvider(
        for parentView: NSView?, location: NSTextLocation, textContainer: NSTextContainer?
    ) -> NSTextAttachmentViewProvider? {
        NoteImageViewProvider(textAttachment: self, parentView: parentView,
                              textLayoutManager: textContainer?.textLayoutManager,
                              location: location)
    }
}

/// Puts a live view in the text for each image, so it can be resized.
final class NoteImageViewProvider: NSTextAttachmentViewProvider {
    override func loadView() {
        guard let attachment = textAttachment as? NoteImageAttachment else { return }
        view = NoteImageView(attachment: attachment)
    }

    override func attachmentBounds(
        for attributes: [NSAttributedString.Key: Any], location: NSTextLocation,
        textContainer: NSTextContainer?, proposedLineFragment: CGRect, position: CGPoint
    ) -> CGRect {
        (textAttachment as? NoteImageAttachment)?.fitted(
            lineWidth: textContainer?.size.width ?? proposedLineFragment.width,
            padding: textContainer?.lineFragmentPadding ?? 0) ?? .zero
    }
}

/// One image in the notes. Hovering shows an outline and a handle at the
/// bottom-right corner: drag it to resize, double-click it to go back to the
/// image's own size. Clicks elsewhere on the image go to the text, so it
/// selects and deletes like a character.
final class NoteImageView: NSView {
    private let attachment: NoteImageAttachment
    private var hovering = false { didSet { needsDisplay = true } }
    private static let handleSize: CGFloat = 12

    init(attachment: NoteImageAttachment) {
        self.attachment = attachment
        super.init(frame: .zero)
        toolTip = "Drag the corner to resize. Double-click it for the original size."
    }

    required init?(coder: NSCoder) { nil }

    private var textView: NotesTextView? {
        sequence(first: superview, next: { $0?.superview })
            .lazy.compactMap { $0 as? NotesTextView }.first
    }

    /// The corner handle, a little larger than drawn so it is easy to catch.
    private var handleHitRect: NSRect {
        let size = Self.handleSize + 8
        return NSRect(x: bounds.maxX - size, y: isFlipped ? bounds.maxY - size : bounds.minY,
                      width: size, height: size)
    }

    private var handleRect: NSRect {
        let size = Self.handleSize
        return NSRect(x: bounds.maxX - size - 2,
                      y: isFlipped ? bounds.maxY - size - 2 : bounds.minY + 2,
                      width: size, height: size)
    }

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        attachment.image?.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1,
                               respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
        guard hovering else { return }
        NSColor.controlAccentColor.setStroke()
        let outline = NSBezierPath(rect: bounds.insetBy(dx: 0.5, dy: 0.5))
        outline.lineWidth = 1
        outline.stroke()
        let handle = NSBezierPath(roundedRect: handleRect, xRadius: 3, yRadius: 3)
        NSColor.controlAccentColor.setFill()
        handle.fill()
        NSColor.white.setStroke()
        handle.lineWidth = 1.5
        handle.stroke()
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(
            rect: .zero, options: [.mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect],
            owner: self))
    }

    override func mouseEntered(with event: NSEvent) { hovering = true }
    override func mouseExited(with event: NSEvent) { hovering = false }

    override func resetCursorRects() {
        addCursorRect(handleHitRect, cursor: .resizeLeftRight)
    }

    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        guard handleHitRect.contains(point), let textView, let window else {
            super.mouseDown(with: event)
            return
        }
        if event.clickCount == 2 {
            textView.setImageWidth(attachment, nil)
            return
        }
        let previous = attachment.width
        let startX = event.locationInWindow.x
        let startWidth = bounds.width
        textView.beginImageResize()
        // Track the drag here: the view may be rebuilt as the text lays out
        // again, and the loop keeps going regardless.
        while let next = window.nextEvent(matching: [.leftMouseDragged, .leftMouseUp]) {
            textView.previewImageWidth(attachment, startWidth + next.locationInWindow.x - startX)
            if next.type == .leftMouseUp { break }
        }
        textView.endImageResize(attachment, from: previous)
    }
}
