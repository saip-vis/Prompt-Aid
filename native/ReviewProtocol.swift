import Foundation

struct Review: Decodable {
    let original: String
    let improved: String
    let changes: [String]?
    let questions: [String]?
    let limitations: [String]?
    let evidence: [String]?
    let sources: [SourceEvidence]?
    let projectRoot: String?
    let assumptions: [String]?
    let pending: Bool?
    var isPreparing: Bool { pending == true }

    static func read(_ url: URL) throws -> Review {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
        guard size <= 128_000 else { throw ServiceError.message("Review is too large.") }
        let data = try Data(contentsOf: url)
        guard data.count <= 128_000 else { throw ServiceError.message("Review is too large.") }
        let review = try JSONDecoder().decode(Review.self, from: data)
        guard !review.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              review.original.count <= 12000, review.improved.count <= 16000,
              review.isPreparing || !review.improved.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ServiceError.message("Invalid review text.")
        }
        return review
    }
    func accepts(_ update: Review) -> Bool {
        isPreparing && !update.isPreparing && update.original == original && update.projectRoot == projectRoot
    }
}

// Opt-in, content-free timing. The host can separate review preparation from UI
// startup without recording prompts, file paths, model input or credentials.
@MainActor enum LaunchMetrics {
    static var started = ProcessInfo.processInfo.systemUptime
    static var events: [String:Double] = [:]
    static func record(_ event: String) {
        guard let path = ProcessInfo.processInfo.environment["PROMPT_AID_LAUNCH_METRICS"] else { return }
        events[event] = (ProcessInfo.processInfo.systemUptime - started) * 1000
        guard let data = try? JSONSerialization.data(withJSONObject:events, options:.sortedKeys) else { return }
        try? data.write(to:URL(fileURLWithPath:path), options:.atomic)
        try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path)
    }
}
