// The Core Audio process tap description. Building the description needs no
// permission; creating the tap from it (in the app target) surfaces the TCC
// prompt on first use.

import CoreAudio
import Foundation

public enum TapFactory {
    /// A global tap that captures every process's output, kept private to
    /// this app and unmuted so the user still hears their call. The uuid is
    /// the sub-tap key when the tap joins an aggregate device.
    public static func makeGlobalTapDescription(excluding processes: [AudioObjectID] = []) -> CATapDescription {
        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: processes)
        description.uuid = UUID()
        // The custom getter on this property confuses Swift's leading-dot
        // shorthand; the explicit enum type compiles everywhere.
        description.muteBehavior = CATapMuteBehavior.unmuted
        description.isPrivate = true
        description.name = "MeetingNotes system audio tap"
        return description
    }
}
