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
        // A tiny Objective-C shim to catch NSExceptions from AVFoundation calls
        // that would otherwise abort the app (AVAudioEngine.installTapOnBus).
        .target(name: "ObjCSupport"),
        .executableTarget(
            name: "MeetingNotesApp",
            dependencies: ["MeetingNotesCore", "ObjCSupport"],
            resources: [.copy("Resources")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "MeetingNotesCoreTests",
            dependencies: ["MeetingNotesCore", "ObjCSupport"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
