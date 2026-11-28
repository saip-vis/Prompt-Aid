import Foundation

struct BuildConfiguration: Decodable { let roots: [String]; let workerAvailable: Bool
    enum CodingKeys: String, CodingKey { case roots; case workerAvailable = "worker_available" }
}
struct CompletionCheck: Codable {
    let kind: String; let label: String; let argv: [String]; let path: String?; let text: String?
    var timeoutSeconds: Int? = nil
    var rule: String? = nil; var criterionIndices: [Int]? = nil
    enum CodingKeys: String, CodingKey { case kind,label,argv,path,text,rule; case timeoutSeconds = "timeout_seconds", criterionIndices = "criterion_indices" }
}
struct SuggestedCheck: Decodable, Identifiable {
    let id: String; let title: String; let description: String; let evidence: String; let check: CompletionCheck
    var checkExplanation: String {
        if check.kind == "creator_offer" { return "Runs \(check.path ?? "extractor") against frozen synthetic inputs; validates \(check.rule ?? "output")" }
        return displayCommand(check.argv)
    }
}
struct CheckSuggestions: Decodable {
    let root: String; let suggestions: [SuggestedCheck]; let notices: [String]; let ready: Bool; let readinessMessage: String
    var environmentMemory: EnvironmentMemory?
    enum CodingKeys: String, CodingKey { case root,suggestions,notices,ready; case readinessMessage = "readiness_message", environmentMemory = "environment_memory" }
}

// Display an argv faithfully; custom checks can round-trip quoted/empty arguments.
func displayCommand(_ arguments: [String]) -> String {
    arguments.map { argument in
        if !argument.isEmpty && argument.allSatisfy({ $0.isLetter || $0.isNumber || "-_./:=*".contains($0) }) { return argument }
        return "'" + argument.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }.joined(separator: " ")
}
struct BuildSpecification: Codable {
    let root: String; let goal: String; let constraints: [String]; let checks: [CompletionCheck]
    let maxTurns: Int; let maxSeconds: Int; let approved: Bool
    var acceptanceCriteria: [String]? = nil
    enum CodingKeys: String, CodingKey { case root,goal,constraints,checks,approved; case maxTurns = "max_turns", maxSeconds = "max_seconds", acceptanceCriteria = "acceptance_criteria" }
}
struct CheckOutcome: Decodable { let label: String; let passed: Bool; let details: String; var status: String?; var reason: String?
    var cases: [SourceCaseEvidence]?
    var title: String { (status == "blocked" ? "Couldn’t run · " : passed ? "Passed · " : "Failed · ")+label }
}
struct CriterionEvidence: Decodable { let text: String; let status: String; let evidence: String
    var automatedStatus: String?;var automatedEvidence: [LinkedCheckEvidence]?
    enum CodingKeys: String,CodingKey { case text,status,evidence;case automatedStatus = "automated_status", automatedEvidence = "automated_evidence" }
}
struct LinkedCheckEvidence: Decodable { let label: String;let status: String;let casesPassed: Int;let casesTotal: Int
    var display: String {
        let count = casesTotal>0 ? " · \(casesPassed)/\(casesTotal) assertions" : ""
        return "Automated support: \(label) · \(status)\(count)"
    }
    enum CodingKeys: String,CodingKey { case label,status;case casesPassed = "cases_passed", casesTotal = "cases_total" }
}
struct RuntimeEvidence: Decodable { let label: String; let status: String; let reason: String; let details: String? }
struct BuildOutcome: Decodable { let code: String; let title: String; let summary: String }
struct EnvironmentMemory: Decodable { let updatedAt: String; let results: Results
    struct Results: Decodable { let preflight: [RuntimeEvidence]?; let checks: [RuntimeEvidence]? }
    enum CodingKeys: String,CodingKey { case results;case updatedAt = "updated_at" }
}
struct BuildPayload: Decodable {
    let turn: Int; let message: String; let worktree: String?; let checks: [CheckOutcome]
    var preflight: [RuntimeEvidence]?; var criteria: [CriterionEvidence]?; var workerSummary: String?; var checkStamp: String?
    enum CodingKeys: String,CodingKey { case turn,message,worktree,checks,preflight,criteria;case workerSummary = "worker_summary", checkStamp = "check_stamp" }
}
struct BuildRecord: Decodable, Identifiable { let id: String; let state: String; let spec: BuildSpecification; let payload: BuildPayload; var outcome: BuildOutcome? }
struct BuildList: Decodable { let builds: [BuildRecord] }
struct BuildEvent: Decodable, Identifiable {
    let seq: Int; let kind: String; let payload: EventPayload
    var id: Int { seq }
    struct EventPayload: Decodable { let summary: String?; let text: String?; let command: String?; let message: String?; let label: String?; let status: String?; let details: String? }
    var summary: String { payload.text ?? payload.summary ?? payload.command ?? payload.message ?? payload.label ?? kind.replacingOccurrences(of:"_",with:" ") }
}
struct BuildEvents: Decodable { let events: [BuildEvent] }
struct BuildDiff: Decodable { let diff: String }

// Split a user-approved executable/arguments without shell expansion.
func commandArguments(_ command: String) throws -> [String] {
    var result: [String] = [], token = "", quote: Character?, escaped = false, started = false
    for c in command {
        if escaped { token.append(c); escaped = false; started = true; continue }
        if c == "\\" && quote != "'" { escaped = true; started = true; continue }
        if let q = quote { if c == q { quote = nil } else { token.append(c) }; continue }
        if c == "\"" || c == "'" { quote = c; started = true }
        else if c.isWhitespace { if started { result.append(token); token = ""; started = false } }
        else { token.append(c); started = true }
    }
    guard quote == nil && !escaped else { throw ServiceError.message("Close the quotes in the completion command.") }
    if started { result.append(token) }
    guard !result.isEmpty else { throw ServiceError.message("Enter a completion command.") }
    return result
}

