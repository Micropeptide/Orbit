import SwiftUI

/// Go back to just before one of your messages: the chat only, or the files
/// later answers changed too.
struct RewindSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var busy = false
    @State private var confirming: (index: Int, files: Bool, text: String)?

    private struct Point: Identifiable {
        var index: Int          // among your messages, as the Mac counts
        var text: String
        var files: Int          // later answers with file changes that can still go back
        var id: Int { index }
    }

    private var points: [Point] {
        var out: [Point] = []
        var n = 0
        for (i, m) in state.messages.enumerated() where m.isUser {
            let later = state.messages[(i + 1)...].filter { !$0.isUser && !$0.undoableChanges.isEmpty }.count
            let t = m.bang.map { "! " + $0.cmd } ?? m.text
            out.append(Point(index: n, text: t.split(whereSeparator: \.isWhitespace).joined(separator: " "), files: later))
            n += 1
        }
        return out.reversed()
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if points.isEmpty {
                        Text("Nothing to rewind to yet").foregroundStyle(.secondary)
                    }
                    ForEach(points) { p in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(p.text.isEmpty ? "(no text)" : String(p.text.prefix(160)))
                                .lineLimit(3)
                            HStack(spacing: 8) {
                                Button("Chat only") { confirming = (p.index, false, p.text) }
                                    .buttonStyle(.bordered)
                                if p.files > 0 {
                                    Button("Chat + files") { confirming = (p.index, true, p.text) }
                                        .buttonStyle(.bordered)
                                        .tint(.orange)
                                }
                            }
                            .font(.caption)
                            .disabled(busy || state.streaming)
                        }
                        .padding(.vertical, 3)
                    }
                } footer: {
                    Text("Puts the chat back to just before that message. Chat + files also puts back the files the answers after it changed.")
                }
            }
            .navigationTitle("Rewind")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .confirmationDialog("Rewind to before this message?",
                                isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
                                titleVisibility: .visible) {
                Button(confirming?.files == true ? "Rewind chat and files" : "Rewind chat", role: .destructive) {
                    guard let c = confirming else { return }
                    busy = true
                    Task {
                        if await state.rewind(toUserIndex: c.index, files: c.files) { dismiss() }
                        busy = false
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Everything from “\(String(confirming?.text.prefix(60) ?? ""))” on is removed.")
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Claude Code's /context: the window as a grid of squares, one colour per part.
struct ContextSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let sid: String
    @State private var detail: ContextDetail?
    @State private var error: String?

    private static let colours: [Color] = [.accentColor, .orange, .purple, .green, .yellow, .red, .gray]

    var body: some View {
        NavigationStack {
            List {
                if let error { Text(error).foregroundStyle(.red) }
                if let d = detail {
                    let max = Swift.max(d.max, 1)
                    Section {
                        Text(summary(d)).font(.footnote).foregroundStyle(.secondary)
                        grid(d, max: max)
                            .padding(.vertical, 4)
                    }
                    Section {
                        ForEach(Array(d.parts.enumerated()), id: \.offset) { i, p in
                            legend(Self.colours[i % Self.colours.count], p.name, p.tokens, max: max)
                        }
                        legend(Color.secondary.opacity(0.25), "free", d.free, max: max)
                    } footer: {
                        Text("\(d.messages) message\(d.messages == 1 ? "" : "s")"
                             + (d.images > 0 ? " · \(d.images) image\(d.images == 1 ? "" : "s")" : ""))
                    }
                    Section {
                        Button {
                            dismiss()
                            Task { await state.compactCurrent() }
                        } label: {
                            Label("Compact now", systemImage: "arrow.down.right.and.arrow.up.left")
                        }
                        .disabled(state.streaming)
                    }
                } else if error == nil {
                    ProgressView()
                }
            }
            .navigationTitle("Context window")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                guard let server = state.server else { return }
                do { detail = try await server.context(sid: sid) }
                catch { self.error = "Couldn't read the context. \(error.localizedDescription)" }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func summary(_ d: ContextDetail) -> String {
        let pct = Int((100 * Double(d.used) / Double(Swift.max(d.max, 1))).rounded())
        var s = "\(pct)% used — \(d.used.formatted()) of \(d.max.formatted()) tokens, \(d.free.formatted()) free "
        s += d.basis == "measured" ? "(measured)." : "(estimated)."
        if let a = d.autocompactAt { s += " Orbit compacts by itself at \(Int(a))%." }
        return s
    }

    /// 100 squares, each one per cent of the window.
    private func grid(_ d: ContextDetail, max: Int) -> some View {
        var cells: [Color] = []
        for (i, p) in d.parts.enumerated() {
            let n = Int((100 * Double(p.tokens) / Double(max)).rounded())
            for _ in 0..<n where cells.count < 100 { cells.append(Self.colours[i % Self.colours.count]) }
        }
        while cells.count < 100 { cells.append(Color.secondary.opacity(0.25)) }
        return VStack(spacing: 3) {
            ForEach(0..<10, id: \.self) { r in
                HStack(spacing: 3) {
                    ForEach(0..<10, id: \.self) { c in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(cells[r * 10 + c])
                            .aspectRatio(1, contentMode: .fit)
                    }
                }
            }
        }
        .frame(maxWidth: 260)
        .frame(maxWidth: .infinity)
        .accessibilityElement()
        .accessibilityLabel("Context grid")
    }

    private func legend(_ colour: Color, _ name: String, _ tokens: Int, max: Int) -> some View {
        HStack(spacing: 9) {
            RoundedRectangle(cornerRadius: 2).fill(colour).frame(width: 12, height: 12)
            Text(name)
            Spacer()
            Text("\(tokens.formatted()) · \(Int((100 * Double(tokens) / Double(max)).rounded()))%")
                .font(.callout.monospacedDigit()).foregroundStyle(.secondary)
        }
    }
}

/// /diff: every file change shown in this chat, newest first.
struct DiffsSheet: View {
    let diffs: [ShownDiff]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if diffs.isEmpty {
                    ContentUnavailableView("No file changes yet", systemImage: "doc.badge.plus",
                                           description: Text("Edits an answer makes while you watch it here are listed."))
                }
                ForEach(diffs.reversed()) { d in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 8) {
                            Text((d.path as NSString).lastPathComponent).font(.callout.weight(.semibold))
                            Text("+\(d.added)").foregroundStyle(.green)
                            Text("−\(d.removed)").foregroundStyle(.red)
                            Spacer()
                            Text(d.existed ? "updated" : "new file").foregroundStyle(.secondary)
                        }
                        .font(.caption.monospacedDigit())
                        DiffView(diff: d.diff)
                    }
                }
            }
            .navigationTitle("Changes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

/// /help: the commands, with what each does. Tapping one puts it in the box.
struct CommandHelpSheet: View {
    var pick: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(Composer.commands + SlashController.libraryCommands, id: \.0) { c in
                        Button {
                            pick(c.0 + " ")
                            dismiss()
                        } label: {
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text(c.0).font(.callout.monospaced().weight(.semibold)).foregroundStyle(.primary)
                                Text(c.1).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                } footer: {
                    Text("Type / in the box to filter these. Saved prompts and, in a Claude Code chat, Claude's own commands appear there too. Start a line with ! to run a shell command, or # to save it to memory.")
                }
            }
            .navigationTitle("Commands")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}

/// /permissions: a Claude Code or Codex chat's folder and mode; for Orbit's
/// own chats, the tools and the rules for asking.
struct PermissionsSheet: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var work: ChatWork?
    @State private var loaded = false

    var body: some View {
        Group {
            if let w = work, w.engine {
                WorkSheet(sid: sid, work: w) { state.chatExtras.workRevision += 1 }
            } else if loaded {
                NavigationStack {
                    ToolsRulesView()
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
                }
            } else {
                ProgressView()
            }
        }
        .task {
            work = try? await state.server?.chatWork(sid: sid)
            loaded = true
        }
    }
}
