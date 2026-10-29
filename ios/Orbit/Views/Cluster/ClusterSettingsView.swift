import SwiftUI

/// What the Mac watches on the cluster and tells you about, when it reads the slow numbers again by
/// itself, and the lab's project folder. Saved together with the Save button, as on the Mac.
struct ClusterSettingsView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterStore
    @State private var draft: ClusterConfig?
    @State private var refreshTime = Date()
    @State private var busy = false
    @State private var note: String?

    private static let spans: [(Int, String)] = [(6, "6 hours"), (12, "12 hours"), (24, "day"), (48, "2 days"), (168, "week")]

    var body: some View {
        Form {
            if draft != nil {
                watchSection
                notifySection
                refreshSection
                projectSection
                Section {
                    Button(busy ? "Saving…" : "Save") { Task { await save() } }
                        .disabled(!changed || busy)
                }
            } else {
                LoadingRow(text: "Reading the settings")
            }
        }
        .navigationTitle("Watching and settings")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .task { load() }
    }

    // ------------------------------------------------------------ sections

    private var watchSection: some View {
        Section {
            Toggle("Watch the queue", isOn: bind(\.watch))
            Toggle("Explain failures", isOn: bind(\.explain))
        } footer: {
            Text("Watching looks every 90 seconds while something of yours is queued or running, and every 10 minutes "
                 + "otherwise, through one shared login. Explain failures adds a short plain-language reading of why a "
                 + "job failed, written by Orbit's helper model from the cluster's own diagnosis.")
        }
    }

    private var notifySection: some View {
        Section {
            ForEach(ClusterConfig.notifyKinds, id: \.key) { k in
                Toggle(k.label, isOn: Binding(
                    get: { draft?.notify[k.key] ?? false },
                    set: { draft?.notify[k.key] = $0 }))
            }
        } header: {
            Text("Tell me when")
        } footer: {
            Text("Notices come to this phone as well as the Mac.")
        }
    }

    private var refreshSection: some View {
        Section {
            Toggle("Read the slow numbers by itself", isOn: bind(\.refreshOn))
            if draft?.refreshOn == true {
                Picker("Every", selection: bind(\.refreshEveryHours)) {
                    ForEach(Self.spans, id: \.0) { Text($0.1).tag($0.0) }
                    if let h = draft?.refreshEveryHours, !Self.spans.contains(where: { $0.0 == h }) {
                        Text("\(h) hours").tag(h)
                    }
                }
                if (draft?.refreshEveryHours ?? 24) >= 24 {
                    DatePicker("At", selection: $refreshTime, displayedComponents: .hourAndMinute)
                }
                Toggle("Measure my folders again", isOn: bind(\.remeasure))
            }
        } header: {
            Text("Read again by itself")
        } footer: {
            Text("Quotas, disk sizes, limits, GPUs and usage history are read again then, quietly. Measuring my folders "
                 + "covers home, scratch, my project folder and folders you looked inside, only the ones that changed. "
                 + "The lab-wide count and other people's folders are never measured by themselves.")
        }
    }

    private var projectSection: some View {
        Section {
            TextField("/path/to/project/yourlab", text: bind(\.projectDir))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .font(.callout.monospaced())
        } header: {
            Text("Project folder")
        } footer: {
            Text("The lab's shared folder on the cluster. It adds the shared-disk bar and the folder views.")
        }
    }

    // ------------------------------------------------------------ editing

    private func bind<T>(_ path: WritableKeyPath<ClusterConfig, T>) -> Binding<T> {
        Binding(get: { draft![keyPath: path] }, set: { draft?[keyPath: path] = $0 })
    }

    private var saved: ClusterConfig? { store.look?.config }

    private var changed: Bool {
        guard let d = draft, let s = saved else { return false }
        return d.watch != s.watch || d.explain != s.explain || d.notify != s.notify
            || d.refreshOn != s.refreshOn || d.refreshEveryHours != s.refreshEveryHours
            || d.remeasure != s.remeasure || d.projectDir != s.projectDir.trimmingCharacters(in: .whitespaces)
            || timeText != s.refreshAt
    }

    private var timeText: String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: refreshTime)
        return String(format: "%02d:%02d", c.hour ?? 3, c.minute ?? 0)
    }

    private func load() {
        guard draft == nil, let c = store.look?.config else { return }
        draft = c
        let parts = c.refreshAt.split(separator: ":").compactMap { Int($0) }
        if parts.count == 2 {
            refreshTime = Calendar.current.date(bySettingHour: parts[0], minute: parts[1], second: 0, of: .now) ?? .now
        }
    }

    private func save() async {
        guard let d = draft, let server = state.server else { return }
        busy = true
        defer { busy = false }
        let body: [String: Any] = [
            "watch": d.watch, "explain": d.explain, "project_dir": d.projectDir.trimmingCharacters(in: .whitespaces),
            "notify": d.notify,
            "refresh": ["on": d.refreshOn, "every_h": d.refreshEveryHours, "at": timeText, "remeasure": d.remeasure]]
        do {
            let look = try await server.clusterSaveConfig(body)
            store.look = look
            draft = look.config
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
