import Foundation
import Testing
@testable import MeetingNotesCore

struct DateGroupingTests {
    private var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }

    private func date(_ iso: String) -> Date {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.date(from: iso)!
    }

    @Test("meetings bucket into today, yesterday, this week, this month, older")
    func test_buckets() {
        let now = date("2026-07-08T12:00:00Z")  // a Wednesday
        func bucket(_ iso: String) -> String {
            DateGrouping.bucket(for: iso, now: now, calendar: calendar)
        }
        #expect(bucket("2026-07-08T09:00:00Z") == "Today")
        #expect(bucket("2026-07-07T18:00:00Z") == "Yesterday")
        #expect(bucket("2026-07-06T10:00:00Z") == "Earlier this week")  // Monday, same week
        #expect(bucket("2026-07-02T10:00:00Z") == "This month")          // earlier in July
        #expect(bucket("2026-05-01T10:00:00Z") == "Older")
        #expect(bucket("not a date") == "Undated")
    }

    @Test("bucket order puts today first and undated last")
    func test_order() {
        #expect(DateGrouping.sortIndex(of: "Today") < DateGrouping.sortIndex(of: "Yesterday"))
        #expect(DateGrouping.sortIndex(of: "Older") < DateGrouping.sortIndex(of: "Undated"))
    }

    @Test("a bare yyyy-MM-dd string still parses")
    func test_bare_date() {
        let now = date("2026-07-08T12:00:00Z")
        #expect(DateGrouping.bucket(for: "2026-07-08", now: now, calendar: calendar) == "Today")
    }
}
