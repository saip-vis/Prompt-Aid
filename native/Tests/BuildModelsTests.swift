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
}
