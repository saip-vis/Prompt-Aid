// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "PromptAidCore",
    platforms: [.macOS(.v13)],
    products: [.library(name: "PromptAidCore", targets: ["PromptAidCore"])],
    targets: [
        .target(name: "PromptAidCore", path: "native", exclude: ["PromptAid.swift", "BuildMode.swift", "BuildMain.swift", "EditingMenu.swift", "build.sh", "Tests"], sources: ["ServiceClient.swift", "ReviewProtocol.swift", "BuildModels.swift"]),
        .testTarget(name: "PromptAidCoreTests", dependencies: ["PromptAidCore"], path: "native/Tests")
    ]
)
