import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct SourceEvidence: Codable, Identifiable {
    let path: String
    let lineStart: Int
    let lineEnd: Int
    let contentHash: String
    let excerpt: String
    var excerptTruncated: Bool?
    var score: Double?
    var status: String?
    var claim: String?
    var id: String { "\(path):\(lineStart)-\(lineEnd)" }
    enum CodingKeys: String, CodingKey {
        case path, excerpt, score, status, claim
        case lineStart = "line_start", lineEnd = "line_end"
        case contentHash = "content_hash", excerptTruncated = "excerpt_truncated"
    }
}

struct SearchResponse: Decodable {
    let projectID: String
    let results: [SourceEvidence]
    let warnings: [String]
    let method: String
    let durationMs: Double
    let vectorSync: VectorSync?
    enum CodingKeys: String, CodingKey { case results, warnings, method; case durationMs = "duration_ms", vectorSync = "vector_sync", projectID = "project_id" }
}
struct VectorSync: Decodable {
    let embeddedChunks: Int
    let reusedChunks: Int
    let removedChunks: Int
    enum CodingKeys: String, CodingKey {
        case embeddedChunks = "embedded_chunks", reusedChunks = "reused_chunks", removedChunks = "removed_chunks"
    }
}
struct IndexResponse: Decodable { let projectID: String; enum CodingKeys: String, CodingKey { case projectID = "project_id" } }
struct SourceResponse: Decodable { let sources: [SourceEvidence] }
struct HistoryItem: Decodable, Identifiable { let id: String; let title: String; let createdAt: String; enum CodingKeys: String, CodingKey { case id, title; case createdAt = "created_at" } }
struct HistoryResponse: Decodable { let reviews: [HistoryItem] }
struct SavedPayload: Decodable { let original: String; let improved: String; let sources: [SourceEvidence]; let assumptions: [String]? }
struct SavedReview: Decodable { let id: String; let payload: SavedPayload }
struct HealthResponse: Decodable { let semantic: Bool; let reranker: Bool }

struct ServiceClient {
    let base: URL
    let token: String

    // Service configuration comes from the launching environment, not model text.
    static func configured(environment: [String:String] = ProcessInfo.processInfo.environment) throws -> ServiceClient? {
        var address = environment["PROMPT_AID_SERVICE_URL"]
        var tokenPath = environment["PROMPT_AID_TOKEN_FILE"]
        if address == nil {
            let path = environment["PROMPT_AID_CONNECTION_FILE"] ?? NSString(string: "~/.local/share/prompt-aid/connection.json").expandingTildeInPath
            guard FileManager.default.fileExists(atPath:path) else { return nil }
            let attributes = try FileManager.default.attributesOfItem(atPath:path)
            guard (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600,
                  (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                  attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.size] as? NSNumber)?.intValue ?? Int.max <= 16000 else {
                throw ServiceError.message("Workspace configuration must be a private owned file (0600).")
            }
            struct Connection: Decodable { let url: String; let token_file: String }
            let config = try JSONDecoder().decode(Connection.self, from: Data(contentsOf:URL(fileURLWithPath:path)))
            address = config.url; tokenPath = config.token_file
        }
        guard let address else { return nil }
        guard let url = URL(string: address), url.scheme == "http", url.host == "127.0.0.1",
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.path.isEmpty || url.path == "/" else { throw ServiceError.message("Service URL must be an HTTP address at 127.0.0.1.") }
        let file = tokenPath ?? NSString(string: "~/.local/share/prompt-aid/api-token").expandingTildeInPath
        let attributes = try FileManager.default.attributesOfItem(atPath: file)
        guard (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600,
              attributes[.type] as? FileAttributeType == .typeRegular else {
            throw ServiceError.message("Service token file must be a regular private file (0600).")
        }
        let token = try String(contentsOfFile: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        guard token.count >= 32 else { throw ServiceError.message("Invalid service token.") }
        return ServiceClient(base: url, token: token)
    }

    func request<T: Decodable>(_ route: String, method: String = "GET", body: [String:Any]? = nil) async throws -> T {
        guard let url = URL(string: route, relativeTo: base), url.host == base.host, url.port == base.port,
              url.scheme == base.scheme, url.user == nil, url.password == nil else { throw ServiceError.message("Invalid local route.") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 60
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        // Never forward the token through an HTTP redirect.
        let session = URLSession(configuration: .ephemeral, delegate: NoRedirects(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let error = (try? JSONSerialization.jsonObject(with: data)) as? [String:Any]
            throw ServiceError.message(error?["error"] as? String ?? "Local service request failed.")
        }
        guard data.count <= 256_000 else { throw ServiceError.message("Local response exceeded its size limit.") }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
enum ServiceError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

func sourceObjects(_ sources: [SourceEvidence]) throws -> [[String:Any]] {
    let data = try JSONEncoder().encode(sources)
    return try JSONSerialization.jsonObject(with: data) as? [[String:Any]] ?? []
}
