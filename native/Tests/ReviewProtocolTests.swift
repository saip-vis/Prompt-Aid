import XCTest
@testable import PromptAidCore

final class ReviewProtocolTests: XCTestCase {
    func read(_ values: [String:Any]) throws -> Review {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:file) }
        try JSONSerialization.data(withJSONObject:values).write(to:file)
        return try Review.read(file)
    }
    func testPendingAcceptsOnlySameRequestAndProjectFinalReview() throws {
        let pending = try read(["original":"Fix login", "improved":"", "pending":true, "projectRoot":"/repo"])
        let final = try read(["original":"Fix login", "improved":"Fix session handling", "projectRoot":"/repo"])
        XCTAssertTrue(pending.accepts(final))
        XCTAssertFalse(final.accepts(pending))
        XCTAssertFalse(pending.accepts(try read(["original":"Other task", "improved":"Do other work", "projectRoot":"/repo"])))
        XCTAssertFalse(pending.accepts(try read(["original":"Fix login", "improved":"Fix session", "projectRoot":"/other"])))
    }
    func testFinalReviewRequiresDraftAndBoundsInput() throws {
        XCTAssertThrowsError(try read(["original":"Fix login", "improved":""]))
        XCTAssertThrowsError(try read(["original":String(repeating:"x",count:12001), "improved":"Fix login"]))
        XCTAssertNoThrow(try read(["original":"Fix login", "improved":"Fix login", "pending":false]))
    }
}
