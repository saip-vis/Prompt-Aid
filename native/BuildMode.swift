import AppKit
import SwiftUI

@MainActor final class BuildSession: ObservableObject {
    @Published var roots: [String] = []; @Published var root = ""
    @Published var goal = ""; @Published var constraints = ""
    @Published var successCriteria = ""; @Published var showCriteria = false
    @Published var verificationNotes: [Int:String] = [:]; @Published var projectMemory = ""
    @Published var demo: CreatorDemo?;@Published var comparison: BuildComparison?
    @Published var comparisonBaselineID = "";@Published var replayIndex = 0
    @Published var checkKind = "command"; @Published var command = ""; @Published var filePath = ""; @Published var requiredText = ""
    @Published var answer = ""
    @Published var maxTurns = 3; @Published var minutes = 10; @Published var approved = false
    @Published var job: BuildRecord?; @Published var history: [BuildRecord] = []; @Published var events: [BuildEvent] = []
    @Published var diff = ""; @Published var status = "Connecting to the local workspace…"; @Published var busy = false
    @Published var workerAvailable = false
    @Published var suggestions: [SuggestedCheck] = []; @Published var selectedChecks: Set<String> = []
    @Published var useSuggestedChecks = true; @Published var loadingChecks = false
    @Published var checkNotice = ""; @Published var readinessMessage = ""; @Published var projectReady = false
    @Published var advanced = false; @Published var showConstraints = false
    private var client: ServiceClient?; private var poll: Task<Void,Never>?
    private var suggestionRequest = UUID()
    var active: Bool { guard let job else { return false }; return ["queued","preparing","preflight","working","checking","correcting","stopping"].contains(job.state) }
    var hasChecks: Bool { useSuggestedChecks ? suggestions.contains { selectedChecks.contains($0.id) } : (checkKind == "command" ? !command.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty : !filePath.isEmpty && (checkKind != "file_contains" || !requiredText.isEmpty)) }
    var canStart: Bool { approved && !busy && job == nil && !loadingChecks && projectReady && hasChecks && workerAvailable && !root.isEmpty && !goal.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty }
    func connect() async {
        do {
            client = try ServiceClient.configured()
            guard let client else { throw ServiceError.message("Set up the local workspace first. See docs/build-mode.md for the setup command.") }
            let config: BuildConfiguration = try await client.request("/builds/config")
            roots = config.roots; if !roots.contains(root) { root = roots.first ?? "" }; workerAvailable = config.workerAvailable
            demo = try? await client.request("/builds/demo")
            let saved: BuildList = try await client.request("/builds"); history = saved.builds
            status = workerAvailable ? "Describe what you want to build. We’ll suggest how to check it." : "Codex CLI is unavailable. Install it and sign in before starting."
            await findChecks()
        } catch { status = error.localizedDescription }
    }
    func changeProject(_ value: String) {
        if value == demo?.spec?.root { loadDemo();return }
        root = value; approved = false; useSuggestedChecks = true
        Task { await findChecks() }
    }
    func loadDemo() {
        guard !active,!busy,let spec = demo?.spec else { return }
        poll?.cancel();job = nil;events = [];diff = "";comparison = nil;verificationNotes = [:]
        root = spec.root;goal = spec.goal;constraints = spec.constraints.joined(separator:"\n")
        successCriteria = (spec.acceptanceCriteria ?? []).joined(separator:"\n");showCriteria = true
        maxTurns = spec.maxTurns;minutes = max(1,spec.maxSeconds/60);useSuggestedChecks = true;approved = false;advanced = false
        status = "Fictional creator-inbox demo. Starting code is deliberately flawed; approve to measure it and supervise a fix."
        Task { await findChecks() }
    }
    func newBuild() {
        guard !active,!busy else { return }
        poll?.cancel();job = nil;events = [];diff = "";answer = "";verificationNotes = [:];comparison = nil
        useSuggestedChecks = true;approved = false;advanced = false
        status = "Update the goal and choose checks for a new build."
        Task { await findChecks() }
    }
    func findChecks() async {
        guard let client,!root.isEmpty else { return }
        let project = root; let request = UUID(); suggestionRequest = request
        approved = false; loadingChecks = true; projectReady = false
        suggestions = []; selectedChecks = []; checkNotice = "";projectMemory = ""; readinessMessage = "Checking your project…"
        do {
            var query = URLComponents(); query.queryItems = [URLQueryItem(name:"root",value:project)]
            let result: CheckSuggestions = try await client.request("/builds/suggestions?"+(query.percentEncodedQuery ?? ""))
            guard root == project,suggestionRequest == request else { return }
            suggestions = result.suggestions
            // Start with one relevant suite; the user can add other project suites.
            let preferred = result.suggestions.first { $0.id == "python-tests" } ?? result.suggestions.first
            selectedChecks = Set(result.suggestions.contains { $0.check.kind == "creator_offer" } ? result.suggestions.map(\.id) : preferred.map { [$0.id] } ?? [])
            checkNotice = result.notices.joined(separator:"\n");projectReady = result.ready;readinessMessage = result.readinessMessage
            if let memory = result.environmentMemory {
                let checks = memory.results.preflight?.contains(where:{ $0.status == "blocked" }) == true ? memory.results.preflight ?? [] : memory.results.checks ?? memory.results.preflight ?? []
                projectMemory = checks.map { $0.label+": "+($0.status == "blocked" ? "couldn’t run last time" : $0.status == "passed" || $0.status == "ready" ? "worked last time" : "needs attention") }.joined(separator:"\n")
            }
            if suggestions.isEmpty { advanced = true }
        } catch {
            guard root == project,suggestionRequest == request else { return }
            checkNotice = "Couldn’t detect checks: "+error.localizedDescription
            readinessMessage = "Reconnect to check this project again."
        }
        if suggestionRequest == request { loadingChecks = false }
    }
    func start() {
        guard canStart else { return };busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                guard let client else { return }
                let checks: [CompletionCheck]
                if useSuggestedChecks { checks = suggestions.filter { selectedChecks.contains($0.id) }.map(\.check) }
                else {
                    let argv = checkKind == "command" ? try commandArguments(command) : []
                    checks = [CompletionCheck(kind:checkKind,label:checkKind == "command" ? "Custom check" : "Required file",argv:argv,path:checkKind == "command" ? nil : filePath,text:checkKind == "file_contains" ? requiredText : nil)]
                }
                let spec = BuildSpecification(root:root,goal:goal,constraints:constraints.split(separator:"\n").map(String.init),checks:checks,maxTurns:maxTurns,maxSeconds:minutes*60,approved:true,acceptanceCriteria:successCriteria.split(separator:"\n").map(String.init))
                let object = try JSONSerialization.jsonObject(with:JSONEncoder().encode(spec)) as! [String:Any]
                let created: BuildRecord = try await client.request("/builds",method:"POST",body:object)
                select(created); approved = false
            } catch { status = error.localizedDescription }
        }
    }
    func select(_ record: BuildRecord) {
        comparison = nil;comparisonBaselineID = "";replayIndex = 0
        poll?.cancel();root = record.spec.root;goal = record.spec.goal;constraints = record.spec.constraints.joined(separator:"\n")
        maxTurns = record.spec.maxTurns;minutes = max(1,record.spec.maxSeconds/60);approved = false;successCriteria = (record.spec.acceptanceCriteria ?? []).joined(separator:"\n");verificationNotes = [:]
        showCriteria = !successCriteria.isEmpty
        if let check = record.spec.checks.first { checkKind = check.kind;command = displayCommand(check.argv);filePath = check.path ?? "";requiredText = check.text ?? "" }
        useSuggestedChecks = false
        job = record;events = [];diff = "";status = record.payload.message
        poll = Task { @MainActor in
            while !Task.isCancelled {
                do {
                    try await refresh()
                    if !active { await loadDiff();await loadComparison();break }
                    try await Task.sleep(nanoseconds:500_000_000)
                } catch is CancellationError { return }
                catch {
                    status = "Connection interrupted. Retrying the local service… "+error.localizedDescription
                    try? await Task.sleep(nanoseconds:1_000_000_000)
                }
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
    func recheck() {
        guard let client,let id = job?.id,!active,!busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do { let value: BuildRecord = try await client.request("/builds/"+id+"/recheck",method:"POST",body:["approved":true,"max_seconds":180]);select(value) }
            catch { status = error.localizedDescription }
        }
    }
    func confirm(_ index: Int) {
        guard let client,let id = job?.id,!active,!busy,let note = verificationNotes[index],!note.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do { let value: BuildRecord = try await client.request("/builds/"+id+"/criteria/"+String(index)+"/confirm",method:"POST",body:["approved":true,"evidence":note]);guard job?.id == id else { return };job = value;status = value.payload.message }
            catch { status = error.localizedDescription }
        }
    }
    func loadComparison() async {
        guard let client,let id = job?.id else { return }
        let baseline = comparisonBaselineID
        comparison = nil
        do {
            var query = URLComponents();if !baseline.isEmpty { query.queryItems = [URLQueryItem(name:"baseline_id",value:baseline)] }
            let value: BuildComparison = try await client.request("/builds/"+id+"/comparison"+(query.percentEncodedQuery.map { "?"+$0 } ?? ""))
            guard job?.id == id,comparisonBaselineID == baseline,!Task.isCancelled else { return };comparison = value;replayIndex = max(0,value.replay.count-1)
        } catch { status = error.localizedDescription }
    }
}

@MainActor struct BuildView: View {
    @ObservedObject var session: BuildSession
    var body: some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                VStack(alignment:.leading,spacing:3) {
                    Text("Prompt Aid · Build").font(.system(size:23,weight:.semibold))
                    Text("Describe a change. Choose checks. Review the result.").foregroundStyle(.secondary)
                }
                Spacer()
                if session.demo?.spec != nil { Button("Creator-offer demo") { session.loadDemo() }.disabled(session.active || session.busy) }
                if session.active { Button("Stop build",role:.destructive) { session.stop() }.buttonStyle(.borderedProminent) }
                Button("Reconnect") { Task { await session.connect() } }.disabled(session.active)
            }
            Divider()
            HSplitView {
                BuildTaskForm(session:session)
                BuildResultsView(session:session)

            }
        }.padding(20).frame(minWidth:800,minHeight:650).task { await session.connect() }
        .onChange(of:session.goal) { _ in session.approved = false }
        .onChange(of:session.constraints) { _ in session.approved = false }
        .onChange(of:session.successCriteria) { _ in session.approved = false }
        .onChange(of:session.command) { _ in session.approved = false }
        .onChange(of:session.checkKind) { _ in session.approved = false }
        .onChange(of:session.filePath) { _ in session.approved = false }
        .onChange(of:session.requiredText) { _ in session.approved = false }
        .onChange(of:session.maxTurns) { _ in session.approved = false }
        .onChange(of:session.minutes) { _ in session.approved = false }
    }
}

@MainActor struct BuildTaskForm: View {
    @ObservedObject var session: BuildSession
    var body: some View {
VStack(alignment:.leading,spacing:10) {
                ScrollView {
                    VStack(alignment:.leading,spacing:12) {
                        projectSection
                        goalSection
                        checksSection
                        advancedSection
                    }.padding(8)
                }
                Divider()
                VStack(alignment:.leading,spacing:8) {
                    Text(session.readinessMessage).font(.caption).foregroundStyle(session.projectReady ? Color.secondary : Color.orange)
                    Button("Refresh project checks") { Task { await session.findChecks() } }.disabled(session.loadingChecks)
                    Text(session.useSuggestedChecks ? "Checks: "+session.suggestions.filter { session.selectedChecks.contains($0.id) }.map(\.title).joined(separator:", ") : "Check: Custom check").font(.caption).foregroundStyle(.secondary)
                    Toggle("I approve this goal, criteria and checks",isOn:$session.approved)
                    Button("Start building") { session.start() }.buttonStyle(.borderedProminent).disabled(!session.canStart)
                    Text("Review changes before applying them. Your original files stay untouched.").font(.caption).foregroundStyle(.secondary)
                }.padding(.horizontal,8)
                }.disabled(session.job != nil || session.busy).frame(minWidth:340,idealWidth:410)
    }
    @ViewBuilder var projectSection: some View {
                        Text("Project").font(.headline)
                        Picker("Project",selection:Binding(get:{ session.root },set:{ session.changeProject($0) })) {
                            ForEach(session.roots,id:\.self) { Text(URL(fileURLWithPath:$0).lastPathComponent).tag($0) }
                        }.labelsHidden()
                        Text(session.root).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
    }

    @ViewBuilder var goalSection: some View {
                        Text("What would you like to build?").font(.headline)
                        TextEditor(text:$session.goal).font(.body).frame(height:100).border(.secondary.opacity(0.25))
                            .accessibilityLabel("What would you like to build?")
                        DisclosureGroup("Anything to preserve or avoid? (optional)",isExpanded:$session.showConstraints) {
                            Text("One instruction per line, such as ‘Keep the current design’ or ‘Add no dependencies’.").font(.caption).foregroundStyle(.secondary)
                            TextEditor(text:$session.constraints).font(.body).frame(height:65).border(.secondary.opacity(0.25)).accessibilityLabel("Constraints")
                        }
                        DisclosureGroup("What should be true when finished? (optional)",isExpanded:$session.showCriteria) {
                            Text("One observable result per line. For a Copy button: ‘Copies the saved text’ and ‘Shows Copied’. You’ll confirm these after automated checks pass. Leave blank to review the goal as a whole.").font(.caption).foregroundStyle(.secondary)
                            TextEditor(text:$session.successCriteria).font(.body).frame(height:75).border(.secondary.opacity(0.25)).accessibilityLabel("Success criteria")
                        }
    }

    @ViewBuilder var checksSection: some View {
                        Divider()
                        Text("How we’ll check the changes").font(.headline)
                        if session.loadingChecks { ProgressView("Finding this project’s checks…") }
                        else {
                            Text("Choose the checks to run after each attempt. If one fails, the worker can try fixing it.").font(.caption).foregroundStyle(.secondary)
                            ForEach(session.suggestions) { suggestion in
                                VStack(alignment:.leading,spacing:4) {
                                    Toggle(suggestion.title,isOn:Binding(get:{ session.selectedChecks.contains(suggestion.id) },set:{ selected in
                                        if selected { session.selectedChecks.insert(suggestion.id) } else { session.selectedChecks.remove(suggestion.id) }
                                        session.approved = false
                                    })).disabled(!session.useSuggestedChecks)
                                    Text(suggestion.description).font(.caption).foregroundStyle(.secondary)
                                    DisclosureGroup(suggestion.check.kind == "creator_offer" ? "Show protected check" : "Show command") {
                                        Text(suggestion.checkExplanation).font(.system(.caption,design:.monospaced)).textSelection(.enabled)
                                        Text("Detected from "+suggestion.evidence).font(.caption).foregroundStyle(.secondary)
                                    }
                                }.padding(.vertical,3)
                            }
                            if !session.checkNotice.isEmpty { Text(session.checkNotice).font(.caption).foregroundStyle(.secondary) }
                            if !session.projectMemory.isEmpty { DisclosureGroup("Last checks for this project") { Text(session.projectMemory).font(.caption).foregroundStyle(.secondary) } }
                        }
    }

    @ViewBuilder var advancedSection: some View {
                        DisclosureGroup("Advanced options",isExpanded:$session.advanced) {
                            VStack(alignment:.leading,spacing:10) {
                                Toggle("Use my own check instead",isOn:Binding(get:{ !session.useSuggestedChecks },set:{ session.useSuggestedChecks = !$0;session.approved = false }))
                                if !session.useSuggestedChecks {
                                    Picker("Check",selection:$session.checkKind) { Text("Run a command").tag("command"); Text("File exists").tag("file_exists"); Text("File contains text").tag("file_contains") }
                                    if session.checkKind == "command" {
                                        TextField("Test command",text:$session.command)
                                        Text("Runs in the separate worktree. Quotes are supported; pipelines need an explicit shell.").font(.caption).foregroundStyle(.secondary)
                                    } else {
                                        TextField("Relative file path",text:$session.filePath)
                                        if session.checkKind == "file_contains" { TextField("Required text",text:$session.requiredText) }
                                    }
                                }
                                Stepper("Up to \(session.maxTurns) attempts",value:$session.maxTurns,in:1...5)
                                Stepper("\(session.minutes)-minute limit",value:$session.minutes,in:1...30)
                            }.padding(.top,5)
                        }
    }

}

@MainActor struct BuildResultsView: View {
    @ObservedObject var session: BuildSession
    var body: some View {
ScrollView {
                    VStack(alignment:.leading,spacing:12) {
                        HStack {
                            Text(session.job?.outcome?.title ?? session.job?.state.replacingOccurrences(of:"_",with:" ").capitalized ?? "Ready").font(.headline)
                            Spacer()
                            if session.active { ProgressView().controlSize(.small) }
                        }
                        Text(session.status).textSelection(.enabled)
                        if let outcome = session.job?.outcome, !session.active { Text(outcome.summary).font(.subheadline).textSelection(.enabled) }
                        if session.job != nil && !session.active {
                            Button("New build from this goal") { session.newBuild() }.disabled(session.busy)
                        }
                        if let job = session.job { BuildJobEvidenceView(session:session,job:job) }
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
}

@MainActor struct BuildJobEvidenceView: View {
    @ObservedObject var session: BuildSession
    let job: BuildRecord
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
                            Text("Worker turn \(job.payload.turn) of \(job.spec.maxTurns)").font(.caption).foregroundStyle(.secondary)
                            if let path = job.payload.worktree { Text(path).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
                            if !session.active { Button("Recheck only · no coding worker (up to 3 min)") { session.recheck() }.disabled(session.busy) }
                            if !session.active { BuildComparisonView(session:session) }
                            if let preflight = job.payload.preflight,!preflight.isEmpty {
                                DisclosureGroup("Environment checks") {
                                    ForEach(Array(preflight.enumerated()),id:\.offset) { _,item in
                                        Text(item.label+" · "+(item.status == "blocked" ? "Couldn’t start" : item.status == "not_probed" ? "Checked when run" : "Runtime ready")).font(.subheadline)
                                        if !item.reason.isEmpty { Text(item.reason).font(.caption) }
                                        if let details = item.details,!details.isEmpty { Text(details).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
                                    }
                                }
                            }
                            if !job.payload.checks.isEmpty { Text("Automated evidence").font(.headline) }
                            ForEach(Array(job.payload.checks.enumerated()),id:\.offset) { _,check in
                                VStack(alignment:.leading) {
                                    Text(check.title).font(.subheadline).bold()
                                    if let reason = check.reason,!reason.isEmpty { Text(reason).font(.caption).foregroundStyle(.secondary) }
                                    DisclosureGroup("Check output") { Text(check.details).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
                                    if let cases = check.cases,!cases.isEmpty { SourceCasesView(cases:cases) }
                                }
                            }
                            if let criteria = job.payload.criteria,!criteria.isEmpty {
                                Text("Requested behavior").font(.headline)
                                Text("Passing tests alone doesn’t prove the goal. Record what you actually checked; confirmation is attributed to you.").font(.caption).foregroundStyle(.secondary)
                                ForEach(Array(criteria.enumerated()),id:\.offset) { index,criterion in
                                    CriterionEvidenceRow(session:session,job:job,index:index,criterion:criterion)
                                }
                            }
                            if let summary = job.payload.workerSummary { DisclosureGroup("Worker report · not independent evidence") { Text(summary).font(.caption).textSelection(.enabled) } }

        }
    }
}

@MainActor struct CriterionEvidenceRow: View {
    @ObservedObject var session: BuildSession
    let job: BuildRecord
    let index: Int
    let criterion: CriterionEvidence
    var canConfirm: Bool { job.state == "needs_review" && job.payload.checkStamp != nil && criterion.status != "confirmed" && !job.payload.checks.isEmpty && job.payload.checks.allSatisfy(\.passed) }
    var body: some View {
        VStack(alignment:.leading,spacing:5) {
            Text((criterion.status == "confirmed" ? "Confirmed by you · " : "Needs review · ")+criterion.text).font(.subheadline).textSelection(.enabled)
            Text(criterion.evidence).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            if let linked = criterion.automatedEvidence {
                ForEach(Array(linked.enumerated()),id:\.offset) { _,check in Text(check.display).font(.caption).foregroundStyle(.secondary) }
            }
            if canConfirm {
                TextField("What did you test or observe?",text:Binding(get:{ session.verificationNotes[index] ?? "" },set:{ session.verificationNotes[index] = $0 }))
                Button("I checked this behavior") { session.confirm(index) }.disabled(session.busy || (session.verificationNotes[index] ?? "").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
            }
        }.padding(.vertical,4)
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
