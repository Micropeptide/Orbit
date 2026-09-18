import SwiftUI

/// Settings → Models & keys: every provider Orbit, Claude Code and Codex share,
/// with accounts, keys, live allowance and which models the picker shows.
struct ModelsKeysView: View {
    @EnvironmentObject var state: AppState
    @State private var overview: HarnessOverview?
    @State private var error: String?
    @State private var note: String?
    @State private var proxy = ""

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let o = overview {
                Section {
                    ForEach(o.providers) { p in
                        NavigationLink {
                            ProviderDetailView(providerID: p.id, overview: o)
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(p.label)
                                HStack(spacing: 4) {
                                    Image(systemName: p.ready ? "checkmark.circle.fill" : "exclamationmark.circle")
                                        .foregroundStyle(p.ready ? .green : .orange)
                                    Text("\(p.statusLine) · \(p.models.count) models")
                                }
                                .font(.caption).foregroundStyle(.secondary)
                                // the account the pickers report on: the first with a key
                                // that is not used up, not only the one marked in use
                                if let until = p.usedUpUntil {
                                    Text("used up until " + until.formatted(date: .abbreviated, time: .shortened))
                                        .font(.caption2).foregroundStyle(.orange)
                                } else if let a = p.reportingAccount, let live = a.live, live.error == nil,
                                   !live.windows.isEmpty {
                                    Text((p.accounts.count > 1 ? "\(a.label): " : "")
                                         + live.windows.map { "\($0.window.left)% \($0.name.lowercased())" }
                                            .joined(separator: " · ") + " left")
                                        .font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                } header: {
                    Text("Providers")
                } footer: {
                    Text("One list for every mode. Keys are stored on the Mac and sent only to their "
                         + "provider; this phone never reads them back."
                         + (o.gatewayError.map { " The gateway is not running: \($0)" } ?? "")
                         + (o.gatewayStats.map { $0.requests > 0 ? " Gateway since it started: \($0.text)." : "" } ?? ""))
                }

                Section {
                    NavigationLink("When a model keeps failing") { FallbackView() }
                    NavigationLink("More models for Orbit's own chat") { OtherModelsView() }
                    NavigationLink("Add your own provider") {
                        CustomProviderView(overview: o) { Task { await load() } }
                    }
                }

                Section {
                    TextField("http://127.0.0.1:7890 (optional)", text: $proxy)
                        .keyboardType(.URL).autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    Button("Save proxy") {
                        Task { await run("proxy saved") {
                            try await state.requireServer().harnessSave(
                                ["proxy": proxy.trimmingCharacters(in: .whitespaces)])
                        } }
                    }
                    .disabled(proxy == (o.proxy ?? ""))
                } header: {
                    Text("Proxy for model requests")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Models & keys")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
    }

    private func load() async {
        do {
            let o = try await state.requireServer().harness()
            overview = o
            // the picker reads the same figures: no need for it to ask again
            state.usage.overview = o
            state.usage.overviewAt = Date()
            proxy = o.proxy ?? ""
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func run(_ done: String, _ work: () async throws -> Void) async {
        do { try await work(); note = done; Haptics.success(); await load() }
        catch { note = error.localizedDescription }
    }
}

// MARK: - One provider

struct ProviderDetailView: View {
    @EnvironmentObject var state: AppState
    let providerID: String
    @State var overview: HarnessOverview
    @State private var note: String?
    @State private var busy: String?
    @State private var tests: [String: String] = [:]
    @State private var renaming: HarnessAccount?
    @State private var renameText = ""
    @State private var removing: HarnessAccount?
    @State private var addingAccount = false
    @State private var newAccountName = ""
    @State private var confirmRemoveToken = false

    private var p: HarnessProvider? { overview.providers.first { $0.id == providerID } }

    var body: some View {
        List {
            if let p {
                Section {
                    LabeledContent("Status", value: p.statusLine)
                    if let docs = p.docs, !docs.isEmpty {
                        Text(docs).font(.caption).foregroundStyle(.secondary)
                    }
                    if let u = p.keysURL, let url = URL(string: u) {
                        Link("Get a key", destination: url)
                    }
                }

                if p.isSubscription { subscription(p) }
                if p.takesKeys { accounts(p) }
                if p.takesKeys { modelList(p) }
                if p.takesKeys, !p.altBases.isEmpty { region(p) }
                models(p)
            } else {
                ErrorRow(message: "This provider is no longer on the Mac.")
            }
        }
        .navigationTitle(p?.label ?? "Provider")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await reload() }
        .settingsNote($note)
        .alert("Rename account", isPresented: Binding(get: { renaming != nil },
                                                        set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: $renameText)
            Button("Save") {
                if let a = renaming {
                    let label = renameText.trimmingCharacters(in: .whitespaces)
                    Task { await act("renamed") {
                        try await state.requireServer().harnessAccount(provider: providerID, op: "rename",
                                                                       id: a.id, label: label)
                    } }
                }
                renaming = nil
            }
            Button("Cancel", role: .cancel) { renaming = nil }
        }
        .alert("Add another account", isPresented: $addingAccount) {
            TextField("Name, e.g. Work", text: $newAccountName)
            Button("Add") {
                let label = newAccountName.trimmingCharacters(in: .whitespaces)
                Task { await act("account added — paste its key") {
                    try await state.requireServer().harnessAccount(provider: providerID, op: "add", label: label)
                } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Several accounts for one provider are tried in order: the one in use first, "
                 + "then the next when its allowance is used up.")
        }
        .confirmationDialog("Remove this account?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            if let a = removing, let p {
                Button("Remove \(a.label)", role: .destructive) {
                    Task { await act("removed") {
                        let s = try state.requireServer()
                        if p.accounts.count == 1 { try await s.saveSecret(name: a.key, value: "") }
                        else { try await s.harnessAccount(provider: p.id, op: "remove", id: a.id) }
                    } }
                    removing = nil
                }
            }
            Button("Cancel", role: .cancel) { removing = nil }
        } message: {
            Text("Its key is deleted from the Mac. Chats using this provider move to another account, "
                 + "or stop working if it was the only one.")
        }
        .confirmationDialog("Remove the Claude sign-in token?", isPresented: $confirmRemoveToken,
                            titleVisibility: .visible) {
            Button("Remove token", role: .destructive) {
                Task { await act("token removed", fresh: true) {
                    try await state.requireServer().saveSecret(name: "CLAUDE_CODE_OAUTH_TOKEN", value: "")
                } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Claude Code on the Mac falls back to its own login, if it has one.")
        }
    }

    // MARK: sections

    @ViewBuilder private func subscription(_ p: HarnessProvider) -> some View {
        Section {
            LabeledContent("Signed in", value: p.ready ? "yes" : "no")
            LabeledContent("Token saved in Orbit", value: (p.tokenSet ?? false) ? "yes" : "no")
            SecretEntry(placeholder: (p.tokenSet ?? false) ? "Replace the sign-in token"
                                                           : "Paste the token from claude setup-token") { v in
                await actResult("token saved", fresh: true) {
                    try await state.requireServer().saveSecret(name: "CLAUDE_CODE_OAUTH_TOKEN", value: v)
                }
            }
            Button("Check again") {
                Task {
                    await reload(fresh: true)
                    note = (p.ready || (self.p?.ready ?? false)) ? "signed in" : "still not signed in"
                }
            }
            if p.tokenSet ?? false {
                Button("Remove token", role: .destructive) { confirmRemoveToken = true }
            }
        } header: {
            Text("Claude sign-in")
        } footer: {
            Text("Uses the claude command's own login on the Mac. If it says not signed in, run "
                 + "claude setup-token in a terminal on the Mac and paste the token it prints here.")
        }
    }

    @ViewBuilder private func accounts(_ p: HarnessProvider) -> some View {
        Section {
            ForEach(p.accounts) { a in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(a.label).font(.body.weight(.medium))
                        if a.active && a.keySet {
                            Text("in use").font(.caption2.weight(.semibold))
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(.tint.opacity(0.15), in: .capsule)
                        }
                        Spacer()
                        Menu {
                            if !a.active {
                                Button("Use this account") { Task { await act("now in use") {
                                    try await state.requireServer().harnessAccount(provider: p.id, op: "activate", id: a.id)
                                } } }
                            }
                            if a.exhaustedUntil != nil {
                                Button("Not used up") { Task { await act("cleared") {
                                    try await state.requireServer().harnessAccount(provider: p.id, op: "clear", id: a.id)
                                } } }
                            }
                            Button("Rename") { renameText = a.label; renaming = a }
                            if p.accounts.count > 1 || a.keySet {
                                Button("Remove", role: .destructive) { removing = a }
                            }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                    Text(a.key + (a.keySet ? " · key set" : " · no key yet"))
                        .font(.caption.monospaced()).foregroundStyle(.secondary)
                    if let until = a.exhaustedUntil {
                        Text("Used up until " + Date(timeIntervalSince1970: until)
                                .formatted(date: .abbreviated, time: .shortened))
                            .font(.caption).foregroundStyle(.orange)
                    }
                    if let live = a.live { LiveUsageView(live: live) }
                    if let u = a.usage, u.requests > 0, let long = u.longText {
                        Text("Through Orbit — " + long).font(.caption).foregroundStyle(.secondary)
                    } else if let s = a.monthSpent, s > 0 {
                        Text(String(format: "$%.2f this month through Orbit", s))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    SecretEntry(placeholder: a.keySet ? "Replace the key" : "Paste the key",
                                buttonTitle: "Save key") { v in
                        await actResult("key saved") {
                            try await state.requireServer().saveSecret(name: a.key, value: v)
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            Button {
                newAccountName = "Account \(p.accounts.count + 1)"
                addingAccount = true
            } label: { Label("Add another account", systemImage: "plus") }
        } header: {
            Text("Accounts")
        } footer: {
            Text("A key you paste goes straight to the Mac and is cleared from this screen. "
                 + "Stored keys are never shown.")
        }
    }

    @ViewBuilder private func modelList(_ p: HarnessProvider) -> some View {
        Section {
            LabeledContent("Model list", value: p.fetchedAt.map {
                "updated " + Date(timeIntervalSince1970: $0).formatted(date: .abbreviated, time: .shortened)
            } ?? "preset")
            Button {
                busy = "refresh"
                Task {
                    do {
                        let r = try await state.requireServer().harnessRefresh(provider: p.id)
                        note = "\(p.label): \(r.count) models" + (r.note.map { " — \($0)" } ?? "")
                        await reload()
                        await state.loadModels()
                    } catch { note = error.localizedDescription }
                    busy = nil
                }
            } label: {
                HStack {
                    Text("Refresh model list")
                    Spacer()
                    if busy == "refresh" { ProgressView().controlSize(.mini) }
                }
            }
            .disabled(busy != nil)
        }
    }

    @ViewBuilder private func region(_ p: HarnessProvider) -> some View {
        let all = ([p.base ?? ""] + p.altBases).filter { !$0.isEmpty }
            .reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        Section("Region") {
            Picker("Endpoint", selection: Binding(
                get: { p.base ?? "" },
                set: { b in Task { await act("region saved") {
                    try await state.requireServer().harnessSave(["providers": [p.id: ["base": b]]])
                } } })) {
                ForEach(all, id: \.self) { Text($0).font(.caption).tag($0) }
            }
            .pickerStyle(.navigationLink)
        }
    }

    @ViewBuilder private func models(_ p: HarnessProvider) -> some View {
        Section {
            ForEach(p.models) { m in
                let mid = "harness:\(p.id)/\(m.id)"
                VStack(alignment: .leading, spacing: 4) {
                    Toggle(isOn: Binding(
                        get: { !m.hidden },
                        set: { show in Task { await setHidden(mid, hidden: !show) } })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(m.label)
                            Text([m.id, m.formatLabel,
                                  m.context.map { "\($0 / 1000)k" } ?? ""]
                                    .filter { !$0.isEmpty }.joined(separator: " · "))
                                .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                            if let u = m.usage, u.requests > 0, let long = u.longText {
                                Text(long).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                    HStack {
                        Button(busy == mid ? "Testing…" : "Test") { Task { await test(mid, m.label) } }
                            .buttonStyle(.bordered).controlSize(.small)
                            .disabled(busy != nil)
                        if let t = tests[mid] {
                            Text(t).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                        }
                    }
                }
            }
        } header: {
            Text("Models")
        } footer: {
            Text("Switched off: hidden from the model picker. Test sends one tiny request through "
                 + "the same route a chat uses.")
        }
    }

    // MARK: actions

    private func reload(fresh: Bool = false) async {
        if let o = try? await state.requireServer().harness(fresh: fresh) { overview = o }
    }

    private func act(_ done: String, fresh: Bool = false, _ work: () async throws -> Void) async {
        _ = await actResult(done, fresh: fresh, work)
    }

    private func actResult(_ done: String, fresh: Bool = false,
                           _ work: () async throws -> Void) async -> Bool {
        do {
            try await work()
            note = done
            Haptics.success()
            await reload(fresh: fresh)
            await state.loadModels()
            return true
        } catch {
            note = error.localizedDescription
            return false
        }
    }

    private func setHidden(_ mid: String, hidden: Bool) async {
        var set = Set(overview.hiddenIDs)
        if hidden { set.insert(mid) } else { set.remove(mid) }
        await act(hidden ? "hidden from the picker" : "shown in the picker") {
            try await state.requireServer().harnessSave(["hidden": Array(set).sorted()])
        }
    }

    private func test(_ mid: String, _ label: String) async {
        busy = mid
        defer { busy = nil }
        do {
            let r = try await state.requireServer().harnessTest(modelID: mid)
            if r.ok == true {
                tests[mid] = String(format: "replied in %.1fs — ", r.secs ?? 0) + String((r.reply ?? "").prefix(40))
            } else {
                tests[mid] = String((r.error ?? "failed").prefix(160))
            }
        } catch { tests[mid] = error.localizedDescription }
    }
}

/// What is left of an account's allowance, per window.
struct LiveUsageView: View {
    let live: LiveUsage

    var body: some View {
        if let e = live.error {
            Text("Usage unavailable (\(e))").font(.caption).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 5) {
                ForEach(live.windows, id: \.name) { w in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(w.name).font(.caption)
                            Spacer()
                            Text("\(w.window.left)% left" + (w.window.limited ? " · limit reached" : ""))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(w.window.limited ? .orange : .secondary)
                        }
                        ProgressView(value: Double(w.window.left), total: 100)
                            .tint(w.window.left < 15 ? .orange : .accentColor)
                        if let r = w.window.resets {
                            Text(resetText(r)).font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - A provider of your own

struct CustomProviderView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let overview: HarnessOverview
    let onAdded: () -> Void
    @State private var label = ""
    @State private var base = ""
    @State private var format = "messages"
    @State private var keyName = ""
    @State private var models = ""
    @State private var context = 128_000
    @State private var note: String?
    @State private var busy = false

    private var id: String {
        let s = label.lowercased().replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return s.isEmpty ? "custom" : s
    }

    var body: some View {
        Form {
            Section {
                TextField("Name, e.g. My server", text: $label)
                TextField("Base URL", text: $base)
                    .keyboardType(.URL).autocorrectionDisabled().textInputAutocapitalization(.never)
                Picker("API", selection: $format) {
                    Text("Anthropic Messages (native)").tag("messages")
                    Text("OpenAI chat completions (gateway)").tag("chat")
                    Text("OpenAI Responses (gateway)").tag("responses")
                }
                TextField("Key name, e.g. MY_SERVER_KEY", text: $keyName)
                    .autocorrectionDisabled().textInputAutocapitalization(.characters)
                TextField("Models, comma separated", text: $models)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                IntField(title: "Context", value: $context, suffix: "tokens")
            } footer: {
                Text("After adding it, open the provider and paste its key.")
            }
            Section {
                Button(busy ? "Adding…" : "Add provider") { Task { await add() } }
                    .disabled(busy || label.trimmingCharacters(in: .whitespaces).isEmpty
                              || base.trimmingCharacters(in: .whitespaces).isEmpty
                              || modelIDs.isEmpty)
            }
        }
        .navigationTitle("Your own provider")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
    }

    private var modelIDs: [String] {
        models.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private func add() async {
        busy = true
        defer { busy = false }
        // the registry takes the whole custom list, so the existing ones go back with it
        var custom: [String: Any] = [:]
        for p in overview.providers where p.custom {
            custom[p.id] = ["label": p.label, "base": p.base ?? "", "key": p.key ?? "", "auth": p.auth,
                            "models": p.models.map { ["id": $0.id, "format": $0.format ?? "chat",
                                                      "context": $0.context ?? 128_000] }]
        }
        let key = (keyName.trimmingCharacters(in: .whitespaces).isEmpty
                   ? id.uppercased().replacingOccurrences(of: "-", with: "_") + "_API_KEY"
                   : keyName.trimmingCharacters(in: .whitespaces)).uppercased()
        custom[id] = ["label": label.trimmingCharacters(in: .whitespaces),
                      "base": base.trimmingCharacters(in: .whitespaces), "key": key,
                      "auth": format == "messages" ? "api_key" : "gateway",
                      "models": modelIDs.map { ["id": $0, "format": format, "context": context > 0 ? context : 128_000] }]
        do {
            try await state.requireServer().harnessSave(["custom": custom])
            Haptics.success()
            onAdded()
            await state.loadModels()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - The rest of Orbit's model list

struct OtherModelsView: View {
    @EnvironmentObject var state: AppState
    @State private var cat: ModelCatalogue?
    @State private var error: String?
    @State private var note: String?
    @State private var forgetting: ModelInfo?
    @State private var fetching: String?
    @State private var newID = ""
    @State private var newLabel = ""
    @State private var newKind = "openai"
    @State private var newBase = ""
    @State private var newKey = ""

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let c = cat {
                let rows = c.models.filter { !$0.id.hasPrefix("harness:") && !$0.id.hasPrefix("harness-direct:") }
                Section {
                    if rows.isEmpty { Text("None yet.").foregroundStyle(.secondary) }
                    ForEach(rows) { m in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(m.display)
                                Text([m.group, m.context.map { "\($0 / 1000)k context" } ?? "",
                                      m.isReady ? "" : "needs a key"].filter { !$0.isEmpty }
                                        .joined(separator: " · "))
                                    .font(.caption).foregroundStyle(m.isReady ? Color.secondary : Color.orange)
                            }
                            Spacer()
                            if m.id == c.default {
                                Text("default").font(.caption2.weight(.semibold)).foregroundStyle(.tint)
                            }
                        }
                        .contextMenu {
                            if m.id != c.default {
                                Button("Make default") { Task { await act("default model set") {
                                    try await state.requireServer().setDefaultModel(m.id)
                                } } }
                            }
                            if m.provider != "local" {
                                Button("Remove from the list", role: .destructive) { forgetting = m }
                            }
                        }
                        .swipeActions {
                            if m.provider != "local" {
                                Button("Remove", role: .destructive) { forgetting = m }
                            }
                        }
                    }
                } header: {
                    Text("Models")
                } footer: {
                    Text("The local server, coding CLIs you are signed into, OpenAI-compatible servers. "
                         + "Touch and hold one to make it the default or remove it.")
                }

                Section {
                    ForEach(c.providers.keys.sorted(), id: \.self) { pid in
                        let pv = c.providers[pid]!
                        VStack(alignment: .leading, spacing: 6) {
                            Text(pv.label ?? pid).font(.body.weight(.medium))
                            Text([pv.kind ?? "", pv.base_url?.replacingOccurrences(
                                    of: "^https?://", with: "", options: .regularExpression) ?? ""]
                                    .filter { !$0.isEmpty }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            if let kn = pv.key, !kn.isEmpty {
                                Text(kn + (c.keysSet.contains(kn) ? " · key set" : " · no key"))
                                    .font(.caption.monospaced()).foregroundStyle(.secondary)
                                SecretEntry(placeholder: c.keysSet.contains(kn) ? "Replace the key" : "Paste the key",
                                            buttonTitle: "Save key") { v in
                                    do {
                                        try await state.requireServer().saveSecret(name: kn, value: v)
                                        note = "key saved"; Haptics.success(); await load()
                                        return true
                                    } catch { note = error.localizedDescription; return false }
                                }
                            } else {
                                Text("No key needed").font(.caption).foregroundStyle(.secondary)
                            }
                            HStack {
                                Button(fetching == pid ? "Asking…" : "Fetch models") { Task { await fetch(pid) } }
                                    .buttonStyle(.bordered).controlSize(.small)
                                    .disabled(fetching != nil)
                                if let u = pv.keys_url, let url = URL(string: u) {
                                    Link("Get a key", destination: url).font(.caption)
                                }
                            }
                        }
                        .padding(.vertical, 3)
                    }
                } header: {
                    Text("Their providers")
                }

                Section {
                    TextField("New provider id, e.g. my-server", text: $newID)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    TextField("Label", text: $newLabel)
                    Picker("Wire format", selection: $newKind) {
                        Text("OpenAI-compatible").tag("openai"); Text("Anthropic").tag("anthropic")
                    }
                    TextField("Base URL, e.g. http://server:8000/v1", text: $newBase)
                        .keyboardType(.URL).autocorrectionDisabled().textInputAutocapitalization(.never)
                    TextField("Key name (blank if none)", text: $newKey)
                        .autocorrectionDisabled().textInputAutocapitalization(.characters)
                    Button("Add provider") {
                        let id = newID.trimmingCharacters(in: .whitespaces)
                        Task { await act("provider added") {
                            try await state.requireServer().addClassicProvider(
                                id: id, label: newLabel.trimmingCharacters(in: .whitespaces).isEmpty ? id : newLabel,
                                kind: newKind, baseURL: newBase.trimmingCharacters(in: .whitespaces),
                                keyName: newKey.trimmingCharacters(in: .whitespaces))
                            newID = ""; newLabel = ""; newBase = ""; newKey = ""
                        } }
                    }
                    .disabled(newID.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Add a provider")
                } footer: {
                    Text("Anything speaking the OpenAI API works — vLLM, SGLang, a colleague's server.")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Orbit's own models")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Remove this model from the list?", isPresented: Binding(
            get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }), titleVisibility: .visible) {
            if let m = forgetting {
                Button("Remove \(m.display)", role: .destructive) {
                    Task { await act("removed") { try await state.requireServer().forgetModel(m.id) } }
                    forgetting = nil
                }
            }
            Button("Cancel", role: .cancel) { forgetting = nil }
        }
    }

    private func load() async {
        do { cat = try await state.requireServer().modelCatalogue(); error = nil }
        catch { self.error = error.localizedDescription }
    }

    private func act(_ done: String, _ work: () async throws -> Void) async {
        do { try await work(); note = done; Haptics.success(); await load(); await state.loadModels() }
        catch { note = error.localizedDescription }
    }

    private func fetch(_ pid: String) async {
        fetching = pid
        defer { fetching = nil }
        do {
            let n = try await state.requireServer().fetchProviderModels(pid)
            note = "\(n) models from \(pid)"
            await load(); await state.loadModels()
        } catch { note = String(error.localizedDescription.prefix(140)) }
    }
}
