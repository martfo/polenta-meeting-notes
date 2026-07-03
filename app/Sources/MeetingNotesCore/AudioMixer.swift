// Mixes the microphone and system-audio streams into the single 16 kHz mono
// WAV the pipeline expects. Pure functions over sample buffers, so the tests
// feed known buffers and assert the output exactly.

import Foundation

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
