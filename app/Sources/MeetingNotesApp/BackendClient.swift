// The HTTP client for the local backend on 127.0.0.1:8765.

import Foundation
import MeetingNotesCore

struct BackendError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct MeetingSummaryRow: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let date: String
    let attendees: [String]
    let folder: String?
    let processing_status: String
    let summary_status: String
    let last_error: String?
    let failed_stage: String?
}

struct LibraryGroup: Codable, Identifiable, Hashable {
    var id: String { folder ?? "(unfiled)" }
    let folder: String?
    let meetings: [MeetingSummaryRow]
}

struct SpeakerAssignment: Codable, Identifiable, Hashable {
    let id: Int
    let diarised_label: String
    let display_name: String?
    let assigned_by: String?
    let confirmed: Int
    let match_score: Double?
}

struct MeetingDetail: Codable {
    let id: String
    let title: String
    let folder: String?
    let processing_status: String
    let summary_status: String
    let last_error: String?
    let failed_stage: String?
    let transcript: String?
    let summary: String?
    let notes: String
    let reveal_path: String
}

final class BackendClient: BackendEnqueuing, @unchecked Sendable {
    let baseURL: URL
    private let session: URLSession

    init(port: Int = 8765) {
        self.baseURL = URL(string: "http://127.0.0.1:\(port)")!
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 600
        self.session = URLSession(configuration: configuration)
    }

    // MARK: - Async surface used by the UI

    func health() async throws -> [String: AnyDecodable] {
        try await get("/health")
    }

    func library() async throws -> [LibraryGroup] {
        try await get("/meetings")
    }

    func meeting(_ id: String) async throws -> MeetingDetail {
        try await get("/meetings/\(id)")
    }

    func retry(_ id: String) async throws {
        let _: [String: AnyDecodable] = try await post("/meetings/\(id)/retry", body: nil)
    }

    func chat(_ id: String, question: String) async throws -> String {
        struct Answer: Codable { let answer: String }
        let answer: Answer = try await post("/meetings/\(id)/chat", body: ["question": question])
        return answer.answer
    }

    func saveNotes(_ id: String, text: String) async throws {
        let _: [String: AnyDecodable] = try await put("/meetings/\(id)/notes", body: ["text": text])
    }

    func folders() async throws -> [String] {
        try await get("/folders")
    }

    func fileMeeting(_ id: String, folder: String) async throws {
        let _: [String: AnyDecodable] = try await put("/meetings/\(id)/folder", body: ["name": folder])
    }

    func suggestFolder(_ id: String) async throws -> String? {
        struct Suggestion: Codable { let folder: String?; let is_new: Bool }
        let suggestion: Suggestion = try await post("/meetings/\(id)/suggest-folder", body: nil)
        return suggestion.folder
    }

    func renameMeeting(_ id: String, title: String) async throws {
        let _: [String: AnyDecodable] = try await put("/meetings/\(id)/title", body: ["name": title])
    }

    func meetingSpeakers(_ id: String) async throws -> [SpeakerAssignment] {
        try await get("/meetings/\(id)/speakers")
    }

    func confirmSpeaker(_ assignmentID: Int) async throws {
        let _: [String: AnyDecodable] = try await post(
            "/speaker-assignments/\(assignmentID)/confirm", body: nil)
    }

    func nameSpeaker(_ assignmentID: Int, name: String) async throws {
        let _: [String: AnyDecodable] = try await post(
            "/speaker-assignments/\(assignmentID)/correct", body: ["name": name])
    }

    // MARK: - BackendEnqueuing (synchronous: called from the recording path)

    @discardableResult
    func importMeeting(audioPath: String, title: String, source: String) throws -> String {
        struct Imported: Codable { let meeting_id: String }
        let body = ["path": audioPath, "title": title, "source": source]
        let result: Imported = try syncRequest("POST", "/meetings/import", body: body)
        return result.meeting_id
    }

    // MARK: - Plumbing

    private func get<T: Decodable>(_ path: String) async throws -> T {
        try await request("GET", path, body: nil)
    }

    private func post<T: Decodable>(_ path: String, body: [String: String]?) async throws -> T {
        try await request("POST", path, body: body)
    }

    private func put<T: Decodable>(_ path: String, body: [String: String]?) async throws -> T {
        try await request("PUT", path, body: body)
    }

    private func makeRequest(_ method: String, _ path: String, body: [String: String]?) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func request<T: Decodable>(_ method: String, _ path: String, body: [String: String]?) async throws -> T {
        let (data, response) = try await session.data(for: try makeRequest(method, path, body: body))
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw BackendError(message: "The backend answered with an error for \(path).")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func syncRequest<T: Decodable>(_ method: String, _ path: String, body: [String: String]?) throws -> T {
        let semaphore = DispatchSemaphore(value: 0)
        var outcome: Result<T, Error> = .failure(BackendError(message: "The backend did not answer."))
        let request = try makeRequest(method, path, body: body)
        session.dataTask(with: request) { data, response, error in
            defer { semaphore.signal() }
            if let error {
                outcome = .failure(error)
                return
            }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data else {
                outcome = .failure(BackendError(message: "The backend answered with an error for \(path)."))
                return
            }
            do { outcome = .success(try JSONDecoder().decode(T.self, from: data)) }
            catch { outcome = .failure(error) }
        }.resume()
        semaphore.wait()
        return try outcome.get()
    }
}

/// Decodes any JSON value; used where the shape does not matter.
struct AnyDecodable: Decodable {
    let value: Any

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let intValue = try? container.decode(Int.self) { value = intValue }
        else if let doubleValue = try? container.decode(Double.self) { value = doubleValue }
        else if let boolValue = try? container.decode(Bool.self) { value = boolValue }
        else if let stringValue = try? container.decode(String.self) { value = stringValue }
        else if let arrayValue = try? container.decode([AnyDecodable].self) { value = arrayValue.map(\.value) }
        else if let dictValue = try? container.decode([String: AnyDecodable].self) { value = dictValue.mapValues(\.value) }
        else { value = NSNull() }
    }
}
