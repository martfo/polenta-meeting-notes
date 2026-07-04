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

struct MeetingAttendee: Codable, Hashable {
    let name: String
    let email: String?
}

struct MeetingDetail: Codable {
    let id: String
    let title: String
    let folder: String?
    let attendees: [MeetingAttendee]
    let summary_edited: Int?
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

    func chat(_ id: String, question: String,
              history: [(question: String, answer: String)] = []) async throws -> String {
        struct Turn: Encodable { let question: String; let answer: String }
        struct Payload: Encodable { let question: String; let history: [Turn] }
        struct Answer: Codable { let answer: String }
        let payload = Payload(
            question: question,
            history: history.map { Turn(question: $0.question, answer: $0.answer) })
        let answer: Answer = try await send("POST", "/meetings/\(id)/chat", encodable: payload)
        return answer.answer
    }

    func saveSummary(_ id: String, body: String) async throws {
        let _: [String: AnyDecodable] = try await put("/meetings/\(id)/summary", body: ["body": body])
    }

    func restoreDefaultSummaryPrompt() async throws {
        let _: [String: AnyDecodable] = try await post("/settings/restore-summary-prompt", body: nil)
    }

    /// Returns the backend's summary decision: none, regenerating, or prompt
    /// (the summary is hand-edited, so ask before replacing it).
    @discardableResult
    func saveNotes(_ id: String, text: String) async throws -> String {
        struct Response: Codable { let saved: Bool; let summary_action: String }
        let response: Response = try await put("/meetings/\(id)/notes", body: ["text": text])
        return response.summary_action
    }

    func regenerateSummary(_ id: String) async throws {
        let _: [String: AnyDecodable] = try await post("/meetings/\(id)/regenerate-summary", body: nil)
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

    func pasteImage(_ id: String, data: Data, suffix: String = "png") async throws -> (path: String, summaryAction: String) {
        struct Payload: Encodable { let data_base64: String; let suffix: String }
        struct Response: Codable { let path: String; let summary_action: String }
        let response: Response = try await send(
            "POST", "/meetings/\(id)/notes/image",
            encodable: Payload(data_base64: data.base64EncodedString(), suffix: suffix))
        return (response.path, response.summary_action)
    }

    func setAttendees(_ id: String, attendees: [MeetingAttendee]) async throws {
        struct Payload: Encodable { let attendees: [MeetingAttendee] }
        let _: [String: AnyDecodable] = try await send(
            "POST", "/meetings/\(id)/attendees", encodable: Payload(attendees: attendees))
    }

    func assignAttendee(_ assignmentID: Int, name: String) async throws {
        let _: [String: AnyDecodable] = try await post(
            "/speaker-assignments/\(assignmentID)/attendee", body: ["name": name])
    }

    func libraryChat(question: String, allFolders: Bool, folder: String?) async throws -> (answer: String, citations: [String]) {
        struct Response: Codable { let answer: String; let citations: [String] }
        var body = ["question": question, "scope": allFolders ? "all" : "folder"]
        if let folder { body["folder"] = folder }
        let response: Response = try await post("/library/chat", body: body)
        return (response.answer, response.citations)
    }

    func deleteMeeting(_ id: String) async throws {
        let _: [String: AnyDecodable] = try await request("DELETE", "/meetings/\(id)", body: nil)
    }

    func renameMeeting(_ id: String, title: String) async throws {
        let _: [String: AnyDecodable] = try await put("/meetings/\(id)/title", body: ["name": title])
    }

    struct GranolaImportFailure: Codable {
        let row: Int
        let title: String
        let reason: String
    }

    struct GranolaImportResult: Codable {
        let total_rows: Int
        let imported: Int
        let skipped: Int
        let empty: Int
        let failed: Int
        let reconciled: Bool
        let folders_created: [String]
        let mapped_columns: [String: String]
        let unmapped_columns: [String]
        let failures: [GranolaImportFailure]
        let warnings: [String]
    }

    func importGranolaCSV(_ csvText: String) async throws -> GranolaImportResult {
        struct Payload: Encodable { let csv_text: String }
        return try await send("POST", "/import/granola", encodable: Payload(csv_text: csvText))
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

    private func send<T: Decodable, B: Encodable>(_ method: String, _ path: String, encodable: B) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.httpBody = try JSONEncoder().encode(encodable)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
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
