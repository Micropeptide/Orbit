import SwiftUI

/// What is running in the background right now, kept current while on screen:
/// chats answering (and what each is doing), messages waiting in a queue, and
/// shell commands a model left running — each with a way to open or stop it.
/// Claude Code's `/tasks`, as the Mac shows it.
@MainActor
final class RunningNowModel: ObservableObject {
    @Published var items: [BackgroundTask] = []
    @Published var now: Double = Date.now.timeIntervalSince1970
    @Published var loaded = false
    @Published var failed: String?
    /// Stopped or removed here, so the row says so until the Mac's list catches up.
    @Published var stopped: Set<String> = []

    func load(_ state: AppState) async {
        guard let server = state.server else { return }
        do {
            let r = try await server.backgroundTasks()
            items = r.items
            now = r.now
            failed = nil
            stopped.formIntersection(Set(r.items.map(\.id)))
        } catch {
            failed = error.localizedDescription
        }
        loaded = true
    }

    /// Every few seconds until the view goes away.
    func poll(_ state: AppState, every seconds: Double = 4) async {
        while !Task.isCancelled {
            await load(state)
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
        }
    }
}

/// The rows, as one list section. Used at the top of Scheduled and in the /tasks sheet.
struct RunningNowSection: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var model: RunningNowModel
    /// Called after opening a chat, so a sheet can close itself.
    var onOpen: () -> Void = {}
    /// Hide the section's own "nothing running" line.
    var quietWhenEmpty = false
    @State private var confirming: BackgroundTask?
    @State private var showing: BackgroundTask?

    var body: some View {
        Section {
            if !model.loaded {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Checking…").font(.footnote).foregroundStyle(.secondary)
                }
            } else if let e = model.failed, model.items.isEmpty {
                Label(e, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.orange)
            } else if model.items.isEmpty {
                if !quietWhenEmpty {
                    Text("Nothing is running in the background.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            ForEach(model.items) { t in
                row(t)
                    .swipeActions(edge: .trailing) {
                        if t.canStop, !model.stopped.contains(t.id) {
                            Button(role: .destructive) { confirming = t } label: {
                                Label(t.kind == .queued ? "Remove" : "Stop",
                                      systemImage: t.kind == .queued ? "trash" : "stop.fill")
                            }
                        }
                    }
                    .contextMenu {
                        if let sid = t.sid {
                            Button { open(sid) } label: { Label("Open chat", systemImage: "bubble.left") }
                        }
                        if t.canStop, !model.stopped.contains(t.id) {
                            Button(role: .destructive) { confirming = t } label: {
                                Label(t.kind == .queued ? "Remove" : "Stop",
                                      systemImage: t.kind == .queued ? "trash" : "stop.fill")
                            }
                        }
                    }
            }
        } header: {
            HStack {
                Text("Running now")
                if !model.items.isEmpty { Text("\(model.items.count)").foregroundStyle(.secondary) }
            }
        }
        .sheet(item: $showing) { t in
            TaskOutputSheet(task: t) { sid in open(sid) }
        }
        .confirmationDialog(confirmTitle, isPresented: Binding(
            get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
                            titleVisibility: .visible, presenting: confirming) { t in
            Button(t.kind == .queued ? "Remove message" : "Stop", role: .destructive) {
                Task {
                    if await state.stopBackground(t) {
                        model.stopped.insert(t.id)
                        try? await Task.sleep(nanoseconds: 800_000_000)
                        await model.load(state)
                    }
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: { t in
            Text(t.title)
        }
    }

    private var confirmTitle: String {
        switch confirming?.kind {
        case .queued: return "Remove this queued message?"
        case .answer: return "Stop this answer?"
        default: return "Stop this command?"
        }
    }

    private func row(_ t: BackgroundTask) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: t.symbol)
                .foregroundStyle(tint(t))
                .frame(width: 24)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(t.kindLabel)
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(tint(t).opacity(0.15), in: .capsule)
                        .foregroundStyle(tint(t))
                    if t.kind == .answer, !model.stopped.contains(t.id) {
                        ProgressView().controlSize(.mini)
                    }
                }
                Text(t.title.isEmpty ? t.rawID : t.title)
                    .font(t.kind == .shell ? .callout.monospaced() : .callout)
                    .lineLimit(2)
                let detail = t.detail(now: model.now)
                if !detail.isEmpty {
                    Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                }
                if model.stopped.contains(t.id) {
                    Text(t.kind == .queued ? "removed" : "stopped")
                        .font(.caption.weight(.medium)).foregroundStyle(.orange)
                }
            }
            Spacer(minLength: 0)
            if t.kind == .background {
                // Claude's task list: open one to see what it has written so far
                Button { showing = t } label: {
                    Text("Open").font(.caption.weight(.semibold))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityLabel("Show the output of \(t.title)")
            } else if let sid = t.sid {
                Button { open(sid) } label: {
                    Text("Open").font(.caption.weight(.semibold))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityLabel("Open chat \(t.title)")
            }
        }
        .padding(.vertical, 2)
    }

    private func tint(_ t: BackgroundTask) -> Color {
        switch t.kind {
        case .answer: return .accentColor
        case .queued: return .purple
        case .shell: return .teal
        case .background: return .indigo
        case .other: return .secondary
        }
    }

    private func open(_ sid: String) {
        onOpen()
        state.tab = "chats"
        state.deepLink = sid
    }
}

/// `/tasks`: background work in a sheet of its own. Present it by setting
/// `state.work.showTasks` (or `state.presentTasks()`); RootView shows it.
struct TasksSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = RunningNowModel()

    var body: some View {
        NavigationStack {
            List {
                RunningNowSection(model: model, onOpen: { dismiss() })
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Background tasks")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        dismiss()
                        state.tab = "scheduled"
                    } label: { Text("Scheduled") }
                }
            }
            .refreshable { await model.load(state) }
            .task { await model.poll(state, every: 3) }
        }
        .presentationDetents([.medium, .large])
    }
}
