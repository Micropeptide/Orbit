import SwiftUI

/// Pick when the draft goes out: a preset, or any date and time, once or repeating.
struct SendLaterSheet: View {
    var onSchedule: (Date, Repeat) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date.now.addingTimeInterval(3600)
    @State private var rep: Repeat = .once

    struct Preset { let label: String; let date: Date }

    /// In 30 minutes, in an hour, this evening at 21:00 (while it is still to
    /// come), tomorrow at 9:00.
    static func presets(now: Date = .now) -> [Preset] {
        let cal = Calendar.current
        var out = [Preset(label: "in 30 minutes", date: now.addingTimeInterval(30 * 60)),
                   Preset(label: "in 1 hour", date: now.addingTimeInterval(3600))]
        if let evening = cal.date(bySettingHour: 21, minute: 0, second: 0, of: now),
           evening.timeIntervalSince(now) > 30 * 60 {
            out.append(Preset(label: "this evening at 21:00", date: evening))
        }
        if let tomorrow = cal.date(byAdding: .day, value: 1, to: now),
           let nine = cal.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow) {
            out.append(Preset(label: "tomorrow at 9:00", date: nine))
        }
        return out
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(Self.presets(), id: \.label) { p in
                        Button {
                            onSchedule(p.date, rep)
                            dismiss()
                        } label: {
                            HStack {
                                Text(p.label.prefix(1).uppercased() + p.label.dropFirst())
                                Spacer()
                                Text(When.describe(p.date)).foregroundStyle(.secondary).font(.callout)
                            }
                        }
                    }
                } header: { Text("Quick") }

                Section {
                    DatePicker("When", selection: $date, in: Date.now..., displayedComponents: [.date, .hourAndMinute])
                    Picker("Repeat", selection: $rep) {
                        ForEach(Repeat.allCases) { Text($0.label).tag($0) }
                    }
                    Button {
                        onSchedule(date, rep)
                        dismiss()
                    } label: {
                        Label("Schedule for \(When.describe(date))", systemImage: "clock.badge.checkmark")
                    }
                } header: {
                    Text("Pick a time")
                } footer: {
                    Text("It waits in this chat's queue on your Mac and goes out at that time, "
                         + "even when the phone is off.")
                }
            }
            .navigationTitle("Send later")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
    }
}

/// A model choice for a scheduled message or task. "" is the chat's own model.
struct ModelChoicePicker: View {
    @EnvironmentObject var state: AppState
    var title = "Model"
    var defaultLabel = "Chat's model"
    @Binding var selection: String

    private var grouped: [(String, [ModelInfo])] {
        Dictionary(grouping: state.models.filter { $0.isReady || $0.id == selection }) { $0.group }
            .sorted { $0.key < $1.key }
    }

    var body: some View {
        Picker(title, selection: $selection) {
            Text(defaultLabel).tag("")
            // a model the catalogue no longer lists still shows what is set
            if !selection.isEmpty, !state.models.contains(where: { $0.id == selection }) {
                Text(selection).tag(selection)
            }
            ForEach(grouped, id: \.0) { group, models in
                Section(group) {
                    ForEach(models) { Text($0.display).tag($0.id) }
                }
            }
        }
        .pickerStyle(.navigationLink)
    }
}

/// What the Mac calls a model, as a person would.
extension AppState {
    func modelLabel(_ id: String?) -> String? {
        guard let id, !id.isEmpty else { return nil }
        return models.first { $0.id == catalogueID(for: id) }?.display ?? id
    }
}

/// Change a waiting message: its text, when it goes, how often, which model.
struct QueuedMessageEditor: View {
    struct Result {
        var text: String
        var at: Date?
        var rep: Repeat
        var model: String
    }

    let original: Result
    var chatTitle: String? = nil
    var onSave: (Result) async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var scheduled = false
    @State private var date = Date.now
    @State private var rep: Repeat = .once
    @State private var model = ""
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                if let chatTitle { Section("Chat") { Text(chatTitle) } }
                Section("Message") {
                    TextField("Message", text: $text, axis: .vertical).lineLimit(3...12)
                }
                Section {
                    Toggle("At a set time", isOn: $scheduled)
                    if scheduled {
                        DatePicker("When", selection: $date, displayedComponents: [.date, .hourAndMinute])
                        Picker("Repeat", selection: $rep) {
                            ForEach(Repeat.allCases) { Text($0.label).tag($0) }
                        }
                    }
                } footer: {
                    Text(scheduled ? "Goes out \(When.describe(date))."
                                   : "Waits its turn and goes out after the answers ahead of it.")
                }
                Section {
                    ModelChoicePicker(selection: $model)
                } footer: {
                    Text("Needs a Mac recent enough to keep a model per message.")
                }
            }
            .navigationTitle("Edit message")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("Save") {
                            saving = true
                            let r = Result(text: text, at: scheduled ? date : nil,
                                           rep: scheduled ? rep : .once, model: model)
                            Task { await onSave(r); saving = false; dismiss() }
                        }
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .onAppear {
                text = original.text
                scheduled = original.at != nil
                date = original.at ?? Date.now.addingTimeInterval(3600)
                rep = original.rep
                model = original.model
            }
        }
    }
}

/// The open chat's waiting messages, above the composer, laid out as the Mac's
/// queue box: "Queued · N" in the order they will go, with what the queue is
/// doing, then "Scheduled · N" by time. Drag a queued one to reorder it.
struct QueueStrip: View {
    @EnvironmentObject var state: AppState
    @State private var open = false
    @State private var editing: QueueItem?
    @State private var confirmClear = false
    @State private var confirmStop: QueueItem?

    private var items: [QueueItem] { state.queue.items }
    private var queued: [QueueItem] { items.filter { !$0.isScheduled } }
    private var scheduled: [QueueItem] {
        items.filter(\.isScheduled).sorted { ($0.at ?? 0) < ($1.at ?? 0) }
    }

    /// What the queue is doing, in the web's words.
    private var queueState: String {
        if state.queue.paused == true { return "paused after Stop" }
        return state.queue.running == true ? "each starts when the one before it is answered" : "starting…"
    }

    private var summary: String {
        var bits: [String] = []
        if !queued.isEmpty { bits.append("Queued · \(queued.count)") }
        if !scheduled.isEmpty { bits.append("Scheduled · \(scheduled.count)") }
        if state.queue.paused == true, !queued.isEmpty { bits.append("paused") }
        return bits.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { open.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: queued.isEmpty ? "clock" : "tray.full")
                        .font(.caption)
                    Text(summary).font(.caption.weight(.medium))
                    if !open, let first = queued.first ?? scheduled.first {
                        Text(first.text).font(.caption).lineLimit(1).foregroundStyle(.tertiary)
                    }
                    Spacer()
                    Image(systemName: open ? "chevron.down" : "chevron.up").font(.caption2)
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Waiting messages: \(summary)")

            if open {
                // a few fit as they are; a long queue scrolls in a bounded box
                if items.count <= 3 {
                    sections
                } else {
                    ScrollView { sections }.frame(maxHeight: 260)
                }
            }
        }
        .overlay(Divider(), alignment: .bottom)
        .sheet(item: $editing) { item in
            QueuedMessageEditor(original: .init(text: item.text, at: item.date,
                                                rep: Repeat(server: item.repeatKind),
                                                model: item.model ?? "")) { r in
                await save(item, r)
            }
        }
        .confirmationDialog("Remove all queued messages?", isPresented: $confirmClear,
                            titleVisibility: .visible) {
            Button("Remove \(queued.count) queued", role: .destructive) {
                Task { await state.clearQueued() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Scheduled ones stay.")
        }
        .confirmationDialog("Stop this repeating message?",
                            isPresented: Binding(get: { confirmStop != nil }, set: { if !$0 { confirmStop = nil } }),
                            titleVisibility: .visible, presenting: confirmStop) { item in
            Button("Stop repeating it", role: .destructive) {
                Task { await state.queueOp("remove", ["id": item.id]) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { item in
            Text("“\(String(item.text.prefix(60)))” will not go out again.")
        }
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !queued.isEmpty {
                queuedHeader
                ForEach(Array(queued.enumerated()), id: \.element.id) { i, item in
                    row(item, index: i)
                        .draggable(item.id) { dragPreview(item) }
                        .dropDestination(for: String.self) { ids, _ in
                            guard let id = ids.first, id != item.id else { return false }
                            Task { await state.moveQueued(id, before: item.id) }
                            return true
                        }
                }
            }
            if !scheduled.isEmpty {
                Text("Scheduled · \(scheduled.count)")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    .padding(.top, queued.isEmpty ? 0 : 4).padding(.leading, 2)
                ForEach(scheduled) { item in row(item, index: nil) }
            }
        }
        .padding(.horizontal, 12).padding(.bottom, 6)
    }

    private var queuedHeader: some View {
        HStack(spacing: 8) {
            Text("Queued · \(queued.count)").font(.caption.weight(.semibold))
            Text(queueState).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 4)
            if state.queue.paused == true {
                Button("Resume") { Task { await state.resumeQueue() } }
                    .font(.caption.weight(.semibold))
            } else if state.queue.running == true {
                Button("Pause") { Task { await state.queueOp("pause") } }
                    .font(.caption)
                    .accessibilityHint("The next one waits after this answer, until you resume")
            }
            Button("Clear") { confirmClear = true }
                .font(.caption)
                .accessibilityHint("Removes every queued message; scheduled ones stay")
        }
        .padding(.leading, 2)
    }

    private func dragPreview(_ item: QueueItem) -> some View {
        Text(item.text.isEmpty ? "(attachments only)" : item.text)
            .font(.footnote).lineLimit(2)
            .padding(8)
            .background(.regularMaterial, in: .rect(cornerRadius: 8))
    }

    /// One waiting message. `index` is its place in line; nil for a scheduled one.
    private func row(_ item: QueueItem, index: Int?) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Group {
                if let index {
                    Text("\(index + 1)").font(.caption.monospacedDigit().weight(.semibold))
                } else {
                    Image(systemName: item.missed ? "clock.badge.exclamationmark" : "clock").font(.caption)
                }
            }
            .foregroundStyle(item.missed ? .orange : .secondary)
            .frame(width: 16)
            .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text.isEmpty ? "(attachments only)" : item.text)
                    .font(.footnote).lineLimit(2)
                HStack(spacing: 5) {
                    Text(when(item))
                    if let rep = item.repeatKind, !rep.isEmpty {
                        Text("· " + Repeat(server: rep).label.lowercased())
                    }
                    if let m = state.modelLabel(item.model) { Text("· " + m).lineLimit(1) }
                    if !item.attachments.isEmpty {
                        Label("\(item.attachments.count)", systemImage: "paperclip").labelStyle(.titleAndIcon)
                    }
                }
                .font(.caption2).foregroundStyle(item.missed ? .orange : .secondary)
            }
            .contentShape(Rectangle())
            .onTapGesture { editing = item }
            Spacer(minLength: 4)
            Menu {
                Button { editing = item } label: { Label("Edit", systemImage: "pencil") }
                Button { Task { await state.sendQueuedNow(item) } } label: {
                    if state.streaming && item.attachments.isEmpty {
                        Label("Send into the running answer now", systemImage: "arrow.turn.down.right")
                    } else {
                        Label("Send now", systemImage: "paperplane")
                    }
                }
                if let index, queued.count > 1 {
                    if index > 0 {
                        Button { move(index, by: -1) } label: { Label("Move up", systemImage: "arrow.up") }
                    }
                    if index < queued.count - 1 {
                        Button { move(index, by: 1) } label: { Label("Move down", systemImage: "arrow.down") }
                    }
                }
                Divider()
                Button(role: .destructive) {
                    if item.isScheduled, !(item.repeatKind ?? "").isEmpty {
                        confirmStop = item
                    } else {
                        Task { await state.queueOp("remove", ["id": item.id]) }
                    }
                } label: { Label("Remove", systemImage: "trash") }
            } label: {
                Image(systemName: "ellipsis.circle").font(.body)
                    .foregroundStyle(.secondary)
                    .frame(width: 30, height: 26)
            }
            .accessibilityLabel("Options for this message")
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 10))
    }

    private func when(_ item: QueueItem) -> String {
        guard let d = item.date else { return "next in line" }
        return item.missed ? "missed · was \(When.describe(d))" : When.describe(d)
    }

    /// Up or down one place among the queued messages.
    private func move(_ index: Int, by delta: Int) {
        let ids = queued.map(\.id)
        let to = index + delta
        guard ids.indices.contains(to) else { return }
        // moving down is moving in front of the one after the next
        let target: String? = delta < 0 ? ids[to] : (to + 1 < ids.count ? ids[to + 1] : nil)
        Task { await state.moveQueued(ids[index], before: target) }
    }

    private func save(_ item: QueueItem, _ r: QueuedMessageEditor.Result) async {
        let textChanged = r.text != item.text
        let whenChanged = r.at?.timeIntervalSince1970 != item.at
            || r.rep != Repeat(server: item.repeatKind)
        let modelChanged = r.model != (item.model ?? "")
        guard textChanged || whenChanged || modelChanged else { return }
        await state.updateQueued(item,
                                 text: textChanged ? r.text : nil,
                                 at: whenChanged ? .some(r.at) : nil,
                                 repeat: whenChanged ? r.rep : nil,
                                 model: modelChanged ? r.model : nil)
    }
}
