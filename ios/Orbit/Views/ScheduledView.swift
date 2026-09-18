import SwiftUI

/// Everything set to happen later: messages waiting for their time in any chat,
/// and the tasks the Mac runs on a timetable.
struct ScheduledView: View {
    @EnvironmentObject var state: AppState
    @State private var messages: [ScheduledMessage] = []
    @State private var tasks: [ScheduledTask] = []
    @State private var loading = true
    @State private var failed: String?
    @State private var editingMessage: ScheduledMessage?
    @State private var editingTask: ScheduledTask?
    @State private var toast: String?
    /// "Running now": answers, queued messages and shell jobs (Views/Tasks/RunningNow.swift).
    @StateObject private var running = RunningNowModel()
    /// A task waiting for "Run it now?" to be confirmed.
    @State private var confirmRun: ScheduledTask?

    var body: some View {
        NavigationStack {
            List {
                RunningNowSection(model: running)

                Section {
                    if messages.isEmpty && !loading {
                        Text("None. Hold the send button, or tap Send later above the message box.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(messages) { m in
                        messageRow(m)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) { Task { await remove(m) } } label: {
                                    Label("Remove", systemImage: "trash")
                                }
                                Button { editingMessage = m } label: {
                                    Label("Edit", systemImage: "pencil")
                                }.tint(.blue)
                            }
                            .swipeActions(edge: .leading) {
                                Button { Task { await sendNow(m) } } label: {
                                    Label("Send now", systemImage: "paperplane")
                                }.tint(.green)
                            }
                            .contextMenu { messageMenu(m) }
                    }
                } header: {
                    Text("Messages")
                }

                Section {
                    if tasks.isEmpty && !loading {
                        Text("No tasks yet. A task is a prompt your Mac runs on its own — "
                             + "every morning, every hour, or once.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(tasks) { t in
                        Button { editingTask = t } label: { taskRow(t) }
                            .buttonStyle(.plain)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) { Task { await deleteTask(t) } } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                            .swipeActions(edge: .leading) {
                                Button { confirmRun = t } label: {
                                    Label("Run now", systemImage: "play")
                                }.tint(.green)
                            }
                            .contextMenu { taskMenu(t) }
                    }
                } header: {
                    Text("Tasks")
                }

                ClusterJobsSection()
            }
            .listStyle(.insetGrouped)
            .overlay {
                if loading && messages.isEmpty && tasks.isEmpty { ProgressView() }
            }
            .navigationTitle("Scheduled")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { editingTask = ScheduledTask() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("New task")
                }
            }
            .refreshable { await load(); await running.load(state) }
            // what is running is kept current only while this tab is on screen
            .task(id: state.pairing?.url ?? "") { await running.poll(state, every: 5) }
            // the pairing can land after this screen first appears. Not tied to the
            // view's own task: switching tabs mid-request must not cancel the read
            .task(id: "\(state.pairing?.url ?? "")|\(state.reachable == true)") {
                Task { await load() }
                if state.models.isEmpty { Task { await state.loadModels() } }
            }
            .sheet(item: $editingMessage) { m in
                QueuedMessageEditor(original: .init(text: m.text, at: m.date,
                                                    rep: Repeat(server: m.repeatKind),
                                                    model: m.model ?? ""),
                                    chatTitle: m.chatTitle) { r in
                    await save(m, r)
                }
            }
            .sheet(item: $editingTask) { t in
                TaskEditor(task: t) { job in await saveTask(job) } onRun: {
                    await runTask(t)
                } onDelete: {
                    await deleteTask(t)
                }
            }
            .overlay(alignment: .bottom) {
                if let toast {
                    Text(toast).font(.footnote.weight(.medium))
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(.thinMaterial, in: .capsule)
                        .padding(.bottom, 12)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .confirmationDialog("Run “\(confirmRun.map(Self.taskTitle) ?? "")” now?",
                                isPresented: Binding(get: { confirmRun != nil }, set: { if !$0 { confirmRun = nil } }),
                                titleVisibility: .visible, presenting: confirmRun) { t in
                Button("Run now") { Task { await runTask(t) } }
                Button("Cancel", role: .cancel) {}
            } message: { t in
                Text(t.sid != nil ? "It runs in its chat, as if it were its time."
                                  : "It runs in a new chat, as if it were its time.")
            }
            .alert("Couldn't do that", isPresented: Binding(
                get: { failed != nil }, set: { if !$0 { failed = nil } })) {
                Button("OK") { failed = nil }
            } message: { Text(failed ?? "") }
        }
    }

    // ------------------------------------------------------------ rows

    private func messageRow(_ m: ScheduledMessage) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Button {
                state.tab = "chats"
                state.deepLink = m.sid
            } label: {
                HStack(spacing: 4) {
                    Text(m.chatTitle).font(.footnote.weight(.semibold)).lineLimit(1)
                    Image(systemName: "chevron.right").font(.caption2)
                }
                .foregroundStyle(.tint)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Open chat \(m.chatTitle)")

            Text(m.text.isEmpty ? "(attachments only)" : m.text)
                .font(.callout).lineLimit(4)

            HStack(spacing: 6) {
                if m.missed {
                    Label("missed · \(When.describe(m.date))", systemImage: "clock.badge.exclamationmark")
                        .foregroundStyle(.orange)
                } else {
                    Label(When.describe(m.date), systemImage: "clock")
                }
                if let r = m.repeatKind, !r.isEmpty {
                    Label(Repeat(server: r).label.lowercased(), systemImage: "repeat")
                }
            }
            .font(.caption).foregroundStyle(.secondary)
            .labelStyle(.titleAndIcon)

            HStack(spacing: 6) {
                Image(systemName: "cpu")
                Text(state.modelLabel(m.model)
                     ?? state.modelLabel(m.chat_model).map { "chat's model · \($0)" }
                     ?? "chat's model")
                    .lineLimit(1)
                if !m.attachments.isEmpty {
                    Label("\(m.attachments.count)", systemImage: "paperclip").labelStyle(.titleAndIcon)
                }
            }
            .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }

    @ViewBuilder
    private func messageMenu(_ m: ScheduledMessage) -> some View {
        Button { editingMessage = m } label: { Label("Edit", systemImage: "pencil") }
        Button { Task { await sendNow(m) } } label: { Label("Send now", systemImage: "paperplane") }
        Button {
            state.tab = "chats"; state.deepLink = m.sid
        } label: { Label("Open chat", systemImage: "bubble.left") }
        Divider()
        Button(role: .destructive) { Task { await remove(m) } } label: {
            Label("Remove", systemImage: "trash")
        }
    }

    static func taskTitle(_ t: ScheduledTask) -> String {
        t.name.isEmpty ? String(t.prompt.prefix(40)) : t.name
    }

    private func taskRow(_ t: ScheduledTask) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: t.isLimitResume ? "hourglass" : t.enabled ? "calendar.badge.clock" : "pause.circle")
                .font(.title3)
                .foregroundStyle(t.isLimitResume ? Color.orange : t.enabled ? Color.accentColor : .secondary)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                if t.isLimitResume {
                    Text("Continue after usage limit")
                        .font(.caption2.weight(.semibold)).foregroundStyle(.orange)
                }
                Text(t.isLimitResume ? t.limitResumeChat : Self.taskTitle(t))
                    .font(.body).lineLimit(2)
                    .foregroundStyle(t.enabled ? .primary : .secondary)
                Text(t.isLimitResume && t.enabled
                     ? "carries on by itself " + (t.at_ts.map { When.describe(Date(timeIntervalSince1970: $0)) } ?? "when it resets")
                     : t.scheduleDescription)
                    .font(.caption).foregroundStyle(.secondary)
                if t.isLimitResume, let why = t.why, !why.isEmpty {
                    Text(why).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                }
                Text(taskFacts(t).joined(separator: " · "))
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(3)
                if let last = t.last_run {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Image(systemName: t.last_ok == false ? "xmark.circle.fill" : "checkmark.circle.fill")
                            .foregroundStyle(t.last_ok == false ? .red : .green)
                        Text("ran \(When.describe(Date(timeIntervalSince1970: last)))"
                             + (t.last_result.map(Self.plain).flatMap { $0.isEmpty ? nil : " — " + $0 } ?? ""))
                            .lineLimit(2)
                    }
                    .font(.caption2).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 3)
        .contentShape(Rectangle())
    }

    /// Next run (or paused, or finished), stops by, model, where it runs, agent —
    /// the facts the Mac's task list gives under each task's name.
    private func taskFacts(_ t: ScheduledTask) -> [String] {
        var out: [String] = []
        if let next = t.nextDescription { out.append(t.enabled ? "next: \(next)" : next) }
        else if t.enabled { out.append("finished") }
        if let s = t.stop_at, !s.isEmpty { out.append("stops by \(s)") }
        out.append("on " + (state.modelLabel(t.model) ?? (t.sid != nil ? "its chat's model" : "the default model")))
        if let sid = t.sid {
            let title = state.chats.first { $0.id == sid }?.displayTitle
            out.append(title.map { "in its chat “\($0)”" } ?? "in its chat")
        } else {
            out.append("new chat each run")
        }
        if let p = t.project, !p.isEmpty {
            out.append("project " + (state.projects.first { $0.id == p }?.name ?? p))
        }
        if let a = t.agent, !a.isEmpty { out.append("agent \(a)") }
        if t.isLimitResume, let n = t.attempt, n > 0 { out.append("attempt \(n + 1)") }
        return out
    }

    @ViewBuilder
    private func taskMenu(_ t: ScheduledTask) -> some View {
        Button { editingTask = t } label: { Label("Edit", systemImage: "pencil") }
        Button { confirmRun = t } label: { Label("Run now", systemImage: "play") }
        if let sid = t.last_sid ?? t.sid {
            Button { state.tab = "chats"; state.deepLink = sid } label: {
                Label("Open its chat", systemImage: "bubble.left")
            }
        }
        Button {
            Task { await saveTask(["id": t.id, "prompt": t.prompt, "enabled": !t.enabled]) }
        } label: {
            Label(t.enabled ? "Pause" : "Resume", systemImage: t.enabled ? "pause" : "play.circle")
        }
        Divider()
        Button(role: .destructive) { Task { await deleteTask(t) } } label: {
            Label("Delete", systemImage: "trash")
        }
    }

    /// A last result is Markdown; a one-line summary reads better without the marks.
    static func plain(_ s: String) -> String {
        s.replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespaces)
    }

    // ------------------------------------------------------------ actions

    private func load() async {
        guard let server = state.server else { loading = false; return }
        loading = true
        defer { loading = false }
        do {
            let r = try await server.scheduled()
            messages = r.messages.sorted { $0.at < $1.at }
            tasks = r.tasks
        } catch { failed = error.localizedDescription }
    }

    private func flash(_ text: String) {
        withAnimation { toast = text }
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            withAnimation { toast = nil }
        }
    }

    private func remove(_ m: ScheduledMessage) async {
        guard let server = state.server else { return }
        do {
            try await server.queue(sid: m.sid, op: "remove", ["id": m.itemID])
            messages.removeAll { $0.id == m.id }
            await refreshOpenQueue(m.sid)
        } catch { failed = error.localizedDescription }
    }

    private func sendNow(_ m: ScheduledMessage) async {
        guard let server = state.server else { return }
        do {
            try await server.queue(sid: m.sid, op: "now", ["id": m.itemID])
            flash("Sent to “\(m.chatTitle)”")
            await load()
            await refreshOpenQueue(m.sid)
        } catch { failed = error.localizedDescription }
    }

    private func save(_ m: ScheduledMessage, _ r: QueuedMessageEditor.Result) async {
        guard let server = state.server else { return }
        let textChanged = r.text != m.text
        let whenChanged = r.at?.timeIntervalSince1970 != m.at || r.rep != Repeat(server: m.repeatKind)
        let modelChanged = r.model != (m.model ?? "")
        guard textChanged || whenChanged || modelChanged else { return }
        do {
            try await server.updateQueued(sid: m.sid, id: m.itemID,
                                          text: textChanged ? r.text : nil,
                                          at: whenChanged ? .some(r.at) : nil,
                                          repeat: whenChanged ? r.rep : nil,
                                          model: modelChanged ? r.model : nil)
        } catch { failed = error.localizedDescription }
        await load()
        await refreshOpenQueue(m.sid)
    }

    private func refreshOpenQueue(_ sid: String) async {
        if state.openChat?.sid == sid { await state.loadQueue() }
    }

    private func saveTask(_ job: [String: Any]) async {
        guard let server = state.server else { return }
        do {
            try await server.saveTask(job)
            await load()
        } catch { failed = error.localizedDescription }
    }

    private func runTask(_ t: ScheduledTask) async {
        guard let server = state.server, !t.id.isEmpty else { return }
        do {
            try await server.runTask(t.id)
            flash("“\(Self.taskTitle(t))” is running on your Mac")
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            await load()
        } catch { failed = error.localizedDescription }
    }

    private func deleteTask(_ t: ScheduledTask) async {
        guard let server = state.server, !t.id.isEmpty else { return }
        do {
            try await server.deleteTask(t.id)
            tasks.removeAll { $0.id == t.id }
        } catch { failed = error.localizedDescription }
    }
}

/// Create or change a scheduled task.
struct TaskEditor: View {
    let task: ScheduledTask
    var onSave: ([String: Any]) async -> Void
    var onRun: () async -> Void
    var onDelete: () async -> Void

    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var prompt = ""
    @State private var every = "daily"
    @State private var time = Date.now
    @State private var once = Date.now
    @State private var n = 30
    @State private var weekday = 0
    @State private var model = ""
    @State private var enabled = true
    @State private var saving = false
    @State private var confirmDelete = false
    // stops by, where it runs, project and agent — as the Mac's task form has them
    @State private var stopBy = false
    @State private var stopAt = Date.now
    @State private var runsIn = ""
    @State private var project = ""
    @State private var agent = ""
    @State private var agents: [String] = []
    @State private var confirmRun = false

    /// Chats a task can run in: yours with something in them, not other agents' sessions.
    private var runnableChats: [ChatSummary] {
        var list = Array(state.chats.filter { $0.external != true && $0.n > 0 }
                                    .sorted { $0.mtime > $1.mtime }.prefix(60))
        if let sid = task.sid, !list.contains(where: { $0.id == sid }),
           let c = state.chats.first(where: { $0.id == sid }) {
            list.insert(c, at: 0)
        }
        return list
    }

    private var isNew: Bool { task.id.isEmpty }

    static let kinds: [(String, String)] = [("once", "Once"), ("minutes", "Every N minutes"),
                                            ("hours", "Every N hours"), ("daily", "Every day"),
                                            ("weekly", "Every week")]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $name)
                    TextField("What should it do?", text: $prompt, axis: .vertical).lineLimit(4...14)
                } header: { Text("Task") }

                Section {
                    Picker("Repeat", selection: $every) {
                        ForEach(Self.kinds, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    switch every {
                    case "once":
                        DatePicker("When", selection: $once, displayedComponents: [.date, .hourAndMinute])
                    case "minutes":
                        Stepper("Every \(n) minutes", value: $n, in: 2...1440, step: n < 10 ? 1 : 5)
                    case "hours":
                        Stepper(n == 1 ? "Every hour" : "Every \(n) hours", value: $n, in: 1...168)
                    case "weekly":
                        Picker("Day", selection: $weekday) {
                            ForEach(0..<7, id: \.self) { Text(ScheduledTask.weekdays[$0]).tag($0) }
                        }
                        DatePicker("Time", selection: $time, displayedComponents: .hourAndMinute)
                    default:
                        DatePicker("Time", selection: $time, displayedComponents: .hourAndMinute)
                    }
                    Toggle("Enabled", isOn: $enabled)
                } header: { Text("When") }

                Section {
                    Toggle("Stop by a time", isOn: $stopBy)
                    if stopBy {
                        DatePicker("Stop by", selection: $stopAt, displayedComponents: .hourAndMinute)
                    }
                } footer: {
                    Text("Optional: the run paces itself to finish by then, and wraps up with a summary if time runs out.")
                }

                Section {
                    Picker("Runs in", selection: $runsIn) {
                        Text("A new chat each time").tag("")
                        if !runsIn.isEmpty, !runnableChats.contains(where: { $0.id == runsIn }) {
                            Text("This task's chat").tag(runsIn)
                        }
                        ForEach(runnableChats) { c in
                            Text(c.displayTitle).lineLimit(1).tag(c.id)
                        }
                    }
                    .pickerStyle(.navigationLink)
                    if !state.projects.isEmpty || !project.isEmpty {
                        Picker("Project", selection: $project) {
                            Text("None").tag("")
                            if !project.isEmpty, !state.projects.contains(where: { $0.id == project }) {
                                Text(project).tag(project)
                            }
                            ForEach(state.projects) { p in Text(p.name).tag(p.id) }
                        }
                    }
                    if !agents.isEmpty || !agent.isEmpty {
                        Picker("Agent", selection: $agent) {
                            Text("None").tag("")
                            if !agent.isEmpty, !agents.contains(agent) { Text(agent).tag(agent) }
                            ForEach(agents, id: \.self) { Text($0).tag($0) }
                        }
                    }
                } header: {
                    Text("Where it runs")
                } footer: {
                    Text(runsIn.isEmpty ? "Each run starts a chat of its own, where its result lands."
                                        : "Each run continues that chat, with its history and context.")
                }

                Section {
                    ModelChoicePicker(defaultLabel: runsIn.isEmpty ? "The default model" : "The chat's model",
                                      selection: $model)
                } footer: {
                    if !isNew, let r = task.last_result, !r.isEmpty {
                        Text("Last result: " + ScheduledView.plain(r).prefix(300))
                    }
                }

                if !isNew {
                    Section {
                        Button { confirmRun = true } label: {
                            Label("Run now", systemImage: "play")
                        }
                        Button(role: .destructive) { confirmDelete = true } label: {
                            Label("Delete task", systemImage: "trash")
                        }
                    }
                }
            }
            .navigationTitle(isNew ? "New task" : "Edit task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("Save") {
                            saving = true
                            let job = changes()
                            Task { await onSave(job); saving = false; dismiss() }
                        }
                        .disabled(prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .confirmationDialog("Run “\(ScheduledView.taskTitle(task))” now?", isPresented: $confirmRun,
                                titleVisibility: .visible) {
                Button("Run now") { Task { await onRun(); dismiss() } }
                Button("Cancel", role: .cancel) {}
            }
            .confirmationDialog("Delete this task?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await onDelete(); dismiss() } }
                Button("Cancel", role: .cancel) {}
            }
            .onAppear(perform: fill)
            .task {
                guard let server = state.server else { return }
                if let a = try? await server.agents() { agents = a.agents.map(\.name) }
            }
        }
    }

    private static let hhmm: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    private func fill() {
        name = task.name
        prompt = task.prompt
        every = Self.kinds.contains { $0.0 == task.every } ? task.every : "daily"
        if let at = task.at, let d = Self.hhmm.date(from: at),
           let t = Calendar.current.date(bySettingHour: Calendar.current.component(.hour, from: d),
                                         minute: Calendar.current.component(.minute, from: d),
                                         second: 0, of: .now) {
            time = t
        } else if let nine = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: .now) {
            time = nine
        }
        once = task.at_ts.map { Date(timeIntervalSince1970: $0) } ?? Date.now.addingTimeInterval(3600)
        n = Int(task.n ?? (task.every == "hours" ? 6 : 30))
        weekday = task.weekday ?? 0
        model = task.model ?? ""
        enabled = task.enabled
        stopBy = !(task.stop_at ?? "").isEmpty
        if let s = task.stop_at, let d = Self.hhmm.date(from: s),
           let t = Calendar.current.date(bySettingHour: Calendar.current.component(.hour, from: d),
                                         minute: Calendar.current.component(.minute, from: d),
                                         second: 0, of: .now) {
            stopAt = t
        } else if let six = Calendar.current.date(bySettingHour: 6, minute: 0, second: 0, of: .now) {
            stopAt = six
        }
        runsIn = task.sid ?? ""
        project = task.project ?? ""
        agent = task.agent ?? ""
    }

    /// Only what changed, plus the id and prompt (a Mac that predates partial
    /// saves refuses a job without its prompt). A new task sends everything.
    private func changes() -> [String: Any] {
        // an empty value removes the setting on the Mac
        let stop = stopBy ? Self.hhmm.string(from: stopAt) : ""
        var full: [String: Any] = ["name": name, "prompt": prompt, "every": every, "enabled": enabled,
                                   "model": model, "stop_at": stop, "sid": runsIn,
                                   "project": project, "agent": agent]
        switch every {
        case "once": full["at_ts"] = once.timeIntervalSince1970
        case "minutes", "hours": full["n"] = n
        case "weekly": full["weekday"] = weekday; full["at"] = Self.hhmm.string(from: time)
        default: full["at"] = Self.hhmm.string(from: time)
        }
        if isNew { return full }
        var job: [String: Any] = ["id": task.id, "prompt": prompt]
        if name != task.name { job["name"] = name }
        if every != task.every { job["every"] = every }
        if enabled != task.enabled { job["enabled"] = enabled }
        if model != (task.model ?? "") { job["model"] = model }
        if stop != (task.stop_at ?? "") { job["stop_at"] = stop }
        if runsIn != (task.sid ?? "") { job["sid"] = runsIn }
        if project != (task.project ?? "") { job["project"] = project }
        if agent != (task.agent ?? "") { job["agent"] = agent }
        // when it runs: send the whole of it if any part moved, so the Mac never
        // pairs a new kind with an old time
        let whenKeys = ["at", "at_ts", "n", "weekday"]
        let moved = every != task.every
            || (full["at"] as? String).map { $0 != task.at } ?? false
            || (full["at_ts"] as? Double).map { abs($0 - (task.at_ts ?? 0)) > 30 } ?? false
            || (full["n"] as? Int).map { Double($0) != task.n } ?? false
            || (full["weekday"] as? Int).map { $0 != task.weekday } ?? false
        if moved {
            job["every"] = every
            for k in whenKeys { if let v = full[k] { job[k] = v } }
        }
        return job
    }
}
