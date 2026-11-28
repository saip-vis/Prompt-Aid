import XCTest
@testable import PromptAidCore
final class BuildModelsTests: XCTestCase {
    func testCommandParsingDoesNotExpandShellSyntax() throws {
        XCTAssertEqual(try commandArguments("python3 -m unittest -v"),["python3","-m","unittest","-v"])
        XCTAssertEqual(try commandArguments("node 'script with spaces.js' \"literal $HOME\""),["node","script with spaces.js","literal $HOME"])
        XCTAssertEqual(try commandArguments("echo a && echo b"),["echo","a","&&","echo","b"])
        XCTAssertThrowsError(try commandArguments("node 'unfinished"))
        XCTAssertThrowsError(try commandArguments(" "))
    }
    func testSuggestedChecksAndQuotedCommandsPreserveApprovedArguments() throws {
        let arguments = ["python3", "space name.py", "literal'quote", "", "$HOME"]
        XCTAssertEqual(try commandArguments(displayCommand(arguments)), arguments)
        let payload = #"{"root":"/project","ready":true,"readiness_message":"Ready","notices":[],"suggestions":[{"id":"python","title":"Python tests","description":"Run tests","evidence":"tests/","check":{"kind":"command","label":"Python tests","argv":["python3","-m","pytest"],"timeout_seconds":120}}]}"#
        let value = try JSONDecoder().decode(CheckSuggestions.self, from: Data(payload.utf8))
        XCTAssertEqual(value.suggestions.first?.check.timeoutSeconds,120)
        let encoded = try JSONEncoder().encode(value.suggestions[0].check)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with:encoded) as? [String:Any])
        XCTAssertEqual(object["timeout_seconds"] as? Int,120)
    }
    func testOutcomeEvidenceSupportsLegacyHistoryAndExplicitManualCriteria() throws {
        let payload = #"{"id":"job","state":"needs_review","spec":{"root":"/project","goal":"Copy text","constraints":[],"checks":[],"max_turns":1,"max_seconds":180,"approved":true},"payload":{"turn":1,"message":"Review behavior","worktree":"/worktree","checks":[{"label":"Python","passed":false,"status":"blocked","reason":"Runtime missing","details":"Python blocked"}],"criteria":[{"text":"Copies exact saved text","status":"pending","evidence":"Not observed"}]},"outcome":{"code":"blocked_setup","title":"Blocked by setup","summary":"Checks could not run"}}"#
        let record = try JSONDecoder().decode(BuildRecord.self,from:Data(payload.utf8))
        XCTAssertEqual(record.outcome?.code,"blocked_setup")
        XCTAssertEqual(record.payload.checks[0].title,"Couldn’t run · Python")
        XCTAssertEqual(record.payload.criteria?[0].status,"pending")
        XCTAssertNil(record.spec.acceptanceCriteria)
    }
}
