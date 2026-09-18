import SwiftUI

/// Every DOI in an answer, checked against Crossref — the model has invented
/// references before.
struct CitationsSheet: View {
    let text: String
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var rows: [CitationRow]?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if let error {
                    Text(error).foregroundStyle(.red)
                } else if let rows {
                    if rows.isEmpty {
                        ContentUnavailableView("No DOIs in this answer", systemImage: "doc.text.magnifyingglass")
                    }
                    ForEach(rows) { r in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: r.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                                .foregroundStyle(r.ok ? .green : .red)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(r.doi).font(.callout.monospaced()).textSelection(.enabled)
                                Text(r.ok ? (r.title ?? "resolves") : (r.why ?? "does not resolve"))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .contextMenu {
                            if let url = URL(string: "https://doi.org/\(r.doi)") {
                                Link(destination: url) { Label("Open", systemImage: "safari") }
                            }
                            Button { UIPasteboard.general.string = r.doi } label: {
                                Label("Copy DOI", systemImage: "doc.on.doc")
                            }
                        }
                    }
                } else {
                    HStack(spacing: 8) {
                        ProgressView()
                        Text("Checking with Crossref…").foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Citations")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                guard let server = state.server else { return }
                do { rows = try await server.checkCitations(text) }
                catch { self.error = error.localizedDescription }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// The files one answer changed: undo them all, or put back an earlier saved
/// version of any one.
struct UndoChangesSheet: View {
    let message: Message
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var done: [String]?
    @State private var busy = false
    @State private var confirm = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(message.changes ?? [], id: \.self) { path in
                        NavigationLink {
                            CheckpointsView(path: path)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text((path as NSString).lastPathComponent)
                                Text(path).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                                    .truncationMode(.head)
                            }
                        }
                    }
                } header: {
                    Text("Changed by this answer")
                } footer: {
                    Text("Tap a file for its earlier saved versions.")
                }
                if let done {
                    Section("Done") {
                        ForEach(done, id: \.self) { Text($0).font(.footnote) }
                    }
                } else {
                    Section {
                        Button(role: .destructive) { confirm = true } label: {
                            HStack {
                                Label("Undo these changes", systemImage: "arrow.uturn.backward")
                                if busy { Spacer(); ProgressView() }
                            }
                        }
                        .disabled(busy || message.undoableChanges.isEmpty)
                    } footer: {
                        Text("Edited files go back to how they were before this answer; files it created go to the bin. Each restore is itself saved, so this can be undone too.")
                    }
                }
            }
            .navigationTitle("File changes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog("Put back the files this answer changed?", isPresented: $confirm,
                                titleVisibility: .visible) {
                Button("Undo changes", role: .destructive) {
                    busy = true
                    Task {
                        done = await state.undoChanges(of: message)
                        busy = false
                    }
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}

/// Earlier versions of one file, kept each time it was overwritten.
struct CheckpointsView: View {
    let path: String
    @EnvironmentObject var state: AppState
    @State private var names: [String]?
    @State private var restoring: String?
    @State private var note: String?

    var body: some View {
        List {
            if let note { Text(note).font(.footnote) }
            if let names {
                if names.isEmpty {
                    Text("No earlier versions saved — one is kept each time a file in the workspace or a project folder is overwritten.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(names, id: \.self) { n in
                    HStack {
                        Text(Self.label(n)).font(.callout.monospacedDigit())
                        Spacer()
                        Button("Restore") { restoring = n }.buttonStyle(.bordered)
                    }
                }
            } else {
                ProgressView()
            }
        }
        .navigationTitle((path as NSString).lastPathComponent)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .confirmationDialog("Replace the current file with this version?",
                            isPresented: Binding(get: { restoring != nil }, set: { if !$0 { restoring = nil } }),
                            titleVisibility: .visible) {
            Button("Restore", role: .destructive) {
                guard let n = restoring, let server = state.server else { return }
                Task {
                    do { note = try await server.restoreCheckpoint(rel: path, name: n) }
                    catch { note = error.localizedDescription }
                    await load()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The current version is saved first, so this can be undone too.")
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        names = (try? await server.checkpoints(rel: path)) ?? []
    }

    /// 20260917-142501.bak → 2026-09-17 14:25:01
    static func label(_ name: String) -> String {
        let s = name.replacingOccurrences(of: ".bak", with: "")
        let c = Array(s)
        guard c.count >= 15, c[8] == "-" else { return s }
        let d = String(c[0..<4]) + "-" + String(c[4..<6]) + "-" + String(c[6..<8])
        let t = String(c[9..<11]) + ":" + String(c[11..<13]) + ":" + String(c[13..<15])
        return d + " " + t + (c.count > 15 ? String(c[15...]) : "")
    }
}

/// Pick one of your own messages and land on it.
struct JumpSheet: View {
    let messages: [Message]
    var pick: (Int) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var filter = ""

    private var rows: [(row: Int, n: Int, text: String)] {
        var n = 0
        var out: [(Int, Int, String)] = []
        for (i, m) in messages.enumerated() where m.isUser {
            n += 1
            let t = m.text.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
            out.append((i, n, t.isEmpty ? "(image)" : String(t.prefix(140))))
        }
        let q = filter.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? out : out.filter { $0.2.lowercased().contains(q) }
    }

    var body: some View {
        NavigationStack {
            List {
                if rows.isEmpty {
                    Text(messages.contains(where: \.isUser) ? "Nothing matches" : "Nothing of yours in this chat yet")
                        .foregroundStyle(.secondary)
                }
                ForEach(rows.reversed(), id: \.row) { r in
                    Button {
                        pick(r.row)
                        dismiss()
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("#\(r.n)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Text(r.text).lineLimit(2).foregroundStyle(.primary)
                        }
                    }
                }
            }
            .searchable(text: $filter, placement: .navigationBarDrawer(displayMode: .always),
                        prompt: "Your messages")
            .navigationTitle("Jump to a message")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Answers, tokens and time: this chat, all time, and by model, tool and day.
struct UsageStatsView: View {
    var sid: String?
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var days = 7
    @State private var stats: UsageStats?
    @State private var ledger: (chat: LedgerSummary, all: LedgerSummary)?
    @State private var error: String?

    private static let periods = [(1, "Last day"), (7, "Last 7 days"), (30, "Last 30 days"), (36500, "All time")]

    var body: some View {
        NavigationStack {
            List {
                if let error { Text(error).foregroundStyle(.red) }
                if let l = ledger {
                    if sid != nil {
                        Section("This chat") { ledgerRow(l.chat) }
                    }
                    Section("Everything, all time") { ledgerRow(l.all) }
                }
                Section {
                    Picker("Period", selection: $days) {
                        ForEach(Self.periods, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    if let s = stats {
                        let tot = s.models.values.reduce((p: 0, c: 0, s: 0.0)) {
                            ($0.p + $1.prompt_tokens, $0.c + $1.completion_tokens, $0.s + $1.seconds)
                        }
                        LabeledContent("Turns", value: s.turns.formatted())
                        LabeledContent("Tokens", value: "\((tot.p + tot.c).formatted()) · \(tot.c.formatted()) out")
                        LabeledContent("Model time", value: Message.duration(tot.s))
                    } else if error == nil {
                        ProgressView()
                    }
                }
                if let s = stats {
                    Section("By model") {
                        if s.models.isEmpty { Text("Nothing in this period").foregroundStyle(.secondary) }
                        ForEach(s.models.sorted { $0.value.turns > $1.value.turns }, id: \.key) { k, m in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(k).font(.callout.weight(.medium))
                                Text(modelLine(m)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if !s.tools.isEmpty {
                        Section("Top tools") {
                            ForEach(s.tools.sorted { $0.value > $1.value }.prefix(15), id: \.key) { k, v in
                                LabeledContent(k, value: v.formatted())
                            }
                        }
                    }
                    if !s.by_day.isEmpty {
                        Section("By day") {
                            ForEach(s.by_day.sorted { $0.key > $1.key }, id: \.key) { k, v in
                                LabeledContent(k, value: "\(v.turns) turns · \(v.tokens.formatted()) tok")
                            }
                        }
                    }
                }
            }
            .navigationTitle("Usage")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task(id: days) { await load() }
        }
    }

    private func ledgerRow(_ l: LedgerSummary) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(l.turns) turns · \(l.completion_tokens.formatted()) output tokens")
            Text("\(Message.duration(l.seconds)) · \(String(format: "%.1f", l.tok_per_s)) tok/s")
                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
    }

    private func modelLine(_ m: UsageStats.ModelRow) -> String {
        var s = "\(m.turns) turns · \(m.prompt_tokens.formatted()) in · \(m.completion_tokens.formatted()) out · \(Message.duration(m.seconds))"
        if m.seconds > 0, m.completion_tokens > 0 {
            s += String(format: " · %.1f tok/s", Double(m.completion_tokens) / m.seconds)
        }
        return s
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            stats = try await server.usageStats(days: days)
            if ledger == nil { ledger = try await server.ledger(sid: sid) }
            error = nil
        } catch { self.error = "Couldn't load usage. \(error.localizedDescription)" }
    }
}
