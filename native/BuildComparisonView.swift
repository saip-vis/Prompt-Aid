import SwiftUI

struct SourceCasesView: View {
    let cases: [SourceCaseEvidence]
    var body: some View {
        DisclosureGroup("Source assertions · \(cases.filter(\.passed).count)/\(cases.count) passed") {
            ForEach(cases) { item in
                VStack(alignment:.leading,spacing:3) {
                    Text((item.passed ? "Passed · " : "Failed · ")+item.caseID).font(.caption).bold()
                    if !item.passed {
                        Text("Expected: "+(item.expected?.display ?? "unknown")).font(.caption)
                        Text("Actual: "+(item.actual?.display ?? "unknown")).font(.caption)
                    }
                    if let source = item.source { Text(source).font(.caption).foregroundStyle(.secondary) }
                }.textSelection(.enabled).padding(.vertical,4)
            }
        }
    }
}

@MainActor struct BuildComparisonView: View {
    @ObservedObject var session: BuildSession
    var body: some View {
        DisclosureGroup("Compare & replay recorded evidence") {
            VStack(alignment:.leading,spacing:10) {
                Picker("Baseline",selection:$session.comparisonBaselineID) {
                    Text("This run’s starting code").tag("")
                    ForEach(session.history.filter { $0.spec.root == session.job?.spec.root && $0.id != session.job?.id }) { record in
                        Text(record.spec.goal).lineLimit(1).tag(record.id)
                    }
                }
                if let comparison = session.comparison {
                    if let baseline = comparison.baseline { metrics(baseline,title:"Starting / baseline") }
                    if let result = comparison.result { metrics(result,title:"Latest recorded result") }
                    ForEach(Array(comparison.notes.enumerated()),id:\.offset) { _,note in Text(note).font(.caption).foregroundStyle(.secondary) }
                    if !comparison.replay.isEmpty {
                        Divider()
                        Text("Recorded replay · no model is running").font(.subheadline).bold()
                        Stepper("Step \(session.replayIndex+1) of \(comparison.replay.count)",value:$session.replayIndex,in:0...max(0,comparison.replay.count-1))
                        let entry = comparison.replay[min(session.replayIndex,comparison.replay.count-1)]
                        Text(entry.label).font(.subheadline)
                        if let output = entry.output { DisclosureGroup("Actual output · first 3 records preview") { Text(output).font(.system(.caption,design:.monospaced)).textSelection(.enabled) } }
                        ForEach(Array(entry.checks.enumerated()),id:\.offset) { _,check in
                            Text(check.title).font(.caption).bold()
                            if let cases = check.cases,!cases.isEmpty { SourceCasesView(cases:cases) }
                        }
                    }
                } else { Text("No recorded comparison loaded.").font(.caption).foregroundStyle(.secondary) }
                Button("Refresh recorded evidence") { Task { await session.loadComparison() } }
            }.padding(.top,5)
        }.onChange(of:session.comparisonBaselineID) { _ in Task { await session.loadComparison() } }
    }
    func metrics(_ entry: RecordedAttempt,title: String) -> some View {
        VStack(alignment:.leading,spacing:4) {
            Text(title+" · "+entry.label).font(.subheadline).bold()
            Text("\(entry.checksPassed)/\(entry.checksTotal) checks · \(entry.casesPassed)/\(entry.casesTotal) source assertions").font(.caption)
            if let duration = entry.elapsedMS { Text(String(format:"Phase duration: %.2f s",duration/1000)).font(.caption) }
            if let worker = entry.workerMS,worker>0 { Text(String(format:"Coding worker: %.2f s",worker/1000)).font(.caption) }
            Text("Cumulative input/output tokens: \(entry.usage["input_tokens"] ?? 0) / \(entry.usage["output_tokens"] ?? 0)").font(.caption)
            if let cached = entry.usage["cached_input_tokens"] { Text("Reported cached input tokens: \(cached)").font(.caption) }
        }
    }
}
