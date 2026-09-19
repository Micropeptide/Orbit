import SwiftUI

/// One of Claude Code's background tasks, as its task list shows it: a shell's output as
/// it grows, or a subagent's steps and words, kept current while it runs.
struct TaskOutput: Decodable {
    var kind: String?
    var status: String?
    var command: String?
    var output: String
    var summary: String?
    var since: Double?
    var ended: Double?
    var tools: Int?
    var tokens: Int?
    var chatSaved: Bool

    var running: Bool { ["running", "pending"].contains((status ?? "").lowercased()) }

    enum CodingKeys: String, CodingKey { case kind, status, command, output, summary, since, ended, tools, tokens, chat_saved }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        kind = c.lenientString(.kind)
        status = c.lenientString(.status)
        command = c.lenientString(.command)
        output = c.lenientString(.output) ?? ""
        summary = c.lenientString(.summary)
        since = c.lenientDouble(.since)
        ended = c.lenientDouble(.ended)
        tools = c.lenientDouble(.tools).map { Int($0) }
        tokens = c.lenientDouble(.tokens).map { Int($0) }
        chatSaved = c.lenientBool(.chat_saved) ?? false
    }
}

extension OrbitServer {
    func taskOutput(sid: String, id: String) async throws -> TaskOutput {
        let data = try await settingsCall("/api/tasks/output?sid=\(OrbitServer.escaped(sid))&id=\(OrbitServer.escaped(id))")
        do { return try JSONDecoder().decode(TaskOutput.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }
}

struct TaskOutputSheet: View {
    let task: BackgroundTask
    var onOpenChat: (String) -> Void = { _ in }
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var got: TaskOutput?
    @State private var failed: String?

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if let d = got {
                            Text(headline(d)).font(.caption).foregroundStyle(.secondary)
                            if let cmd = d.command, !cmd.isEmpty {
                                Text("$ " + cmd).font(.footnote.monospaced()).textSelection(.enabled)
                            }
                            Text(d.output.isEmpty ? (d.summary ?? (d.running ? "(nothing written yet)" : "(no output)")) : d.output)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(10)
                                .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 9))
                            if let s = d.summary, !s.isEmpty, !d.output.isEmpty {
                                Text("Reported: " + s).font(.footnote).foregroundStyle(.secondary)
                            }
                            Color.clear.frame(height: 1).id("end")
                        } else if let failed {
                            Label(failed, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                        } else {
                            ProgressView()
                        }
                    }
                    .padding()
                }
                .onChange(of: got?.output.count) { _, _ in
                    if got?.running == true { proxy.scrollTo("end", anchor: .bottom) }
                }
            }
            .navigationTitle(task.title.isEmpty ? "Background task" : task.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .primaryAction) {
                    if let out = got?.output, !out.isEmpty {
                        Button { UIPasteboard.general.string = out; Haptics.tap() } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .accessibilityLabel("Copy the output")
                    }
                    if let sid = task.sid, got?.chatSaved == true {
                        Button("Chat") { dismiss(); onOpenChat(sid) }
                    }
                }
            }
            .task { await poll() }
        }
    }

    private func headline(_ d: TaskOutput) -> String {
        var parts = [d.kind == "agent" ? "subagent" : "shell", d.running ? "running" : (d.status ?? "ended")]
        if let since = d.since {
            let end = d.ended ?? Date.now.timeIntervalSince1970
            parts.append((d.running ? "for " : "took ") + BackgroundTask.duration(end - since))
        }
        if let t = d.tools, t > 0 { parts.append(ToolText.plural(t, "tool use", "tool uses")) }
        if let k = d.tokens, k > 0 { parts.append(HomeDashboard.tokens(k) + " tokens") }
        return parts.joined(separator: " · ")
    }

    private func poll() async {
        while !Task.isCancelled {
            guard let server = state.server else { return }
            do {
                got = try await server.taskOutput(sid: task.sid ?? "", id: task.rawID)
                failed = nil
                if got?.running == false { return }
            } catch {
                if got == nil { failed = "Its output is no longer available." }
                return
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }
}
