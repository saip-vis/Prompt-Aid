import AppKit
import SwiftUI

struct Review: Decodable {
    let original: String
    let improved: String
    let changes: [String]?
    let questions: [String]?
    let limitations: [String]?
}

final class ReviewSession: ObservableObject {
    let review: Review
    @Published var draft: String
    private var completed = false
    init(_ review: Review) { self.review = review; self.draft = review.improved }
    func finish(_ action: String) {
        guard !completed else { return }
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        if action == "run" && (trimmed.isEmpty || draft.count > 16000) { return }
        completed = true
        var output: [String: String] = ["action": action]
        if action == "run" { output["prompt"] = draft }
        if let data = try? JSONSerialization.data(withJSONObject: output),
           let json = String(data: data, encoding: .utf8) {
            print(json)
            fflush(stdout)
        }
        NSApplication.shared.terminate(nil)
    }
}

struct ReviewView: View {
    @ObservedObject var session: ReviewSession
    let deep = Color(red: 0.07, green: 0.11, blue: 0.08)
    let panel = Color(red: 0.12, green: 0.17, blue: 0.13)
    let soft = Color(red: 0.70, green: 0.78, blue: 0.69)
    let accent = Color(red: 0.76, green: 0.88, blue: 0.70)

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("P").font(.system(size: 19, weight: .medium, design: .serif))
                    .foregroundStyle(deep).frame(width: 32, height: 32)
                    .background(accent, in: RoundedRectangle(cornerRadius: 9))
                Text("Prompt Aid").font(.system(size: 15, weight: .semibold))
                Spacer()
                Text("REVIEW BEFORE RUNNING").font(.system(size: 10, weight: .semibold)).tracking(0.8).foregroundStyle(soft)
            }
            Divider().overlay(.white.opacity(0.12))
            VStack(alignment: .leading, spacing: 3) {
                Text("Make your request clearer.").font(.system(size: 27, weight: .regular, design: .serif))
                Text("Compare the drafts and edit the suggestion before running it.").font(.system(size: 13)).foregroundStyle(soft)
            }
            HStack(alignment: .top, spacing: 12) {
                promptPanel("Original prompt", text: .constant(session.review.original), editable: false)
                promptPanel("Suggested prompt · editable", text: $session.draft, editable: true)
            }
            ScrollView {
                HStack(alignment: .top, spacing: 12) {
                    notes("What changed", session.review.changes)
                    notes("Questions", session.review.questions)
                    notes("Limitations", session.review.limitations)
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 64)
            Divider().overlay(.white.opacity(0.12))
            HStack(spacing: 12) {
                Text("Run returns this prompt to the active Codex session.")
                    .font(.system(size: 11)).foregroundStyle(soft)
                Spacer(minLength: 5)
                Button("Cancel") { session.finish("cancel") }.keyboardShortcut(.cancelAction)
                Button("Run with Codex →") { session.finish("run") }
                    .keyboardShortcut(.defaultAction)
                    .disabled(session.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || session.draft.count > 16000)
            }.controlSize(.large)
        }
        .padding(18)
        .foregroundStyle(Color.white.opacity(0.94))
        .background(deep)
        .frame(minWidth: 560, minHeight: 400)
    }
    func promptPanel(_ label: String, text: Binding<String>, editable: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.system(size: 12, weight: .semibold))
            TextEditor(text: text)
                .font(.system(size: 13)).scrollContentBackground(.hidden)
                .foregroundStyle(editable ? .white : soft)
                .disabled(!editable)
                .padding(7)
                .background(deep.opacity(0.65), in: RoundedRectangle(cornerRadius: 6))
                .frame(height: 105)
        }.padding(12).background(panel, in: RoundedRectangle(cornerRadius: 9))
    }
    @ViewBuilder func notes(_ title: String, _ entries: [String]?) -> some View {
        if let entries, !entries.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 11, weight: .semibold))
                ForEach(Array(entries.enumerated()), id: \.offset) { _, entry in
                    Text("• " + entry).font(.system(size: 11)).foregroundStyle(soft)
                }
            }.frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let session: ReviewSession
    var window: NSWindow?
    init(session: ReviewSession) { self.session = session }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = ReviewView(session: session)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 660, height: 500), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Prompt Aid"
        window.contentViewController = NSHostingController(rootView: view)
        window.minSize = NSSize(width: 560, height: 400)
        window.delegate = self
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { session.finish("cancel"); return false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "PromptAid", code: 1, userInfo: [NSLocalizedDescriptionKey: "Usage: PromptAid <review.json>"]) }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let data = try Data(contentsOf: url)
    guard data.count <= 100_000 else { throw NSError(domain: "PromptAid", code: 2, userInfo: [NSLocalizedDescriptionKey: "Review is too large."]) }
    let review = try JSONDecoder().decode(Review.self, from: data)
    guard !review.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          !review.improved.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          review.original.count <= 12000, review.improved.count <= 16000 else {
        throw NSError(domain: "PromptAid", code: 3, userInfo: [NSLocalizedDescriptionKey: "Invalid review text."])
    }
    let session = ReviewSession(review)
    let delegate = AppDelegate(session: session)
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.delegate = delegate
    app.run()
} catch {
    fputs("Prompt Aid could not open: \(error.localizedDescription)\n", stderr)
    exit(1)
}
