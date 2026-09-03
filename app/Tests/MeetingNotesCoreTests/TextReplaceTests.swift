import Testing
@testable import MeetingNotesCore

struct TextReplaceTests {
    @Test("replaces every occurrence and reports the count")
    func test_replaces_all() {
        let out = TextReplace.replacingAll(
            in: "Misha said hi. Later Misha left.", find: "Misha", with: "Nisha",
            caseSensitive: true)
        #expect(out.text == "Nisha said hi. Later Nisha left.")
        #expect(out.count == 2)
    }

    @Test("case-insensitive by request, literal replacement")
    func test_case_insensitive() {
        let out = TextReplace.replacingAll(
            in: "misha and Misha and MISHA", find: "misha", with: "Nisha",
            caseSensitive: false)
        #expect(out.text == "Nisha and Nisha and Nisha")
        #expect(out.count == 3)
    }

    @Test("match case leaves other casings alone")
    func test_case_sensitive_is_exact() {
        let out = TextReplace.replacingAll(
            in: "Misha and misha", find: "Misha", with: "Nisha", caseSensitive: true)
        #expect(out.text == "Nisha and misha")
        #expect(out.count == 1)
    }

    @Test("no match changes nothing")
    func test_no_match() {
        let out = TextReplace.replacingAll(
            in: "nothing here", find: "Misha", with: "Nisha", caseSensitive: false)
        #expect(out.text == "nothing here")
        #expect(out.count == 0)
    }

    @Test("an empty find is a no-op, not an infinite loop")
    func test_empty_find() {
        #expect(TextReplace.count(in: "anything", find: "", caseSensitive: false) == 0)
        let out = TextReplace.replacingAll(in: "anything", find: "", with: "x", caseSensitive: false)
        #expect(out == ("anything", 0))
    }

    @Test("count matches what replace will change")
    func test_count_matches_replace() {
        let text = "CET, cet, and Cet"
        #expect(TextReplace.count(in: text, find: "cet", caseSensitive: false) == 3)
        #expect(TextReplace.count(in: text, find: "CET", caseSensitive: true) == 1)
    }
}
