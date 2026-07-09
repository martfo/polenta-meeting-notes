// Relative date buckets for the library's "by date" view, so meetings from
// today or yesterday are easy to find. Pure logic, tested independently of
// the UI.

import Foundation

public enum DateGrouping {
    /// Bucket names in the order they should appear.
    public static let order = ["Today", "Yesterday", "Earlier this week",
                               "This month", "Older", "Undated"]

    /// The bucket for an ISO date-time string (or a plain yyyy-MM-dd), decided
    /// against `now` using the given calendar.
    public static func bucket(for startedAt: String, now: Date,
                              calendar: Calendar = .current) -> String {
        guard let date = parse(startedAt) else { return "Undated" }
        if calendar.isDate(date, inSameDayAs: now) { return "Today" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
           calendar.isDate(date, inSameDayAs: yesterday) { return "Yesterday" }
        if calendar.isDate(date, equalTo: now, toGranularity: .weekOfYear) {
            return "Earlier this week"
        }
        if calendar.isDate(date, equalTo: now, toGranularity: .month) {
            return "This month"
        }
        return "Older"
    }

    /// A sort key so buckets order correctly even if an unexpected one appears.
    public static func sortIndex(of bucket: String) -> Int {
        order.firstIndex(of: bucket) ?? order.count
    }

    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        return formatter
    }()

    static func parse(_ value: String) -> Date? {
        if let date = isoFormatter.date(from: value) { return date }
        // Fall back to a bare date, and to a truncated ISO string.
        return dayFormatter.date(from: String(value.prefix(10)))
    }
}
