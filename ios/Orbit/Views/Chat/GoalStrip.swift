import SwiftUI

/// Above the message box: the chat's goal, where it stands, and its controls. The Mac
/// keeps the chat working until the goal is done; this is how you see and steer that.
struct GoalStrip: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @State private var confirmClear = false
    @State private var showHistory = false

    var body: some View {
        Group {
            if let o = state.goalOffer, state.openChat?.sid == sid,
               state.goal == nil || state.goal?.status == "complete" {
                OfferCard(sid: sid, offer: o)
            } else if let g = state.goal, state.openChat?.sid == sid {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Image(systemName: icon(g.status)).foregroundStyle(tint(g.status))
                        Text(g.word).font(.caption.weight(.semibold)).foregroundStyle(tint(g.status))
                        Text(g.objective).font(.caption).lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: 4)
                        Menu {
                            if g.status == "active" {
                                Button("Pause", systemImage: "pause") { Task { await state.goalAction("pause") } }
                            } else if g.status != "complete" {
                                Button("Resume", systemImage: "play") { Task { await resume(g) } }
                            }
                            Button("Edit…", systemImage: "pencil") { state.showGoalEditor = true }
                            Button("Clear goal", systemImage: "xmark", role: .destructive) { confirmClear = true }
                        } label: {
                            Image(systemName: "ellipsis.circle").font(.callout)
                        }
                        .accessibilityLabel("Goal actions")
                    }
                    Text(g.usage).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                    if !g.reason.isEmpty {
                        Text(g.reason).font(.caption2).foregroundStyle(.secondary).lineLimit(3)
                    }
                    // what each check said: why it carried on, and why it stopped
                    if g.history.count > 1 {
                        DisclosureGroup(isExpanded: $showHistory) {
                            ScrollView {
                                VStack(alignment: .leading, spacing: 3) {
                                    ForEach(Array(g.history.reversed().enumerated()), id: \.offset) { _, h in
                                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                                            Text(Date(timeIntervalSince1970: h.t).formatted(date: .omitted, time: .shortened))
                                                .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                                            Text(h.verdict).font(.caption2.weight(.semibold))
                                            Text(h.reason).font(.caption2).foregroundStyle(.secondary)
                                        }
                                    }
                                }
                            }
                            .frame(maxHeight: 120)
                        } label: {
                            Text("History").font(.caption2)
                        }
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .leading) {
                    Rectangle().fill(tint(g.status)).frame(width: 3)
                }
                .overlay(Divider(), alignment: .top)
                .confirmationDialog("Stop keeping this goal?", isPresented: $confirmClear) {
                    Button("Clear goal", role: .destructive) { Task { await state.goalAction("clear") } }
                } message: {
                    Text("The chat stays as it is; it just won't carry on by itself.")
                }
            }
        }
        .sheet(isPresented: $state.showGoalEditor) { GoalEditor(sid: sid) }
    }

    private func resume(_ g: Goal) async {
        // a goal that used its budget needs a bigger one to carry on
        if g.overBudget { state.showGoalEditor = true; return }
        await state.goalAction("resume")
    }

    private func icon(_ s: String) -> String {
        switch s {
        case "active": return "scope"
        case "complete": return "checkmark.circle.fill"
        case "paused": return "pause.circle"
        default: return "exclamationmark.circle"
        }
    }

    private func tint(_ s: String) -> Color {
        switch s {
        case "active": return .accentColor
        case "complete": return .green
        case "paused": return .secondary
        default: return .orange
        }
    }
}

/// The answer left work undone: keep going until it is done? Taken on its own when the
/// countdown runs out, unless you say no.
struct OfferCard: View {
    let sid: String
    let offer: GoalOffer
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Image(systemName: "scope").foregroundStyle(Color.accentColor)
                Text("Keep going until it's done?").font(.caption.weight(.semibold))
            }
            Text(offer.objective).font(.caption).lineLimit(2).foregroundStyle(.secondary)
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                Text(line(at: ctx.date)).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }
            HStack {
                Button("Keep going until done") {
                    Task { await state.answerGoalOffer(sid: sid, accept: true) }
                }
                .buttonStyle(.borderedProminent).controlSize(.small)
                Button("No thanks") {
                    Task { await state.answerGoalOffer(sid: sid, accept: false) }
                }
                .buttonStyle(.bordered).controlSize(.small)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.accentColor.opacity(0.07))
        .overlay(alignment: .leading) { Rectangle().fill(Color.accentColor).frame(width: 3) }
        .overlay(Divider(), alignment: .top)
    }

    private func line(at now: Date) -> String {
        let why = offer.why.prefix(1).uppercased() + offer.why.dropFirst()
        guard let dl = offer.deadline else { return why }
        let left = Int(max(0, dl.timeIntervalSince(now)))
        if left == 0 {
            // taken on the Mac: pick up the goal it just started
            Task { try? await Task.sleep(for: .seconds(3)); if state.goalOffer == offer { state.goalOffer = nil; await state.open(sid) } }
            return why + " · carrying on…"
        }
        return why + " · it carries on by itself in \(left / 60):" + String(format: "%02d", left % 60)
    }
}

/// Set a goal, or change one: what done looks like, a token budget, a turn limit.
struct GoalEditor: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var objective = ""
    @State private var budget = ""
    @State private var turns = 20

    private var existing: Goal? { state.goal }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("e.g. every test in tests/ passes and the README documents the new flag",
                              text: $objective, axis: .vertical)
                        .lineLimit(3...8)
                } header: {
                    Text("What done looks like")
                } footer: {
                    Text("After each answer the Mac checks the work against this and carries on, or stops "
                         + "and says why — done, stuck three checks running, over its budget, or out of turns. "
                         + "Stop pauses it.")
                }
                Section("Limits") {
                    TextField("Token budget (none)", text: $budget).keyboardType(.numberPad)
                    Stepper("Up to \(turns) turns", value: $turns, in: 1...200)
                }
            }
            .navigationTitle(existing == nil ? "Set a goal" : "Goal")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(existing == nil ? "Start" : "Save") { Task { await save() } }
                        .disabled(objective.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear {
                if let g = existing {
                    objective = g.objective
                    budget = g.token_budget > 0 ? String(g.token_budget) : ""
                    turns = g.max_turns
                }
            }
        }
    }

    private func save() async {
        let obj = objective.trimmingCharacters(in: .whitespacesAndNewlines)
        let tb = Int(budget.filter(\.isNumber)) ?? 0
        let had = existing
        await state.goalAction(had == nil ? "set" : "edit", objective: obj, tokenBudget: tb, maxTurns: turns)
        // a new goal starts at once; one that stopped at its budget carries on with the new one
        if had == nil || had?.status == "budget" {
            await state.goalAction("resume")
        }
        dismiss()
    }
}


/// In a chat another chat started: which one, and a way back to it.
struct ParentLine: View {
    let sid: String
    @EnvironmentObject var state: AppState

    var body: some View {
        if state.openChat?.sid == sid, let p = state.openChat?.parent, let psid = p["sid"],
           let url = URL(string: "orbit://chat/" + psid) {
            HStack(spacing: 5) {
                Image(systemName: "arrow.turn.down.right").font(.caption2)
                Text("Started by").font(.caption2).foregroundStyle(.secondary)
                Link(p["title"] ?? "another chat", destination: url).font(.caption2.weight(.semibold))
                Spacer()
            }
            .padding(.horizontal, 14).padding(.vertical, 4)
            .overlay(Divider(), alignment: .top)
        }
    }
}


/// The chats this one talks to: which, what each is doing, and whom it waits on now.
/// Kept fresh while any of them is at work; it also picks up a goal the chat set itself.
struct LinksStrip: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @State private var links: [ChatLink] = []
    @State private var talkingTo: String?
    @State private var open = false

    var body: some View {
        Group {
            if !links.isEmpty || talkingTo != nil {
                VStack(alignment: .leading, spacing: 4) {
                    Button { withAnimation(.easeInOut(duration: 0.15)) { open.toggle() } } label: {
                        HStack(spacing: 5) {
                            Image(systemName: "arrow.left.arrow.right").font(.caption2)
                            Text(talkingTo.map { "Waiting for “\($0)”" } ?? "Talks with \(links.count) chat\(links.count == 1 ? "" : "s")")
                                .lineLimit(1)
                            Spacer(minLength: 4)
                            Image(systemName: open ? "chevron.down" : "chevron.up").font(.caption2).foregroundStyle(.tertiary)
                        }
                        .font(.caption).contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    if open {
                        ForEach(links) { l in
                            HStack(spacing: 6) {
                                Text(l.role).font(.caption2).foregroundStyle(.secondary).frame(minWidth: 56, alignment: .leading)
                                if let url = URL(string: "orbit://chat/" + l.sid) {
                                    Link(l.title, destination: url).font(.caption2.weight(.semibold)).lineLimit(1)
                                }
                                Spacer(minLength: 4)
                                Text([l.state, l.goal.map { $0 == "complete" ? "goal done" : "goal: " + $0 } ?? ""]
                                        .filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(Divider(), alignment: .top)
            }
        }
        .task(id: sid) {
            // every few seconds while it, or a chat it talks to, is at work
            while !Task.isCancelled {
                await load()
                let busy = state.streaming || talkingTo != nil || links.contains { !$0.state.isEmpty }
                    || state.goal?.status == "active"
                try? await Task.sleep(for: .seconds(busy ? 4 : 20))
            }
        }
    }

    private func load() async {
        guard let server = state.server, state.openChat?.sid == sid,
              let r = try? await server.links(sid) else { return }
        links = r.links; talkingTo = r.talkingTo
        if state.openChat?.sid == sid, r.goal != state.goal { state.goal = r.goal }
    }
}
