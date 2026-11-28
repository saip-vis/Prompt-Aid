import XCTest
@testable import PromptAidCore

final class ServiceClientTests: XCTestCase {
    func testLegacyWorkflowDoesNotRequireService() throws {
        XCTAssertNil(try ServiceClient.configured(environment: ["PROMPT_AID_CONNECTION_FILE":"/nonexistent/prompt-aid-test.json"]))
    }
    func testRejectsExternalServicesAndInsecureTokenFiles() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("token")
        try String(repeating: "x", count: 40).write(to: file, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:file.path)
        var environment = ["PROMPT_AID_SERVICE_URL":"http://127.0.0.1:4318", "PROMPT_AID_TOKEN_FILE":file.path]
        XCTAssertNotNil(try ServiceClient.configured(environment:environment))
        for url in ["https://example.com", "http://127.0.0.1:4318@evil.example", "http://127.0.0.1:4318?token=secret", "http://127.0.0.1:4318/other"] {
            environment["PROMPT_AID_SERVICE_URL"] = url
            XCTAssertThrowsError(try ServiceClient.configured(environment:environment))
        }
        environment["PROMPT_AID_SERVICE_URL"] = "http://127.0.0.1:4318"
        try FileManager.default.setAttributes([.posixPermissions:0o644], ofItemAtPath:file.path)
        XCTAssertThrowsError(try ServiceClient.configured(environment:environment))
    }
    func testEvidenceRoundTripPreservesHashesAndUnverifiedClaims() throws {
        let json = """
        {"path":"src/login.py","line_start":3,"line_end":8,"content_hash":"abcdef","excerpt":"def login(): pass","status":"stale","claim":"This fixes authentication"}
        """
        let source = try JSONDecoder().decode(SourceEvidence.self, from:Data(json.utf8))
        XCTAssertEqual(source.id,"src/login.py:3-8")
        let objects = try sourceObjects([source])
        XCTAssertEqual(objects[0]["content_hash"] as? String,"abcdef")
        XCTAssertEqual(objects[0]["status"] as? String,"stale")
        XCTAssertEqual(objects[0]["claim"] as? String,"This fixes authentication")
    }
}

extension ServiceClientTests {
    func testPrivateConnectionDescriptorAndExplicitEnvironmentOverride() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:dir, withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:dir) }
        let token = dir.appendingPathComponent("token")
        try String(repeating:"x",count:40).write(to:token, atomically:true, encoding:.utf8)
        try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:token.path)
        let descriptor = dir.appendingPathComponent("connection.json")
        try JSONSerialization.data(withJSONObject:["url":"http://127.0.0.1:4318", "token_file":token.path]).write(to:descriptor)
        try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:descriptor.path)
        let client = try ServiceClient.configured(environment:["PROMPT_AID_CONNECTION_FILE":descriptor.path])
        XCTAssertEqual(client?.base.port,4318)
        let override = try ServiceClient.configured(environment:["PROMPT_AID_CONNECTION_FILE":descriptor.path,"PROMPT_AID_SERVICE_URL":"http://127.0.0.1:4320","PROMPT_AID_TOKEN_FILE":token.path])
        XCTAssertEqual(override?.base.port,4320)
        try FileManager.default.setAttributes([.posixPermissions:0o644],ofItemAtPath:descriptor.path)
        XCTAssertThrowsError(try ServiceClient.configured(environment:["PROMPT_AID_CONNECTION_FILE":descriptor.path]))
    }
}
