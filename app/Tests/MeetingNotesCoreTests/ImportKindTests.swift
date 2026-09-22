import Foundation
import Testing

@testable import MeetingNotesCore

/// Sorting a drop into what each file will be imported as.
struct ImportKindTests {
    @Test func markdownAndTextAreTranscripts() {
        #expect(ImportKind.of(fileExtension: "md") == .transcript)
        #expect(ImportKind.of(fileExtension: "MD") == .transcript)
        #expect(ImportKind.of(fileExtension: "markdown") == .transcript)
        #expect(ImportKind.of(fileExtension: "txt") == .transcript)
    }

    @Test func audioIsStillAudio() {
        #expect(ImportKind.of(fileExtension: "wav") == .audio)
        #expect(ImportKind.of(fileExtension: "m4a") == .audio)
        #expect(ImportKind.of(fileExtension: "mp3") == .audio)
    }

    @Test func anythingElseIsDeclined() {
        #expect(ImportKind.of(fileExtension: "pdf") == nil)
        #expect(ImportKind.of(fileExtension: "png") == nil)
        #expect(ImportKind.of(fileExtension: "") == nil)
    }

    @Test func aMixedDropIsSplitInOrder() {
        let selection = ImportSelection.from(urls: [
            URL(fileURLWithPath: "/tmp/one.m4a"),
            URL(fileURLWithPath: "/tmp/notes.pdf"),
            URL(fileURLWithPath: "/tmp/call.md"),
            URL(fileURLWithPath: "/tmp/two.wav"),
        ])
        #expect(selection.audio.map(\.lastPathComponent) == ["one.m4a", "two.wav"])
        #expect(selection.transcripts.map(\.lastPathComponent) == ["call.md"])
        #expect(selection.count == 3)
    }

    @Test func severalOfOneKindReadNaturally() {
        let many = ImportSelection(audio: [
            URL(fileURLWithPath: "/tmp/one.m4a"), URL(fileURLWithPath: "/tmp/two.m4a"),
        ])
        #expect(many.prompt() == "Import 2 recordings as meetings?")
    }

    @Test func aDropOfOnlyUnsupportedFilesIsEmpty() {
        let selection = ImportSelection.from(urls: [URL(fileURLWithPath: "/tmp/a.pdf")])
        #expect(selection.isEmpty)
    }

    @Test func theConfirmationSaysWhatIsBeingImported() {
        let one = ImportSelection(transcripts: [URL(fileURLWithPath: "/tmp/call.md")])
        #expect(one.prompt() == "Import the transcript call.md as a meeting?")

        let audio = ImportSelection(audio: [URL(fileURLWithPath: "/tmp/one.m4a")])
        #expect(audio.prompt() == "Import one.m4a as a meeting?")

        let mixed = ImportSelection(
            audio: [URL(fileURLWithPath: "/tmp/one.m4a")],
            transcripts: [URL(fileURLWithPath: "/tmp/call.md")])
        #expect(mixed.prompt() == "Import 1 recording and 1 transcript as meetings?")
    }
}
