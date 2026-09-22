import Foundation
import UniformTypeIdentifiers

/// What a dropped or chosen file should be imported as.
///
/// Audio goes through the recording pipeline (transcribe, diarise, enrol,
/// summarise). A written transcript is already past all of that, so it skips
/// straight to indexing and the summary. Anything else is declined, so a
/// stray PDF dragged onto the window does nothing rather than creating a
/// meeting full of nonsense.
public enum ImportKind: Equatable, Sendable {
    case audio
    case transcript

    /// Markdown and plain text hold a written transcript. The extensions are
    /// matched directly as well as through the type system, because a file
    /// exported by another tool often has no registered type for its suffix.
    public static let transcriptExtensions: Set<String> = ["md", "markdown", "txt", "text"]

    public static func of(url: URL) -> ImportKind? {
        of(fileExtension: url.pathExtension)
    }

    public static func of(fileExtension: String) -> ImportKind? {
        let suffix = fileExtension.lowercased()
        if transcriptExtensions.contains(suffix) { return .transcript }
        guard let type = UTType(filenameExtension: suffix) else { return nil }
        if type.conforms(to: .audio) { return .audio }
        // A type that is plain text but not something else (not HTML, not
        // source code) is readable as a transcript.
        if type.conforms(to: .plainText) { return .transcript }
        return nil
    }
}

/// A drop split into what each part will be imported as, preserving order.
public struct ImportSelection: Equatable, Sendable {
    public var audio: [URL] = []
    public var transcripts: [URL] = []

    public init(audio: [URL] = [], transcripts: [URL] = []) {
        self.audio = audio
        self.transcripts = transcripts
    }

    public var isEmpty: Bool { audio.isEmpty && transcripts.isEmpty }
    public var count: Int { audio.count + transcripts.count }

    public static func from(urls: [URL]) -> ImportSelection {
        var selection = ImportSelection()
        for url in urls {
            switch ImportKind.of(url: url) {
            case .audio: selection.audio.append(url)
            case .transcript: selection.transcripts.append(url)
            case nil: continue
            }
        }
        return selection
    }

    /// The confirmation wording for this drop: plain about what will happen,
    /// because an import writes a meeting into the vault.
    public func prompt() -> String {
        if count == 1 {
            let name = (audio.first ?? transcripts.first)?.lastPathComponent ?? ""
            return transcripts.isEmpty
                ? "Import \(name) as a meeting?"
                : "Import the transcript \(name) as a meeting?"
        }
        if transcripts.isEmpty { return "Import \(Self.count(audio.count, "recording")) as meetings?" }
        if audio.isEmpty { return "Import \(Self.count(transcripts.count, "transcript")) as meetings?" }
        return "Import \(Self.count(audio.count, "recording")) and "
            + "\(Self.count(transcripts.count, "transcript")) as meetings?"
    }

    private static func count(_ n: Int, _ noun: String) -> String {
        "\(n) \(noun)\(n == 1 ? "" : "s")"
    }
}
