// Free disk space and when to warn about it. A recording is held in memory
// and written out when it stops, so a disk that fills during a call loses the
// whole meeting; the warning comes early enough to act on. Pure logic plus one
// file-system read, so the thresholds are tested without a full disk.

import Foundation

public enum DiskSpace {
    /// Below this much free space the person is warned.
    public static let warnBelowBytes: Int64 = 10_000_000_000
    /// What an hour of recording needs at its peak: three 16 kHz tracks
    /// (mixed, microphone, call audio) of about 115 MB each, written once as
    /// a capture and once into the meeting before the capture is removed.
    public static let bytesPerRecordingHour: Int64 = 700_000_000

    /// The warning to show for this much free space, or nil when there is
    /// plenty.
    public static func warning(freeBytes: Int64) -> String? {
        guard freeBytes < warnBelowBytes else { return nil }
        let hours = max(0, freeBytes / bytesPerRecordingHour)
        let room = hours < 1
            ? "not enough for an hour of recording"
            : "enough for about \(hours) hour\(hours == 1 ? "" : "s") of recording"
        return "Your Mac has \(format(freeBytes)) free, \(room). Free some space, or "
            + "choose how long to keep recordings in Settings, Storage."
    }

    /// The space available for the volume holding url, as the system counts
    /// it for important use (purgeable space included).
    public static func freeBytes(at url: URL) -> Int64? {
        let values = try? url.resourceValues(forKeys: [
            .volumeAvailableCapacityForImportantUsageKey, .volumeAvailableCapacityKey])
        if let important = values?.volumeAvailableCapacityForImportantUsage, important > 0 {
            return important
        }
        return values?.volumeAvailableCapacity.map(Int64.init)
    }

    public static func format(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
