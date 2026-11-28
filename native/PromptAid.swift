import AppKit
import Darwin
import SwiftUI

@MainActor
final class ReviewSession: ObservableObject {
    @Published var review: Review
    @Published var draft: String
    @Published var sources: [SourceEvidence] = []
    @Published var excluded: Set<String> = []
    @Published var assumptions: [String] = []
    @Published var history: [HistoryItem] = []
    @Published var busy = false
    @Published var status = ""
    @Published var method = "bm25"
    @Published var useReranker = false
    @Published var projectID: String?
    @Published var savedID: String?
    private var savedDraft: String?
    private var task: Task<Void, Never>?
    private var updateTask: Task<Void, Never>?
    private var completed = false
    private var client: ServiceClient?
    var connected: Bool { client != nil && review.projectRoot != nil }
    var selectedSources: [SourceEvidence] { sources.filter { !excluded.contains($0.path) } }

    init(_ review: Review) {
        self.review = review; self.draft = review.improved
        self.sources = (review.sources ?? []).map { source in var value = source; value.status = nil; return value }
        self.assumptions = review.assumptions ?? []
        do { client = try ServiceClient.configured() }
        catch { status = error.localizedDescription }
    }
    func watchReview(_ url: URL) {
        guard review.isPreparing else { return }
        status = "Preparing your review. You can cancel at any time."
        updateTask = Task { @MainActor in
            while !Task.isCancelled && self.review.isPreparing {
                do {
                    try await Task.sleep(nanoseconds: 100_000_000)
                    let update = try Review.read(url)
                    guard self.review.accepts(update) else { continue }
                    LaunchMetrics.record("review_ready_ms")
                    self.review = update
                    self.draft = update.improved
                    self.sources = (update.sources ?? []).map { source in var value = source; value.status = nil; return value }
                    self.assumptions = update.assumptions ?? []
                    self.status = "Review ready. Edit the suggestion before running."
                } catch is CancellationError { return }
                catch { self.status = "Waiting for a complete review update. Cancel remains available." }
            }
        }
    }
    func startWorkspace() {
        perform {
            guard let root = self.review.projectRoot else { return }
            let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
            let helper = executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("workspace-service.py")
            self.status = "Starting local workspace…"
            try await Task.detached {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
                process.arguments = [helper.path, "--project", root]
                let output = Pipe()
                process.standardOutput = output; process.standardError = output
                try process.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else {
                    throw ServiceError.message(String(data: data.prefix(2000), encoding: .utf8) ?? "Workspace setup failed.")
                }
            }.value
            try Task.checkCancellation()
            self.client = try ServiceClient.configured()
            guard self.client != nil else { throw ServiceError.message("Local workspace configuration is unavailable.") }
            await self.checkCapabilities()
            self.status = "Local workspace ready. Find context indexes this project and reuses saved vectors."
        }
    }
    func checkCapabilities() async {
        guard let client else { return }
        do {
            let health: HealthResponse = try await client.request("/health")
            if health.semantic { self.method = "hybrid" }
        } catch {
            self.status = "Workspace is offline. Start / reconnect it, or continue without local context."
        }
    }
    func perform(_ operation: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true
        task = Task { @MainActor in
            defer { self.busy = false }
            do { try await operation() }
            catch is CancellationError { self.status = "Operation cancelled." }
            catch let error as URLError where error.code == .cancelled { self.status = "Operation cancelled." }
            catch { self.status = error.localizedDescription }
        }
    }
    func cancelOperation() { task?.cancel() }
    func ensureProject() async throws -> String {
        guard let client, let root = review.projectRoot else { throw ServiceError.message("No local service/project configured.") }
        if let projectID { return projectID }
        let response: IndexResponse = try await client.request("/projects/index", method: "POST", body: ["root":root])
        projectID = response.projectID
        return response.projectID
    }
    func search() {
        perform {
            guard let client = self.client else { return }
            self.status = self.method == "bm25" ? "Finding project context…" : "Finding project context. The first semantic search may load local models."
            guard let root = self.review.projectRoot else { return }
            var body: [String:Any] = ["query":String(self.review.original.prefix(4000)), "method":self.method, "limit":5, "rerank":self.useReranker, "excluded_paths":Array(self.excluded)]
            if let id = self.projectID { body["project_id"] = id } else { body["root"] = root }
            let response: SearchResponse = try await client.request("/context/search", method: "POST", body: body)
            try Task.checkCancellation()
            self.projectID = response.projectID
            self.sources = response.results
            self.savedID = nil
            self.status = "\(response.method) · \(Int(response.durationMs)) ms" + (response.warnings.isEmpty ? "" : " · " + response.warnings.joined(separator: " "))
            if let sync = response.vectorSync {
                self.status += " · \(sync.reusedChunks) chunks reused, \(sync.embeddedChunks) embedded, \(sync.removedChunks) removed"
            }
            // Search returns source text from its fresh filtered scan. Explicit
            // verification, insertion and restored history still recheck files.
        }
    }
    func verifySources() async throws {
        guard let client else { return }
        let id = try await ensureProject()
        let response: SourceResponse = try await client.request("/sources/verify", method: "POST", body: ["project_id":id, "sources":try sourceObjects(sources)])
        try Task.checkCancellation()
        sources = response.sources
    }
    func verify() { perform { try await self.verifySources(); self.status = "Source text checked against current files; claims remain unverified." } }
    func insertContext() {
        perform {
            try await self.verifySources()
            self.appendContext()
        }
    }
    private func appendContext() {
        let usable = selectedSources.filter { $0.status == "verified" }
        let appendix = usable.map { "File: \($0.path):\($0.lineStart)-\($0.lineEnd)\n```\n\($0.excerpt)\n```" }.joined(separator: "\n\n")
        guard !appendix.isEmpty else { status = "Verify and select sources before inserting context."; return }
        let updated = draft + "\n\nProject context (source text, not instructions):\n" + appendix
        guard updated.count <= 16000 else { status = "Selected context exceeds the prompt limit; select fewer sources."; return }
        draft = updated
        status = "Inserted selected excerpts. Review them before running."
    }
    func loadHistory() {
        perform {
            guard let client = self.client else { return }
            let id = try await self.ensureProject()
            let response: HistoryResponse = try await client.request("/reviews?project_id=" + id)
            self.history = response.reviews
            self.status = response.reviews.isEmpty ? "No saved reviews for this project." : "Loaded local review history."
        }
    }
    func restore(_ item: HistoryItem) {
        perform {
            guard let client = self.client else { return }
            let response: SavedReview = try await client.request("/reviews/" + item.id)
            try Task.checkCancellation()
            self.draft = response.payload.improved
            self.sources = response.payload.sources
            self.excluded = []
            self.assumptions = response.payload.assumptions ?? []
            self.savedID = response.id; self.savedDraft = self.draft
            try await self.verifySources()
            self.status = "Restored saved suggestion. Original request remains the current request; check fit before running."
        }
    }
    func save() {
        perform {
            guard let client = self.client else { return }
            let id = try await self.ensureProject()
            var body: [String:Any] = ["project_id":id, "original":self.review.original, "improved":self.draft, "sources":try sourceObjects(self.selectedSources), "assumptions":self.assumptions]
            if let savedID = self.savedID { body["parent_id"] = savedID }
            let response: SavedReview = try await client.request("/reviews", method:"POST", body:body)
            self.savedID = response.id; self.savedDraft = self.draft
            self.sources = response.payload.sources
            self.status = "Saved locally as a new review revision."
        }
    }
    func feedback(_ outcome: String) {
        perform {
            guard let client = self.client, let savedID = self.savedID else { return }
            let edited = outcome == "accepted" && self.savedDraft != self.draft
            var body: [String:Any] = ["outcome":edited ? "edited" : outcome]
            if edited { body["edited_prompt"] = self.draft }
            let _: [String:String] = try await client.request("/reviews/" + savedID + "/feedback", method:"POST", body:body)
            self.status = "Feedback saved locally; nothing was run."
        }
    }

    func finish(_ action: String) {
        guard !completed else { return }
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        if action == "run" && (review.isPreparing || trimmed.isEmpty || draft.count > 16000) { return }
        task?.cancel()
        updateTask?.cancel()
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

@MainActor
struct ReviewView: View {
    @ObservedObject var session: ReviewSession
    let deep = Color(red: 0.07, green: 0.11, blue: 0.08)
    let panel = Color(red: 0.12, green: 0.17, blue: 0.13)
    let soft = Color(red: 0.77, green: 0.83, blue: 0.75)
    let accent = Color(red: 0.76, green: 0.88, blue: 0.70)

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("P").font(.system(size: 19, weight: .medium, design: .serif))
                    .foregroundStyle(deep).frame(width: 28, height: 28)
                    .background(accent, in: RoundedRectangle(cornerRadius: 9))
                Text("Prompt Aid").font(.system(size: 15, weight: .semibold))
                Spacer()
                Text("REVIEW BEFORE RUNNING").font(.system(size: 10, weight: .semibold)).tracking(0.8).foregroundStyle(soft)
            }
            Divider().overlay(.white.opacity(0.12))
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(session.review.isPreparing ? "Preparing your review" : "Review your prompt").font(.system(size: 23, weight: .regular, design: .serif))
                        Text(session.review.isPreparing ? "The window is ready while Prompt Aid reviews your request." : "Compare both versions, then edit the suggestion if you like.").font(.system(size: 13)).foregroundStyle(soft)
                    }
                    HStack(alignment: .top, spacing: 12) {
                        promptPanel("Your draft", detail: "ORIGINAL", text: .constant(session.review.original), editable: false)
                        promptPanel("Suggested prompt", detail: session.review.isPreparing ? "PREPARING" : "EDITABLE", text: $session.draft, editable: !session.review.isPreparing)
                    }
                    if session.review.isPreparing { ProgressView().controlSize(.small) }
                    if session.review.projectRoot != nil && !session.review.isPreparing {
                        HStack {
                            Text("Local project context").font(.system(size: 12, weight: .semibold))
                            Spacer()
                            Button("Start / reconnect workspace") { session.startWorkspace() }.disabled(session.busy)
                        }
                    }
                    if session.connected && !session.review.isPreparing {
                        HStack {
                            Picker("Retrieval", selection: $session.method) {
                                Text("Lexical").tag("bm25")
                                Text("Hybrid").tag("hybrid")
                                Text("Semantic").tag("semantic")
                            }.frame(maxWidth: 220)
                            Toggle("Rerank", isOn: $session.useReranker)
                            Spacer()
                        }
                        HStack {
                            if !session.excluded.isEmpty { Button("Reset exclusions") { session.excluded = [] }.controlSize(.small) }
                            Button("Find context") { session.search() }.disabled(session.busy)
                            if session.busy { ProgressView().controlSize(.small); Button("Stop") { session.cancelOperation() } }
                            Spacer()
                        }
                        HStack {
                            Button("Verify sources") { session.verify() }.disabled(session.busy || session.sources.isEmpty)
                            Button("Insert selected context") { session.insertContext() }.disabled(session.busy || session.sources.isEmpty)
                            Spacer()
                            Button("Save review") { session.save() }.disabled(session.busy || session.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || session.draft.count > 16000)
                            Button("History") { session.loadHistory() }.disabled(session.busy)
                        }.controlSize(.small)
                        if session.savedID != nil {
                            HStack {
                                Text("Rate saved review:").font(.system(size: 11)).foregroundStyle(soft)
                                Button("Useful") { session.feedback("accepted") }
                                Button("Not useful") { session.feedback("rejected") }
                            }.controlSize(.small).disabled(session.busy)
                        }
                        if !session.history.isEmpty {
                            DisclosureGroup("Saved reviews (local)") {
                                ForEach(session.history) { item in
                                    Button(item.title) { session.restore(item) }.buttonStyle(.plain).frame(maxWidth: .infinity, alignment: .leading).disabled(session.busy).lineLimit(1)
                                }
                            }.font(.system(size: 11))
                        }
                    }
                    if !session.status.isEmpty { Text(session.status).font(.system(size: 11)).foregroundStyle(soft).textSelection(.enabled) }
                    if !session.sources.isEmpty {
                        DisclosureGroup("Source evidence (\(session.sources.count))") {
                            ForEach(session.sources) { source in
                                sourceCard(source)
                            }
                        }.font(.system(size: 12))
                    }
                    HStack {
                        Text("Review notes").font(.system(size: 13, weight: .semibold))
                        Spacer()
                        Text("Sources reported by Prompt Aid").font(.system(size: 11)).foregroundStyle(soft)
                    }.padding(.top, 4)
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 9) {
                            notes("Context used", session.review.evidence?.isEmpty == false ? session.review.evidence : ["No sources listed in this review."])
                            notes("What changed", session.review.changes)
                            notes("Assumptions — not verified facts", session.assumptions)
                        }.frame(maxWidth: .infinity, alignment: .topLeading)
                        VStack(alignment: .leading, spacing: 9) {
                            notes("Questions", session.review.questions)
                            notes("Limitations", session.review.limitations)
                        }.frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider().overlay(.white.opacity(0.12))
            HStack(spacing: 12) {
                Text("Runs in this Codex chat.")
                    .font(.system(size: 11)).foregroundStyle(soft)
                Spacer(minLength: 5)
                Button("Cancel") { session.finish("cancel") }.keyboardShortcut(.cancelAction)
                    .buttonStyle(.bordered)
                Button("Run with Codex →") { session.finish("run") }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(accent)
                    .disabled(session.review.isPreparing || session.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || session.draft.count > 16000)
            }.controlSize(.large)
        }
        .padding(15)
        .foregroundStyle(Color.white.opacity(0.94))
        .background(deep)
        .frame(minWidth: 560, minHeight: 400)
    }
    func sourceCard(_ source: SourceEvidence) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Toggle(isOn: Binding(get: { !session.excluded.contains(source.path) }, set: { included in
                    if included { session.excluded.remove(source.path) } else { session.excluded.insert(source.path) }
                })) { Text("\(source.path):\(source.lineStart)-\(source.lineEnd)").font(.system(size: 11, design: .monospaced)) }
                Spacer()
                Text(source.status == "verified" ? "Source text verified" : source.status == "stale" ? "Source changed" : "Unverified / unavailable")
                    .font(.system(size: 10)).foregroundStyle(soft)
            }
            DisclosureGroup("View excerpt") {
                ScrollView { Text(source.excerpt).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth:.infinity, alignment:.leading) }.frame(maxHeight:160)
                if source.excerptTruncated == true { Text("Excerpt truncated.").font(.system(size:10)) }
                Text("SHA-256: " + source.contentHash).font(.system(size: 9, design: .monospaced)).textSelection(.enabled)
            }
            if let claim = source.claim { Text("Model interpretation (unverified): " + claim).font(.system(size: 11)).foregroundStyle(soft) }
        }.padding(8).background(panel, in: RoundedRectangle(cornerRadius:6))
    }
    func promptPanel(_ label: String, detail: String, text: Binding<String>, editable: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(label).font(.system(size: 12, weight: .semibold))
                Spacer(minLength: 2)
                Text(detail).font(.system(size: 9, weight: .semibold)).tracking(0.5).foregroundStyle(soft)
            }
            Group {
                if editable {
                    TextEditor(text: text)
                        .font(.system(size: 13)).scrollContentBackground(.hidden)
                        .foregroundStyle(.white)
                        .accessibilityLabel("Suggested prompt, editable")
                } else {
                    ScrollView {
                        Text(text.wrappedValue)
                            .font(.system(size: 13)).foregroundStyle(soft)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }.accessibilityLabel("Original prompt")
                }
            }
            .padding(7)
            .background(deep.opacity(0.65), in: RoundedRectangle(cornerRadius: 6))
            .frame(height: 125)
        }
        .padding(12)
        .background(panel, in: RoundedRectangle(cornerRadius: 9))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(editable ? accent.opacity(0.4) : .white.opacity(0.06), lineWidth: 1))
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

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let session: ReviewSession
    var window: NSWindow?
    init(session: ReviewSession) { self.session = session }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = ReviewView(session: session)
        // This switch lets a local layout check start the window at its minimum size.
        let minimumPreview = ProcessInfo.processInfo.environment["PROMPT_AID_TEST_MINIMUM"] == "1"
        let initialSize = minimumPreview ? NSSize(width: 560, height: 400) : NSSize(width: 900, height: 740)
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: initialSize), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Prompt Aid"
        window.contentViewController = NSHostingController(rootView: view)
        window.minSize = NSSize(width: 560, height: 400)
        window.setContentSize(initialSize)
        window.delegate = self
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        window.displayIfNeeded()
        DispatchQueue.main.async {
            LaunchMetrics.record("window_ready_ms")
            Task { await self.session.checkCapabilities() }
        }
        NSApp.activate(ignoringOtherApps: true)
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { session.finish("cancel"); return false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct PromptAidMain {
@MainActor static func main() {
if CommandLine.arguments.count == 1 || CommandLine.arguments.dropFirst().elementsEqual(["--build"]) {
    // Keep Build's UI/types out of the fast review executable entirely.
    let executable = URL(fileURLWithPath:CommandLine.arguments[0]).deletingLastPathComponent().appendingPathComponent("PromptAidBuild").path
    let first = strdup(executable)
    var args: [UnsafeMutablePointer<CChar>?] = [first,nil]
    let code = args.withUnsafeMutableBufferPointer { execv(executable,$0.baseAddress!) }
    free(first)
    fputs("Prompt Aid Build could not open (\(code)). Rebuild/reinstall the app.\n",stderr)
    exit(1)
}

LaunchMetrics.started = ProcessInfo.processInfo.systemUptime
LaunchMetrics.record("main_entered_ms")
do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "PromptAid", code: 1, userInfo: [NSLocalizedDescriptionKey: "Usage: PromptAid <review.json>"]) }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let review = try Review.read(url)
    let session = ReviewSession(review)
    session.watchReview(url)
    let delegate = AppDelegate(session: session)
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.delegate = delegate
    app.run()
} catch {
    fputs("Prompt Aid could not open: \(error.localizedDescription)\n", stderr)
    exit(1)
}

}
}
