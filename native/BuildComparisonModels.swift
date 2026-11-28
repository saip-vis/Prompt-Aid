import Foundation

struct CreatorDemo: Decodable { let spec: BuildSpecification?;let synthetic: Bool;let description: String }
struct SourceCaseEvidence: Decodable, Identifiable {
    let caseID: String;let passed: Bool;let reason: String;let expected: EvidenceValue?;let actual: EvidenceValue?;let source: String?
    var id: String { caseID }
    enum CodingKeys: String,CodingKey { case passed,reason,expected,actual,source;case caseID = "case_id" }
}
indirect enum EvidenceValue: Decodable {
    case text(String),number(Double),boolean(Bool),null,array([EvidenceValue]),object([String:EvidenceValue])
    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let item = try? value.decode(Bool.self) { self = .boolean(item) }
        else if let item = try? value.decode(String.self) { self = .text(item) }
        else if let item = try? value.decode(Double.self) { self = .number(item) }
        else if let item = try? value.decode([EvidenceValue].self) { self = .array(item) }
        else { self = .object(try value.decode([String:EvidenceValue].self)) }
    }
    var display: String {
        switch self {
        case .text(let item): return item
        case .number(let item): return String(format:"%g",item)
        case .boolean(let item): return item ? "true" : "false"
        case .null: return "unknown"
        case .array(let items): return "["+items.map(\.display).joined(separator:", ")+"]"
        case .object(let items): return items.keys.sorted().map { $0+": "+items[$0]!.display }.joined(separator:", ")
        }
    }
}
struct RecordedAttempt: Decodable {
    let label: String;let kind: String;let turn: Int;let elapsedMS: Double?;let workerMS: Double?;let usage: [String:Int]
    let checksPassed: Int;let checksTotal: Int;let casesPassed: Int;let casesTotal: Int;let checks: [CheckOutcome];let output: String?
    enum CodingKeys: String,CodingKey { case label,kind,turn,usage,checks,output;case elapsedMS = "elapsed_ms", workerMS = "worker_ms", checksPassed = "checks_passed", checksTotal = "checks_total", casesPassed = "cases_passed", casesTotal = "cases_total" }
}
struct BuildComparison: Decodable { let mode: String;let comparable: Bool;let notes: [String];let baseline: RecordedAttempt?;let result: RecordedAttempt?;let replay: [RecordedAttempt] }
