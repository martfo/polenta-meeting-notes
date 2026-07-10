// Mixes the microphone and system-audio streams into the single 16 kHz mono
// WAV the pipeline expects. Pure functions over sample buffers, so the tests
// feed known buffers and assert the output exactly.

import Foundation

/// Converts a mach host time (as carried by AVAudioTime and Core Audio's
/// AudioTimeStamp) to seconds, so the microphone and system-audio callbacks
/// can be placed on one shared clock.
public enum HostClock {
    public static func seconds(_ hostTime: UInt64) -> Double {
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        return Double(hostTime) * Double(info.numer) / Double(info.denom) / 1_000_000_000
    }
}

public enum AudioMixer {
    public static let targetSampleRate = 16_000

    /// Linear-interpolation resample to the target rate. Good enough for
    /// speech transcription; the original recording is kept for playback.
    public static func resample(_ samples: [Float], from sourceRate: Double, to targetRate: Double = Double(targetSampleRate)) -> [Float] {
        guard !samples.isEmpty, sourceRate > 0 else { return [] }
        if sourceRate == targetRate { return samples }
        let ratio = sourceRate / targetRate
        let outputCount = Int((Double(samples.count) / ratio).rounded())
        var output = [Float](repeating: 0, count: outputCount)
        for i in 0..<outputCount {
            let position = Double(i) * ratio
            let index = Int(position)
            let fraction = Float(position - Double(index))
            let a = samples[min(index, samples.count - 1)]
            let b = samples[min(index + 1, samples.count - 1)]
            output[i] = a + (b - a) * fraction
        }
        return output
    }

    /// Append a resampled buffer to a channel's running samples, placed at its
    /// true time on a clock shared with the other channel.
    ///
    /// The microphone and the system-audio tap run on different device clocks
    /// and deliver buffers independently; the tap in particular can stall while
    /// nothing is playing. Appending each buffer positionally lets the two
    /// channels drift apart, so a later merge by timestamp piles one speaker's
    /// turns at the end. Instead every buffer carries the host time of its
    /// first sample: the gap since the shared origin is filled with silence, so
    /// sample index maps to the same wall-clock instant in both channels and
    /// each channel's WAV stays full length. Buffers that would land in the past
    /// (clock jitter) are appended contiguously rather than rewritten.
    public static func place(
        _ block: [Float], into samples: inout [Float],
        atHostSeconds hostSeconds: Double, origin: Double,
        sampleRate: Int = targetSampleRate
    ) {
        guard !block.isEmpty else { return }
        let start = Int(((hostSeconds - origin) * Double(sampleRate)).rounded())
        if start > samples.count {
            samples.append(contentsOf: repeatElement(0, count: start - samples.count))
        }
        samples.append(contentsOf: block)
    }

    /// Average the two streams into one mono track at 16 kHz. The shorter
    /// stream is treated as silent once it runs out.
    public static func mixToMono16k(
        microphone: [Float], microphoneRate: Double,
        system: [Float], systemRate: Double
    ) -> [Int16] {
        let mic = resample(microphone, from: microphoneRate)
        let sys = resample(system, from: systemRate)
        let count = max(mic.count, sys.count)
        var mixed = [Int16](repeating: 0, count: count)
        for i in 0..<count {
            let m = i < mic.count ? mic[i] : 0
            let s = i < sys.count ? sys[i] : 0
            let value = max(-1.0, min(1.0, (m + s) * 0.5))
            mixed[i] = Int16(value * Float(Int16.max))
        }
        return mixed
    }

    /// One channel of float samples as a 16-bit mono WAV, used to write the
    /// microphone and system streams separately.
    public static func monoWav(from floats: [Float], sampleRate: Int = targetSampleRate) -> Data {
        let samples = floats.map { Int16(max(-1, min(1, $0)) * Float(Int16.max)) }
        return wavData(samples: samples, sampleRate: sampleRate)
    }

    /// A minimal RIFF/WAVE container: PCM, one channel, 16-bit.
    public static func wavData(samples: [Int16], sampleRate: Int = targetSampleRate) -> Data {
        let dataSize = samples.count * 2
        var data = Data(capacity: 44 + dataSize)

        func append(_ string: String) { data.append(contentsOf: string.utf8) }
        func append32(_ value: UInt32) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
        func append16(_ value: UInt16) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }

        append("RIFF"); append32(UInt32(36 + dataSize)); append("WAVE")
        append("fmt "); append32(16)
        append16(1)                       // PCM
        append16(1)                       // mono
        append32(UInt32(sampleRate))
        append32(UInt32(sampleRate * 2))  // byte rate
        append16(2)                       // block align
        append16(16)                      // bits per sample
        append("data"); append32(UInt32(dataSize))
        samples.withUnsafeBytes { data.append(contentsOf: $0) }
        return data
    }
}
