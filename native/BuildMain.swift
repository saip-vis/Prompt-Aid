import AppKit

@main struct PromptAidBuildMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = BuildAppDelegate()
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        app.run()
    }
}
