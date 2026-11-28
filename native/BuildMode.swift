import AppKit
import SwiftUI

@MainActor final class BuildSession: ObservableObject {
    @Published var roots: [String] = []; @Published var root = ""
    @Published var goal = ""; @Published var constraints = ""
    @Published var checkKind = "command"; @Published var command = ""; @Published var filePath = ""; @Published var requiredText = ""
    @Published var answer = ""
    @Published var maxTurns = 3; @Published var minutes = 10; @Published var approved = false
    @Published var job: BuildRecord?; @Published var history: [BuildRecord] = []; @Published var events: [BuildEvent] = []
    @Published var diff = ""; @Published var status = "Connecting to the local workspace…"; @Published var busy = false
    @Published var workerAvailable = false
    private var client: ServiceClient?; private var poll: Task<Void,Never>?
    var active: Bool { guard let job else { return false }; return ["queued","preparing","working","checking","correcting","stopping"].contains(job.state) }
    var canStart: Bool { approved && !busy && !active && workerAvailable && !root.isEmpty && !goal.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && (checkKind == "command" ? !command.isEmpty : !filePath.isEmpty && (checkKind != "file_contains" || !requiredText.isEmpty)) }
    func connect() async {
        do {
            client = try ServiceClient.configured()
            guard let client else { throw ServiceError.message("Set up the local workspace first. See docs/build-mode.md for the setup command.") }
            let config: BuildConfiguration = try await client.request("/builds/config")
            roots = config.roots; if !roots.contains(root) { root = roots.first ?? "" }; workerAvailable = config.workerAvailable
            let saved: BuildList = try await client.request("/builds"); history = saved.builds
            status = workerAvailable ? "Ready. Describe the goal and how completion should be checked." : "Codex CLI is unavailable. Install it and sign in before starting."
        } catch { status = error.localizedDescription }
    }
    func start() {
        guard canStart else { return };busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                guard let client else { return }
                let argv = checkKind == "command" ? try commandArguments(command) : []
                let check = CompletionCheck(kind:checkKind,label:checkKind == "command" ? "Verification command" : "Required file",argv:argv,path:checkKind == "command" ? nil : filePath,text:checkKind == "file_contains" ? requiredText : nil)
                let spec = BuildSpecification(root:root,goal:goal,constraints:constraints.split(separator:"\n").map(String.init),checks:[check],maxTurns:maxTurns,maxSeconds:minutes*60,approved:true)
                let object = try JSONSerialization.jsonObject(with:JSONEncoder().encode(spec)) as! [String:Any]
                let created: BuildRecord = try await client.request("/builds",method:"POST",body:object)
                select(created); approved = false
            } catch { status = error.localizedDescription }
        }
    }
    func select(_ record: BuildRecord) {
        poll?.cancel();root = record.spec.root;goal = record.spec.goal;constraints = record.spec.constraints.joined(separator:"\n")
        maxTurns = record.spec.maxTurns;minutes = max(1,record.spec.maxSeconds/60);approved = false
        if let check = record.spec.checks.first { checkKind = check.kind;command = check.argv.map { $0.contains(" ") ? "\""+$0+"\"" : $0 }.joined(separator:" ");filePath = check.path ?? "";requiredText = check.text ?? "" }
        job = record;events = [];diff = "";status = record.payload.message
        poll = Task { @MainActor in
            while !Task.isCancelled {
                do {
                    try await refresh()
                    if !active { await loadDiff(); break }
                    try await Task.sleep(nanoseconds:500_000_000)
                } catch is CancellationError { return }
                catch { status = error.localizedDescription; return }
            }
        }
    }
    func refresh() async throws {
        guard let client,let id = job?.id else { return }
        let value: BuildRecord = try await client.request("/builds/"+id)
        let after = events.last?.seq ?? 0
        let updates: BuildEvents = try await client.request("/builds/"+id+"/events?after="+String(after))
        try Task.checkCancellation()
        guard job?.id == id else { return }
        job = value; events.append(contentsOf:updates.events); if events.count>200 { events.removeFirst(events.count-200) };status = value.payload.message
    }
    func stop() {
        guard let client,let id = job?.id,active else { return }
        Task { @MainActor in
            do { let value: BuildRecord = try await client.request("/builds/"+id+"/stop",method:"POST",body:[:]);guard job?.id == id else { return };job = value;status = value.payload.message }
            catch { status = error.localizedDescription }
        }
    }
    func resume() {
        guard let client,let id = job?.id,!answer.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                let value: BuildRecord = try await client.request("/builds/"+id+"/resume",method:"POST",body:["answer":answer,"max_seconds":minutes*60,"approved":true])
                answer = "";select(value)
            } catch { status = error.localizedDescription }
        }
    }
    func loadDiff() async {
        guard let client,let id = job?.id else { return }
        do { let result: BuildDiff = try await client.request("/builds/"+id+"/diff");try Task.checkCancellation();guard job?.id == id else { return };diff = result.diff }
        catch { status = error.localizedDescription }
    }
}

@MainActor struct BuildView: View {
    @ObservedObject var session: BuildSession
    var body: some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                VStack(alignment:.leading,spacing:3) {
                    Text("Prompt Aid · Build").font(.system(size:23,weight:.semibold))
                    Text("Approve a goal. Follow the evidence. Review the changes.").foregroundStyle(.secondary)
                }
                Spacer()
                if session.active { Button("Stop build",role:.destructive) { session.stop() }.buttonStyle(.borderedProminent) }
                Button("Reconnect") { Task { await session.connect() } }.disabled(session.active)
            }
            Divider()
            HSplitView {
                ScrollView {
                    VStack(alignment:.leading,spacing:12) {
                        Text("Project").font(.headline)
                        Picker("Project",selection:$session.root) { ForEach(session.roots,id:\.self) { Text($0).tag($0) } }.labelsHidden()
                        Text("Goal").font(.headline)
                        TextEditor(text:$session.goal).font(.body).frame(height:100).border(.secondary.opacity(0.25))
                        Text("Constraints · one per line").font(.headline)
                        TextEditor(text:$session.constraints).font(.body).frame(height:65).border(.secondary.opacity(0.25))
                        Text("Completion check").font(.headline)
                        Picker("Check",selection:$session.checkKind) { Text("Run tests / command").tag("command"); Text("File exists").tag("file_exists"); Text("File contains text").tag("file_contains") }.labelsHidden()
                        if session.checkKind == "command" {
                            TextField("e.g. python3 -m unittest discover",text:$session.command)
                            Text("Runs in the isolated worktree. Quotes are supported; pipelines need an explicit shell.").font(.caption).foregroundStyle(.secondary)
                        } else {
                            TextField("Relative file path",text:$session.filePath)
                            if session.checkKind == "file_contains" { TextField("Required literal text",text:$session.requiredText) }
                        }
                        HStack { Stepper("Up to \(session.maxTurns) worker turns",value:$session.maxTurns,in:1...5);Spacer() }
                        HStack { Stepper("\(session.minutes)-minute limit",value:$session.minutes,in:1...30);Spacer() }
                        Text("Starts from a clean Git checkpoint in a separate worktree. Checks run automatically. Changes are retained for review and are never merged automatically.").font(.caption).foregroundStyle(.secondary)
                        Toggle("I approve this goal, constraints and completion check",isOn:$session.approved)
                        Button("Approve & start build") { session.start() }.buttonStyle(.borderedProminent).disabled(!session.canStart)
                        Text("For a quick prompt review, use $prompt-aid in your assistant.").font(.caption).foregroundStyle(.secondary)
                    }.padding(8).disabled(session.active || session.busy)
                }.frame(minWidth:340,idealWidth:410)
                ScrollView {
                    VStack(alignment:.leading,spacing:12) {
                        HStack {
                            Text(session.job?.state.replacingOccurrences(of:"_",with:" ").capitalized ?? "Ready").font(.headline)
                            Spacer()
                            if session.active { ProgressView().controlSize(.small) }
                        }
                        Text(session.status).textSelection(.enabled)
                        if let job = session.job {
                            Text("Worker turn \(job.payload.turn) of \(job.spec.maxTurns)").font(.caption).foregroundStyle(.secondary)
                            if let path = job.payload.worktree { Text(path).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
                            ForEach(Array(job.payload.checks.enumerated()),id:\.offset) { _,check in
                                VStack(alignment:.leading) {
                                    Text((check.passed ? "Passed · " : "Failed · ")+check.label).font(.subheadline).bold()
                                    DisclosureGroup("Check output") { Text(check.details).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
                                }
                            }
                        }
                        if let job = session.job,job.state == "needs_input",job.payload.turn < job.spec.maxTurns {
                            TextField("Your clarification",text:$session.answer)
                            Button("Approve answer & continue (up to \(session.minutes) min)") { session.resume() }.disabled(session.busy || session.answer.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                        }
                        if !session.events.isEmpty {
                            DisclosureGroup("Progress events (\(session.events.count))") {
                                ForEach(session.events) { event in
                                    VStack(alignment:.leading,spacing:2) { Text(event.kind).font(.caption).foregroundStyle(.secondary);Text(event.summary).font(.system(.caption,design:.monospaced)).textSelection(.enabled).lineLimit(8) }.padding(.vertical,4)
                                }
                            }
                        }
                        if !session.diff.isEmpty {
                            DisclosureGroup("Review changes") { Text(session.diff).font(.system(.caption,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading) }
                        }
                        if !session.history.isEmpty {
                            DisclosureGroup("Previous builds") {
                                ForEach(session.history.filter { $0.spec.root == session.root }) { job in Button(job.spec.goal) { session.select(job) }.buttonStyle(.plain).lineLimit(2).disabled(session.active || session.busy).padding(.vertical,3) }
                            }
                        }
                    }.padding(8).frame(maxWidth:.infinity,alignment:.leading)
                }.frame(minWidth:350)
            }
        }.padding(20).frame(minWidth:800,minHeight:650).task { await session.connect() }
    }
}

@MainActor final class BuildAppDelegate: NSObject,NSApplicationDelegate,NSWindowDelegate {
    let session = BuildSession();var window: NSWindow?
    func applicationDidFinishLaunching(_ notification:Notification) {
        installEditingMenu()
        let window = NSWindow(contentRect:NSRect(x:0,y:0,width:1000,height:800),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "Prompt Aid · Build";window.contentViewController = NSHostingController(rootView:BuildView(session:session));window.minSize = NSSize(width:800,height:650);window.delegate = self;window.center();window.makeKeyAndOrderFront(nil);self.window = window;NSApp.activate(ignoringOtherApps:true)
    }
    func windowShouldClose(_ sender:NSWindow)->Bool {
        if session.active { session.status = "Use Stop build before closing this active session.";return false }
        NSApp.terminate(nil);return true
    }
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        guard session.active else { return .terminateNow }
        session.stop()
        Task { @MainActor in
            for _ in 0..<30 {
                try? await Task.sleep(nanoseconds:250_000_000)
                try? await session.refresh()
                if !session.active { sender.reply(toApplicationShouldTerminate:true);return }
            }
            session.status = "Could not confirm Stop. Check the local service before quitting."
            sender.reply(toApplicationShouldTerminate:false)
        }
        return .terminateLater
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
}
