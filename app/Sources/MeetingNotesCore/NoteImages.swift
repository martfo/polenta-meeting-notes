// Notes are stored as plain markdown in notes.md, with each pasted image as a
// relative link: ![pasted image](assets/pasted-1a2b3c.png). The editor shows
// those links as the images themselves; this splits the text into runs of
// text and images, and joins them back, so what is saved is unchanged.

import Foundation

public enum NoteSegment: Equatable {
    case text(String)
    case image(alt: String, path: String)
}

public enum NoteImages {
    /// The same link shape the backend writes and reads (notes/notes.py).
    private static let pattern = try! NSRegularExpression(
        pattern: #"!\[([^\]]*)\]\((assets/[^)]+)\)"#)

    public static let defaultAlt = "pasted image"

    /// The notes split into text and image links, in order. Joining the
    /// segments gives back exactly the original text.
    public static func segments(in notes: String) -> [NoteSegment] {
        var result: [NoteSegment] = []
        var cursor = notes.startIndex
        let range = NSRange(notes.startIndex..., in: notes)
        for match in pattern.matches(in: notes, range: range) {
            guard let whole = Range(match.range, in: notes),
                  let alt = Range(match.range(at: 1), in: notes),
                  let path = Range(match.range(at: 2), in: notes) else { continue }
            if cursor < whole.lowerBound {
                result.append(.text(String(notes[cursor..<whole.lowerBound])))
            }
            result.append(.image(alt: String(notes[alt]), path: String(notes[path])))
            cursor = whole.upperBound
        }
        if cursor < notes.endIndex {
            result.append(.text(String(notes[cursor...])))
        }
        return result
    }

    /// A display width rides in the alt text, as Obsidian writes it:
    /// ![pasted image|320](assets/x.png) is shown 320 points wide. Obsidian's
    /// "|320x200" form is read too; only the width is used.
    private static let widthSuffix = try! NSRegularExpression(pattern: #"\|(\d+)(?:x\d+)?$"#)

    public static func splitAlt(_ alt: String) -> (label: String, width: Int?) {
        let range = NSRange(alt.startIndex..., in: alt)
        guard let match = widthSuffix.firstMatch(in: alt, range: range),
              let whole = Range(match.range, in: alt),
              let digits = Range(match.range(at: 1), in: alt),
              let width = Int(alt[digits]), width > 0 else { return (alt, nil) }
        return (String(alt[..<whole.lowerBound]), width)
    }

    public static func alt(label: String, width: Int?) -> String {
        guard let width else { return label }
        return "\(label)|\(width)"
    }

    public static func markdown(alt: String, path: String) -> String {
        "![\(alt)](\(path))"
    }

    public static func join(_ segments: [NoteSegment]) -> String {
        segments.map { segment in
            switch segment {
            case .text(let text): return text
            case .image(let alt, let path): return markdown(alt: alt, path: path)
            }
        }.joined()
    }

    /// What to put either side of an image inserted at `offset` (a UTF-16
    /// offset into `text`, as a text view reports it) so the image sits on a
    /// line of its own.
    public static func padding(forInsertAt offset: Int, in text: String)
        -> (before: String, after: String) {
        let utf16 = Array(text.utf16)
        let offset = max(0, min(offset, utf16.count))
        let newline = UInt16(UInt8(ascii: "\n"))
        let before = offset > 0 && utf16[offset - 1] != newline ? "\n" : ""
        let after = offset < utf16.count && utf16[offset] == newline ? "" : "\n"
        return (before, after)
    }
}
