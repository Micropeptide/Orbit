import SwiftUI

/// Crew mode: a builder and a reviewer improving a folder, round after round, until a limit or until
/// you stop them. The runs are the Mac's; this lists them, shows where each is, and pauses, resumes
/// and stops them. Starting one spends tokens, so it asks.
struct CrewView: View {
    @EnvironmentObject var state: AppState
    @State private var runs: [CrewRun]?
    @State private var error: String?
    @State private var starting = false

    var body: some View {
        List {
            if let error { Section { ErrorRow(message: error) } }
            if let runs {
                Section {
                    if runs.isEmpty {
                        Text("No crews yet. A crew is a builder chat and a reviewer chat that improve a folder together until you stop them.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(runs) { r in
                        NavigationLink { CrewDetailView(runID: r.id, runs: $runs) } label: { row(r) }
                    }
                } footer: {
                    Text("The Mac runs them, so they carry on when this phone is away. Each round spends tokens on the builder's and the reviewer's models.")
                }
            } else if error == nil {
                Section { LoadingRow() }
            }
        }
        .navigationTitle("Crew")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { starting = true } label: { Image(systemName: "plus") }.accessibilityLabel("New crew")
            }
        }
        .task { await keepCurrent() }
        .refreshable { await load() }
        .sheet(isPresented: $starting) { NewCrewView { await load() } }
    }

    private func row(_ r: CrewRun) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(r.title).font(.callout.weight(.medium)).lineLimit(1)
                Spacer()
                ClusterStatePill(text: CrewView.stateWords(r), tint: CrewView.tint(r))
            }
            Text(summary(r)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            if !r.attention.isEmpty {
                Label(r.attention, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.orange)
            }
        }
    }

    private func summary(_ r: CrewRun) -> String {
        var p = ["round \(r.round)"]
        if let b = r.best { p.append("best score \(b)") }
        if r.isRunning, !r.phase.isEmpty, r.phase != "idle" { p.append(r.phase == "build" ? "building" : "reviewing") }
        else if !r.reason.isEmpty { p.append(r.reason) }
        return p.joined(separator: " · ")
    }

    static func stateWords(_ r: CrewRun) -> String { r.state.isEmpty ? "—" : r.state }

    static func tint(_ r: CrewRun) -> Color {
        switch r.state {
        case "running": return .green
        case "paused": return .orange
        case "done": return .accentColor
        default: return .secondary
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            runs = try await server.crewRuns().sorted { $0.created > $1.created }
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    /// A running crew moves between rounds, so the list is read again every few seconds while on show.
    private func keepCurrent() async {
        while !Task.isCancelled {
            await load()
            try? await Task.sleep(nanoseconds: 8_000_000_000)
        }
    }
}

/// One crew: where it is, the reviewer's scores round by round, what is still to do, and the controls.
struct CrewDetailView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let runID: String
    @Binding var runs: [CrewRun]?
    @State private var note = ""
    @State private var toast: String?
    @State private var confirm: Confirm?
    @State private var limitsOpen = false
    @State private var showBrief = false

    enum Confirm: String, Identifiable {
        case resume, stop, delete
        var id: String { rawValue }
    }

    private var run: CrewRun? { runs?.first { $0.id == runID } }

    var body: some View {
        List {
            if let r = run {
                statusSection(r)
                controls(r)
                if !r.history.isEmpty { roundsSection(r) }
                if !r.backlog.isEmpty { backlogSection(r) }
                noteSection(r)
                aboutSection(r)
            } else {
                Section { Text("This crew is gone.").foregroundStyle(.secondary) }
            }
        }
        .navigationTitle(run?.title ?? "Crew")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($toast)
        .sheet(isPresented: $limitsOpen) { if let r = run { CrewLimitsSheet(run: r) { await reload() } } }
        .confirmationDialog(confirmTitle, isPresented: Binding(get: { confirm != nil }, set: { if !$0 { confirm = nil } }),
                            titleVisibility: .visible, presenting: confirm) { c in
            Button(c == .resume ? "Resume" : c == .stop ? "Stop it" : "Delete", role: c == .resume ? nil : .destructive) {
                Task { await perform(c) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { c in Text(confirmMessage(c)) }
    }

    private var confirmTitle: String {
        switch confirm {
        case .resume: return "Resume this crew?"
        case .stop: return "Stop this crew?"
        case .delete: return "Delete this crew?"
        case nil: return ""
        }
    }

    private func confirmMessage(_ c: Confirm) -> String {
        switch c {
        case .resume: return "The builder and the reviewer start working again and spend tokens until a limit or until you stop them."
        case .stop: return "It ends here. Its chats are let go and the folder keeps what was built."
        case .delete: return "The run and its history go. The folder and its files stay."
        }
    }

    // ------------------------------------------------------------ sections

    private func statusSection(_ r: CrewRun) -> some View {
        Section {
            HStack {
                ClusterStatePill(text: CrewView.stateWords(r), tint: CrewView.tint(r))
                if !r.reason.isEmpty { Text(r.reason).font(.footnote).foregroundStyle(.secondary) }
            }
            if !r.attention.isEmpty {
                Label(r.attention, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(.orange)
            }
            LabeledContent("Round", value: "\(r.round)" + (r.isRunning && r.phase != "idle" ? " · " + (r.phase == "build" ? "building" : "reviewing") : ""))
            if let b = r.best { LabeledContent("Best score", value: "\(b) (round \(r.bestRound))") }
            LabeledContent("Tokens", value: r.tokens.formatted())
            if r.hours > 0 || r.maxRounds > 0 || r.maxTokens > 0 {
                LabeledContent("Limits", value: [r.hours > 0 ? "\(r.hours.formatted()) h" : nil,
                                                 r.maxRounds > 0 ? "\(r.maxRounds) rounds" : nil,
                                                 r.maxTokens > 0 ? "\(r.maxTokens.formatted()) tokens" : nil]
                    .compactMap { $0 }.joined(separator: ", "))
            }
        }
    }

    private func controls(_ r: CrewRun) -> some View {
        Section {
            if r.isRunning {
                Button { Task { await pause() } } label: { Label("Pause", systemImage: "pause.fill") }
            } else {
                Button { confirm = .resume } label: {
                    Label(r.state == "done" ? "Resume (raise a limit first)" : "Resume", systemImage: "play.fill")
                }
                .disabled(r.state == "done")
            }
            if r.state != "stopped" {
                Button(role: .destructive) { confirm = .stop } label: { Label("Stop", systemImage: "stop.fill") }
            }
            Button { limitsOpen = true } label: { Label("Limits", systemImage: "gauge.with.dots.needle.33percent") }
            if let sid = r.builders.first?.sid { Button { open(sid) } label: { Label("Open the builder's chat", systemImage: "bubble.left") } }
            if let sid = r.reviewers.first?.sid { Button { open(sid) } label: { Label("Open the reviewer's chat", systemImage: "bubble.right") } }
            Button(role: .destructive) { confirm = .delete } label: { Label("Delete", systemImage: "trash") }
        }
    }

    private func roundsSection(_ r: CrewRun) -> some View {
        Section {
            ForEach(r.history.reversed().prefix(12)) { h in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Round \(h.round)").font(.callout.weight(.medium))
                        Spacer()
                        if let s = h.score { Text("\(s)").font(.callout.monospacedDigit().weight(.semibold)) }
                    }
                    Text(h.summary).font(.footnote).foregroundStyle(.secondary).lineLimit(6)
                    ForEach(h.issues.prefix(3), id: \.self) { Text("• " + $0).font(.caption).foregroundStyle(.orange).lineLimit(2) }
                }
                .padding(.vertical, 2)
            }
        } header: {
            Text("Rounds")
        } footer: {
            Text("The reviewer's score and summary for each round, newest first.")
        }
    }

    private func backlogSection(_ r: CrewRun) -> some View {
        Section("Still to do") {
            ForEach(r.backlog.prefix(10), id: \.self) { Text($0).font(.footnote).lineLimit(4) }
        }
    }

    private func noteSection(_ r: CrewRun) -> some View {
        Section {
            TextField("Tell the builder something", text: $note, axis: .vertical).lineLimit(1...5)
            Button("Send note") { Task { await send(r) } }
                .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            ForEach(r.notes, id: \.self) { Text($0).font(.footnote).foregroundStyle(.secondary).lineLimit(3) }
        } header: {
            Text("Notes")
        } footer: {
            Text("The builder reads a note at its next step. A crew never asks you questions; it decides and carries on.")
        }
    }

    private func aboutSection(_ r: CrewRun) -> some View {
        Section {
            LabeledContent("Folder", value: r.folder).font(.footnote)
            DisclosureGroup("The brief", isExpanded: $showBrief) {
                Text(r.brief).font(.footnote).textSelection(.enabled)
            }
            LabeledContent("Builders", value: r.builders.map { $0.model ?? "a chat of yours" }.joined(separator: ", ")).font(.footnote)
            LabeledContent("Reviewers", value: r.reviewers.isEmpty ? "none" : r.reviewers.map { $0.model ?? "a chat of yours" }.joined(separator: ", "))
                .font(.footnote)
        } header: {
            Text("About")
        }
    }

    // ------------------------------------------------------------ actions

    private func open(_ sid: String) {
        state.tab = "chats"
        state.deepLink = sid
    }

    private func reload() async {
        if let server = state.server, let r = try? await server.crewRuns() { runs = r.sorted { $0.created > $1.created } }
    }

    private func perform(_ c: Confirm) async {
        guard let server = state.server else { return }
        do {
            switch c {
            case .resume: try await server.crewControl("resume", id: runID)
            case .stop: try await server.crewControl("stop", id: runID)
            case .delete: try await server.crewDelete(id: runID)
            }
            Haptics.success()
            await reload()
            if c == .delete { dismiss() }
        } catch { toast = error.localizedDescription }
    }

    /// Pausing needs no question: it only stops spending.
    private func pause() async {
        guard let server = state.server else { return }
        do { try await server.crewControl("pause", id: runID); await reload() } catch { toast = error.localizedDescription }
    }

    private func send(_ r: CrewRun) async {
        guard let server = state.server else { return }
        do {
            try await server.crewNote(id: r.id, text: note.trimmingCharacters(in: .whitespacesAndNewlines))
            note = ""
            toast = "note sent"
            await reload()
        } catch { toast = error.localizedDescription }
    }
}
