import SwiftUI

/// Go back to just before one of your messages: the chat only, or the files
/// later answers changed too.
struct RewindSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var busy = false
    @State private var confirming: (index: Int, files: Bool, text: String)?
    /// What putting the files back would do, asked for before it is done.
    @State private var preview: (index: Int, text: String, look: OrbitServer.UndoPreview)?

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
                                    // what going back would do to each file, before it does it:
                                    // a file you edited yourself since is not quietly overwritten
                                    Button("Chat + files") {
                                        busy = true
                                        Task {
                                            if let look = await state.rewindPreview(toUserIndex: p.index) {
                                                if look.isEmpty { confirming = (p.index, true, p.text) }
                                                else { preview = (p.index, p.text, look) }
                                            } else {
                                                // an older Mac has no preview to give, and a
                                                // failure here left a button that did nothing
                                                // at all with the reason hidden behind the sheet
                                                confirming = (p.index, true, p.text)
                                            }
                                            busy = false
                                        }
                                    }
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
                        if await state.rewind(toUserIndex: c.index, files: c.files) != nil { dismiss() }
                        busy = false
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Everything from “\(String(confirming?.text.prefix(60) ?? ""))” on is removed.")
            }
            .sheet(isPresented: Binding(get: { preview != nil }, set: { if !$0 { preview = nil } })) {
                if let p = preview { undoPreview(p) }
            }
        }
        .presentationDetents([.medium, .large])
    }

    /// The file-by-file account of a "chat + files" rewind. Nothing is restored
    /// at all while anything is in `unsafe` — that is the Mac's rule, not a
    /// warning — so the way past it is the explicit second button.
    private func undoPreview(_ p: (index: Int, text: String, look: OrbitServer.UndoPreview)) -> some View {
        NavigationStack {
            List {
                // the Mac lists one row per write, so a file edited twice appears twice:
                // the counts are of rows, and the rows are what will actually happen
                if !p.look.unsafe.isEmpty {
                    Section {
                        ForEach(Array(p.look.unsafe.enumerated()), id: \.offset) { _, r in
                            row(path: r.path, note: r.why, tint: .orange)
                        }
                    } header: {
                        Text("Changed since that answer wrote them")
                    } footer: {
                        Text("Nothing is put back while these are in the way — a half-undone "
                             + "folder is worse than one that was left alone. Going ahead "
                             + "overwrites the work you did on them since.")
                    }
                }
                if !p.look.safe.isEmpty {
                    Section("Would be put back (\(p.look.safe.count))") {
                        ForEach(Array(p.look.safe.enumerated()), id: \.offset) { _, r in
                            row(path: r.path, note: r.what, tint: .secondary) }
                    }
                }
                if !p.look.gone.isEmpty {
                    Section {
                        ForEach(Array(p.look.gone.enumerated()), id: \.offset) { _, r in
                            row(path: r.path, note: r.why, tint: .secondary) }
                    } header: {
                        Text("Cannot be put back")
                    } footer: {
                        Text("No snapshot was taken — these live outside the workspace.")
                    }
                }
            }
            .navigationTitle("\(p.look.messages) message\(p.look.messages == 1 ? "" : "s") back")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { preview = nil } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(p.look.unsafe.isEmpty ? "Rewind" : "Overwrite and rewind", role: .destructive) {
                        busy = true
                        let force = !p.look.unsafe.isEmpty
                        preview = nil
                        Task {
                            if await state.rewind(toUserIndex: p.index, files: true, force: force) != nil { dismiss() }
                            busy = false
                        }
                    }
                    .disabled(p.look.safe.isEmpty && p.look.unsafe.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func row(path: String, note: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text((path as NSString).lastPathComponent).font(.callout)
            Text(note.isEmpty ? path : "\(note) · \(path)")
                .font(.caption2).foregroundStyle(tint)
                .lineLimit(2).truncationMode(.head)
        }
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
