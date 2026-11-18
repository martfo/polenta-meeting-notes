// `polenta://note/<meeting_id>` links. Another app (the task manager, whose
// action items come from a meeting's Next Steps) opens one to bring Polenta
// forward on that meeting. The id is the meeting's folder name under
// <vault>/meetings/, so it is checked strictly before it touches the disk.

import Foundation

public enum NoteLink: Equatable {
    /// A well-formed link to the meeting with this id (already percent-decoded).
    case note(String)
    /// `polenta://note/...` with no usable id, or an id of the wrong shape.
    case malformed
    /// Any other scheme or host: not ours to act on.
    case ignored

    public static let scheme = "polenta"
    public static let noteHost = "note"

    /// Meeting ids are `YYYY-MM-DD_HHMM_slug`, the slug lower-case letters,
    /// digits and hyphens. Anything else, including path separators, dots,
    /// spaces and upper case, is refused: the id becomes a folder name.
    private static let idPattern = try! NSRegularExpression(
        pattern: #"^\d{4}-\d{2}-\d{2}_\d{4}_[a-z0-9-]+$"#)

    public static func isValidMeetingID(_ id: String) -> Bool {
        let range = NSRange(id.startIndex..., in: id)
        return idPattern.firstMatch(in: id, range: range) != nil
    }

    public static func parse(_ url: URL) -> NoteLink {
        guard url.scheme?.lowercased() == scheme else { return .ignored }
        guard url.host?.lowercased() == noteHost else { return .ignored }
        // `url.path` is percent-decoded by Foundation, so an encoded slash
        // comes back as a real one and is caught by the component count.
        let components = url.path.split(separator: "/", omittingEmptySubsequences: true)
        guard components.count == 1 else { return .malformed }
        let id = String(components[0])
        return isValidMeetingID(id) ? .note(id) : .malformed
    }

    /// The link that opens this meeting, for copying into another app. Nil
    /// for an id the parser would refuse, so a copied link always works.
    public static func url(forMeetingID id: String) -> URL? {
        guard isValidMeetingID(id) else { return nil }
        return URL(string: "\(scheme)://\(noteHost)/\(id)")
    }

    /// The meeting's folder, or nil when no meeting with this id is in the
    /// vault. A folder only counts as a meeting when it holds meeting.md.
    public static func meetingFolder(id: String, vault: URL) -> URL? {
        guard isValidMeetingID(id) else { return nil }
        let folder = vault.appendingPathComponent("meetings").appendingPathComponent(id)
        let note = folder.appendingPathComponent("meeting.md")
        return FileManager.default.fileExists(atPath: note.path) ? folder : nil
    }

    public static func notice(for link: NoteLink) -> String? {
        switch link {
        case .note, .ignored: return nil
        case .malformed: return "That Polenta link is not a meeting link."
        }
    }

    public static func notice(forUnknownID id: String) -> String {
        "No meeting with the id \(id) is in this vault."
    }
}
