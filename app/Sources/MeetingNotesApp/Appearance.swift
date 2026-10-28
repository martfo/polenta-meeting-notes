// The app-wide font: a family and a base size, chosen in Settings, stored in
// user defaults, applied from the root view down. Semantic styles (titles,
// captions) keep their relative roles; the reading and writing surfaces
// follow the chosen base.

import SwiftUI

enum Appearance {
    static let sizeKey = "baseFontSize"
    static let designKey = "fontDesign"
    static let defaultSize = 13.0

    static let designs: [(name: String, raw: String)] = [
        ("System", "system"),
        ("Serif", "serif"),
        ("Rounded", "rounded"),
        ("Monospaced", "monospaced"),
    ]

    static func design(from raw: String) -> Font.Design {
        switch raw {
        case "serif": return .serif
        case "rounded": return .rounded
        case "monospaced": return .monospaced
        default: return .default
        }
    }

    static func font(size: Double, design raw: String) -> Font {
        .system(size: size, design: design(from: raw))
    }
}
