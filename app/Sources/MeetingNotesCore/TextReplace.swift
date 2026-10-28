// Find and replace for the summary and notes: fix a mis-heard name or term in
// one pass. Pure string logic, so counting and replacing are tested without UI.

import Foundation

public enum TextReplace {
    /// The number of non-overlapping occurrences of `find` in `text`, counted
    /// the same way `replacingAll` replaces them.
    public static func count(in text: String, find: String, caseSensitive: Bool) -> Int {
        guard !find.isEmpty else { return 0 }
        let options: String.CompareOptions = caseSensitive ? [] : [.caseInsensitive]
        var total = 0
        var searchStart = text.startIndex
        while searchStart < text.endIndex,
              let range = text.range(of: find, options: options, range: searchStart..<text.endIndex) {
            total += 1
            // Advance past this match so overlapping runs are not double counted.
            searchStart = range.upperBound > range.lowerBound ? range.upperBound
                : text.index(after: range.lowerBound)
        }
        return total
    }

    /// Replace every occurrence of `find` with `replacement`, returning the new
    /// text and how many replacements were made.
    public static func replacingAll(
        in text: String, find: String, with replacement: String, caseSensitive: Bool
    ) -> (text: String, count: Int) {
        let matches = count(in: text, find: find, caseSensitive: caseSensitive)
        guard matches > 0 else { return (text, 0) }
        let options: String.CompareOptions = caseSensitive ? [] : [.caseInsensitive]
        let replaced = text.replacingOccurrences(of: find, with: replacement, options: options)
        return (replaced, matches)
    }
}
