// A calm markdown renderer for summaries and transcripts: semibold headings,
// softly muted body text, styled bullets, and generous line spacing, so the
// notes are comfortable to read rather than a wall of raw markdown. It honours
// the app's chosen font and size.

import SwiftUI

private enum Block: Identifiable {
    case section(String)      // ## heading
    case subheading(String)   // ### heading, or a line that is entirely bold
    case bullet(text: String, indent: Int)
    case paragraph(String)

    var id: String {
        switch self {
        case .section(let t): return "s:\(t)"
        case .subheading(let t): return "h:\(t)"
        case .bullet(let t, let i): return "b:\(i):\(t)"
        case .paragraph(let t): return "p:\(t)"
        }
    }
}

/// The text of a bullet if the line is one, for the marker styles a model
/// might emit: -, *, •, or a number followed by a dot or paren.
private func bulletBody(of line: String) -> String? {
    for marker in ["- ", "* ", "• ", "•\t"] {
        if line.hasPrefix(marker) {
            return String(line.dropFirst(marker.count)).trimmingCharacters(in: .whitespaces)
        }
    }
    if let match = line.range(of: #"^\d{1,2}[.)]\s+"#, options: .regularExpression) {
        return String(line[match.upperBound...])
    }
    return nil
}

private func parseBlocks(_ text: String) -> [Block] {
    var blocks: [Block] = []
    var paragraph: [String] = []

    func flushParagraph() {
        if !paragraph.isEmpty {
            blocks.append(.paragraph(paragraph.joined(separator: " ")))
            paragraph = []
        }
    }

    for rawLine in text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n") {
        let line = rawLine.trimmingCharacters(in: .whitespaces)
        let leading = rawLine.prefix { $0 == " " }.count

        if line.isEmpty {
            flushParagraph()
            continue
        }
        if line.hasPrefix("## ") {
            flushParagraph()
            blocks.append(.section(String(line.dropFirst(3))))
        } else if line.hasPrefix("### ") {
            flushParagraph()
            blocks.append(.subheading(String(line.dropFirst(4))))
        } else if let bulletBody = bulletBody(of: line) {
            flushParagraph()
            blocks.append(.bullet(text: bulletBody, indent: leading / 2))
        } else if line.hasPrefix("**") && line.hasSuffix("**") && line.count > 4
                    && !line.dropFirst(2).dropLast(2).contains("**") {
            // A line that is entirely bold reads as a sub-heading.
            flushParagraph()
            blocks.append(.subheading(String(line.dropFirst(2).dropLast(2))))
        } else {
            paragraph.append(line)
        }
    }
    flushParagraph()
    return blocks
}

struct RichMarkdownView: View {
    let text: String
    @AppStorage(Appearance.sizeKey) private var baseFontSize = Appearance.defaultSize
    @AppStorage(Appearance.designKey) private var fontDesign = "system"

    private var design: Font.Design { Appearance.design(from: fontDesign) }

    /// A lazy stack renders long transcripts cheaply but breaks text selection
    /// inside a ScrollView, so the summary (which the user wants to copy from)
    /// uses a plain VStack and only the long transcript opts into lazy.
    var lazy = false

    var body: some View {
        Group {
            if lazy {
                LazyVStack(alignment: .leading, spacing: 10) { blocks }
            } else {
                VStack(alignment: .leading, spacing: 10) { blocks }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var blocks: some View {
        ForEach(parseBlocks(text)) { block in
            switch block {
            case .section(let t):
                Text(LocalizedStringKey(t))
                    .font(.system(size: baseFontSize + 4, weight: .semibold, design: design))
                    .foregroundStyle(.primary)
                    .padding(.top, 8)
            case .subheading(let t):
                Text(LocalizedStringKey(t))
                    .font(.system(size: baseFontSize + 1, weight: .semibold, design: design))
                    .foregroundStyle(.primary)
                    .padding(.top, 2)
            case .bullet(let t, let indent):
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("•")
                        .font(.system(size: baseFontSize, design: design))
                        .foregroundStyle(.secondary)
                    Text(LocalizedStringKey(t))
                        .font(.system(size: baseFontSize, design: design))
                        .foregroundStyle(.primary.opacity(0.85))
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.leading, CGFloat(indent) * 18)
            case .paragraph(let t):
                Text(LocalizedStringKey(t))
                    .font(.system(size: baseFontSize, design: design))
                    .foregroundStyle(.primary.opacity(0.85))
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
