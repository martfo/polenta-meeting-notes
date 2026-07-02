// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MeetingNotes",
    platforms: [.macOS("14.4")],
    targets: [
        .target(
            name: "MeetingNotesCore",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "MeetingNotesApp",
            dependencies: ["MeetingNotesCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "MeetingNotesCoreTests",
            dependencies: ["MeetingNotesCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
