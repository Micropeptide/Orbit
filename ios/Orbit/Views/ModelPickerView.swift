import SwiftUI

struct ModelPickerView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    /// Only these models (the new-chat sheet shows one harness's). nil = all.
    var only: ((ModelInfo) -> Bool)? = nil
    /// The model to tick. nil = the open chat's.
    var selected: String? = nil
    var title = "Model for this chat"
    /// Called instead of changing the open chat's model.
    var onPick: ((ModelInfo) -> Void)? = nil
    /// Pushed inside another sheet's navigation rather than presented on its own.
    var embedded = false
    @State private var filter = ""
    @State private var note: String?
    /// A provider that cannot answer was picked: why, and where to fix it.
    @State private var problem: Problem?
    /// The provider whose keys to open, from `problem`.
    @State private var settingsFor: SettingsTarget?
    @State private var showOffpeak = false

    struct Problem: Identifiable {
        var message: String
        var providerID: String?
        var id: String { message }
    }

    struct SettingsTarget: Identifiable {
        var providerID: String?
        var id: String { providerID ?? "" }
    }

    /// One heading in the list: a provider as one harness reaches it.
    struct ProviderGroup: Identifiable {
        var title: String
        /// The provider in Settings → Models & keys, for `harness:`/`codex:` ids.
        var providerID: String?
        var codex: Bool
        var models: [ModelInfo]
        /// Set for a provider that has no models to offer because it is not ready.
        var missing: String?
        var id: String { title }
    }

    private var tickedID: String? { selected ?? state.effectiveModelID }

    private var query: String { filter.trimmingCharacters(in: .whitespaces).lowercased() }

    /// Switched off in Settings → Models & keys, except the model already in use.
    private func isHidden(_ m: ModelInfo) -> Bool {
        m.id != tickedID && (state.usage.harnessModel(m.id)?.hidden ?? false)
    }

    private var allowed: [ModelInfo] {
        state.models.filter { (only?($0) ?? true) && !isHidden($0) }
    }

    private var groups: [ProviderGroup] {
        let q = query
        let shown = allowed.filter { m in
            q.isEmpty || m.display.lowercased().contains(q) || m.group.lowercased().contains(q)
        }
        var out: [ProviderGroup] = Dictionary(grouping: shown) { $0.group }.map { title, models in
            let first = models[0].id
            return ProviderGroup(title: title, providerID: ModelID.provider(first),
                         codex: first.hasPrefix("codex:"), models: models)
        }
        // providers that cannot answer have no models listed: say why, where
        // the harness would reach them, so nobody wonders where they went
        if q.isEmpty, let o = state.usage.overview {
            // only for the harness this list is about: every harness at once would
            // bury the models under a dozen "needs a key" headings
            let listed = Set(allowed.map { HarnessKind(modelID: $0.id) })
            let kinds: Set<HarnessKind> = listed.count == 1 ? listed : [HarnessKind(modelID: tickedID)]
            let present = Set(out.compactMap { g in g.providerID.map { (g.codex ? "codex:" : "harness:") + $0 } })
            for p in o.providers where !p.ready {
                if kinds.contains(.claude), !present.contains("harness:" + p.id) {
                    out.append(ProviderGroup(title: "Claude Code · \(p.label)", providerID: p.id, codex: false,
                                     models: [], missing: p.pickerProblem ?? "needs a key"))
                }
                if kinds.contains(.codex), p.id != "claude", !present.contains("codex:" + p.id) {
                    out.append(ProviderGroup(title: "Codex · \(p.label)", providerID: p.id, codex: true,
                                     models: [], missing: p.pickerProblem ?? "needs a key"))
                }
            }
            if kinds.contains(.codex), let c = state.usage.codex["chatgpt"], !c.ready,
               !present.contains("codex:chatgpt") {
                out.append(ProviderGroup(title: c.label, providerID: "chatgpt", codex: true, models: [],
                                 missing: "not signed in"))
            }
        }
        // the open chat's harness first, the ChatGPT account first among Codex
        // routes, then providers in the Mac's own order
        let tickedKind = HarnessKind(modelID: tickedID)
        let order = state.usage.overview?.providers.map(\.id) ?? []
        func key(_ g: ProviderGroup) -> (Int, Int, Int, String) {
            let kind: HarnessKind = g.codex ? .codex : (g.providerID != nil ? .claude
                : HarnessKind(modelID: g.models.first?.id))
            return (kind == tickedKind ? 0 : 1,
                    g.providerID == "chatgpt" ? 0 : 1,
                    g.providerID.flatMap { order.firstIndex(of: $0) } ?? 999,
                    g.title)
        }
        return out.sorted { key($0) < key($1) }
    }

    /// Models used lately in Claude Code and Codex, newest first.
    private var recent: [(RecentModel, ModelInfo)] {
        guard query.isEmpty else { return [] }
        var seen = Set<String>()
        return (state.harnessRecent + state.codexRecent).compactMap { r -> (RecentModel, ModelInfo)? in
            guard r.id != tickedID, !seen.contains(r.id),
                  let m = allowed.first(where: { $0.id == r.id }) else { return nil }
            seen.insert(r.id)
            return (r, m)
        }
        .prefix(5).map { $0 }
    }

    var body: some View {
        if embedded {
            list
        } else {
            NavigationStack {
                list.toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
            }
        }
    }

    private var list: some View {
        List {
            if !recent.isEmpty {
                Section("Recent") {
                    ForEach(recent, id: \.0.id) { r, m in
                        row(m, label: r.label ?? m.display)
                    }
                }
            }
            ForEach(groups) { g in
                Section {
                    if let missing = g.missing {
                        Button {
                            problem = Problem(message: problemText(g, missing), providerID: g.providerID)
                        } label: {
                            Label(missing, systemImage: "exclamationmark.circle")
                                .font(.callout).foregroundStyle(.orange)
                        }
                    }
                    ForEach(g.models) { m in row(m, label: shortLabel(m, in: g)) }
                } header: {
                    header(g)
                } footer: {
                    footer(g)
                }
            }
        }
        .searchable(text: $filter, prompt: "Filter models")
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if allowed.contains(where: { $0.offpeak != nil }) {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showOffpeak = true } label: { Image(systemName: "leaf") }
                        .accessibilityLabel("Cheaper hours")
                }
            }
        }
        .overlay {
            if state.models.isEmpty {
                ContentUnavailableView("No models", systemImage: "cpu",
                    description: Text("Your Mac hasn't reported any models yet."))
            }
        }
        .task {
            await state.loadUsage()
            if state.models.contains(where: { $0.id.hasPrefix("codex:") && (only?($0) ?? true) }) {
                await state.loadCodexStatus(providers: ["chatgpt"])
            }
        }
        .refreshable { await state.loadUsage(force: true); await state.loadModels() }
        .alert(problem?.message ?? "", isPresented: Binding(get: { problem != nil },
                                                           set: { if !$0 { problem = nil } })) {
            if let p = problem, canOpenSettings(p.providerID) {
                Button("Open Models & keys") { settingsFor = SettingsTarget(providerID: p.providerID) }
            }
            Button("OK", role: .cancel) {}
        }
        .sheet(item: $settingsFor) { t in
            NavigationStack {
                Group {
                    if let pid = t.providerID, let o = state.usage.overview,
                       o.providers.contains(where: { $0.id == pid }) {
                        ProviderDetailView(providerID: pid, overview: o)
                    } else {
                        ModelsKeysView()
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") {
                            settingsFor = nil
                            Task { await state.loadUsage(force: true) }
                        }
                    }
                }
            }
        }
        .sheet(isPresented: $showOffpeak) { OffpeakSheet() }
        .settingsNote($note)
    }

    // MARK: rows

    private func row(_ m: ModelInfo, label: String? = nil) -> some View {
        let spend = state.usage.harnessModel(m.id)?.usage
        return Button {
            if !m.isReady {
                problem = Problem(message: notReadyText(m), providerID: ModelID.provider(m.id))
            } else if let onPick { onPick(m); dismiss() }
            else { Task { await state.choose(model: m); dismiss() } }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(label ?? m.display).foregroundStyle(m.isReady ? .primary : .secondary)
                    if let op = m.offpeak {
                        // cheaper hours: green while it is cheaper, orange when later
                        Label(op.shortText, systemImage: op.isActive ? "leaf.fill" : "clock")
                            .font(.caption2)
                            .foregroundStyle(op.isActive ? Color.green : Color.orange)
                    }
                    // the provider's generic note ("through Orbit's translating gateway") says
                    // nothing a heading doesn't; the model's own size and spend matter more
                    if let n = m.note, !n.isEmpty, !Self.genericNote(n) {
                        Text(n).font(.caption2).foregroundStyle(.secondary)
                    } else if !m.isReady {
                        Text("needs an API key on your Mac")
                            .font(.caption2).foregroundStyle(.orange)
                    } else if let c = m.context {
                        Text(contextText(c) + (spend?.shortText.map { " · " + $0 } ?? ""))
                            .font(.caption2).foregroundStyle(.secondary)
                    } else if let s = spend?.shortText {
                        Text(s).font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if m.id == tickedID {
                    Image(systemName: "checkmark").foregroundStyle(.tint)
                }
            }
        }
        .contextMenu {
            // the long figures: this model's spend, and the account it shares
            if let long = spend?.longText { Text(long) }
            if let pid = ModelID.provider(m.id), let p = state.usage.provider(pid),
               let a = p.reportingAccount, let live = a.live {
                Text("\(a.label): \(live.longText) (shared by all models)")
            }
            if let c = m.context { Text(contextText(c) + " context") }
        }
    }

    static func genericNote(_ n: String) -> Bool {
        let t = n.lowercased()
        return t.contains("translating gateway") || t.contains("orbit's gateway")
    }

    /// Under a provider's heading, "GLM-5 · OpenCode Go" is just "GLM-5".
    private func shortLabel(_ m: ModelInfo, in g: ProviderGroup) -> String {
        let full = m.display
        guard let dot = full.range(of: " · ") else { return full }
        let tail = full[dot.upperBound...].lowercased()
        let title = g.title.lowercased()
        return title.contains(tail) || tail.contains(title) ? String(full[..<dot.lowerBound]) : full
    }

    private func contextText(_ n: Int) -> String {
        n >= 1_000_000 ? "\((Double(n) / 1_000_000).formatted(.number.precision(.fractionLength(0...1))))M"
            : "\(n / 1000)k"
    }

    // MARK: headings

    @ViewBuilder private func header(_ g: ProviderGroup) -> some View {
        let p = g.providerID.flatMap { state.usage.provider($0) }
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(g.title)
                if g.missing == nil, let p {
                    if let problem = p.pickerProblem {
                        Text(problem).font(.caption2).foregroundStyle(.orange).textCase(nil)
                    } else if let a = p.reportingAccount, let short = a.live?.shortText {
                        Text("\(a.label): \(short)").font(.caption2).textCase(nil)
                    }
                }
            }
            Spacer()
            // a provider that lists its own models can be asked again from here
            if let pid = g.providerID, let p, !p.isLocal, !p.keyless, g.missing == nil, pid != "chatgpt" {
                if state.usage.refreshing.contains(pid) {
                    ProgressView().controlSize(.mini)
                } else {
                    Button {
                        Task { note = await state.refreshProviderModels(pid) }
                    } label: {
                        Image(systemName: "arrow.clockwise").font(.caption)
                    }
                    .accessibilityLabel("Refresh \(p.label) models")
                }
            }
        }
    }

    @ViewBuilder private func footer(_ g: ProviderGroup) -> some View {
        if g.missing == nil, let pid = g.providerID, let p = state.usage.provider(pid) {
            let parts = [
                p.fetchedAt.map { "list from " + Date(timeIntervalSince1970: $0).formatted(date: .abbreviated, time: .omitted) },
                p.reportingAccount.flatMap { a in a.live.map { "\(a.label): \($0.longText) (shared by all models)" } },
            ].compactMap { $0 }
            if !parts.isEmpty { Text(parts.joined(separator: " · ")) }
        }
    }

    // MARK: problems

    private func problemText(_ g: ProviderGroup, _ missing: String) -> String {
        if g.providerID == "chatgpt" {
            return "Codex is not signed in — run codex login in a terminal on your Mac."
        }
        if g.providerID == "claude" {
            return "The claude command is not signed in — run claude auth login in a terminal on your Mac "
                + "(or it is not installed)."
        }
        let label = g.providerID.flatMap { state.usage.provider($0)?.label } ?? g.title
        if missing.hasPrefix("used up") { return "\(label) is \(missing)." }
        return "\(label) needs a key — add it in Settings → Models & keys."
    }

    private func notReadyText(_ m: ModelInfo) -> String {
        if let pid = ModelID.provider(m.id), let p = state.usage.provider(pid) {
            return problemText(ProviderGroup(title: p.label, providerID: pid, codex: m.id.hasPrefix("codex:"), models: []),
                               p.pickerProblem ?? "needs a key")
        }
        return "\(m.group) needs an API key — add it in Settings → Models & keys."
    }

    /// The ChatGPT sign-in and the Claude login happen in a terminal on the Mac,
    /// not in Models & keys.
    private func canOpenSettings(_ pid: String?) -> Bool {
        pid != "chatgpt"
    }
}

/// One line under a model's name elsewhere (the new-chat sheet): what is left
/// of its provider's allowance, or why it cannot answer.
struct ModelAllowanceLine: View {
    @EnvironmentObject var state: AppState
    let modelID: String?

    var body: some View {
        // a stack rather than a Group, so the task below runs even while it is empty
        VStack(alignment: .trailing, spacing: 0) {
            if let id = modelID, let pid = ModelID.provider(id), let p = state.usage.provider(pid) {
                if let problem = p.pickerProblem {
                    Text("\(p.label): \(problem)").foregroundStyle(.orange)
                } else if let a = p.reportingAccount, let short = a.live?.shortText {
                    Text("\(p.label) · \(a.label): \(short)").foregroundStyle(.secondary)
                }
            }
        }
        .font(.caption2)
        .task { await state.loadUsage() }
    }
}
