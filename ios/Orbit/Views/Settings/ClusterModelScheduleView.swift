import SwiftUI

/// When a model server starts and stops by itself, and who is told when it is ready, stops or fails.
/// The schedule runs while Orbit is running on the Mac. A start waits for a GPU, so the model is ready
/// some minutes after the time; a stop done by hand is not undone the same day.
struct ClusterModelScheduleView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterModelsStore
    let id: String
    @State private var rows: [ServerSchedule] = []
    @State private var email = ""
    @State private var desktop = true
    @State private var events: [String: Bool] = [:]
    @State private var loaded = false
    @State private var busy = false
    @State private var note: String?

    private static let days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    private var saved: ModelServer? { store.server(id) }

    private var changed: Bool {
        guard let s = saved else { return false }
        return rows != s.schedule || email != s.email || desktop != s.desktop || events != s.events
    }

    var body: some View {
        Form {
            if loaded {
                Section {
                    if rows.isEmpty {
                        Text("No schedule. Start and stop it by hand.").font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach($rows) { $r in scheduleRow($r) }
                        .onDelete { rows.remove(atOffsets: $0) }
                    Button { rows.append(ServerSchedule()) } label: { Label("Add a schedule", systemImage: "plus") }
                } header: {
                    Text("Start and stop by themselves")
                } footer: {
                    Text("Swipe a row to remove it.")
                }

                Section {
                    TextField("E-mail (empty: none)", text: $email)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.emailAddress)
                    Toggle("When it is ready", isOn: event("ready"))
                    Toggle("When it stops", isOn: event("stopped"))
                    Toggle("When it fails", isOn: event("failed"))
                    Toggle("Also a notification on the Mac", isOn: $desktop)
                } header: {
                    Text("Tell me")
                } footer: {
                    Text("The e-mail is sent by the cluster itself, not from a mail account of yours, so it arrives even when the Mac is off. "
                         + "It applies from the next start.")
                }

                Section {
                    Button(busy ? "Saving…" : "Save") { Task { await save() } }.disabled(!changed || busy)
                }
            } else {
                LoadingRow()
            }
        }
        .navigationTitle("Schedule and notices")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .task { if !loaded, let s = saved { adopt(s); loaded = true } }
    }

    private func scheduleRow(_ r: Binding<ServerSchedule>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("On", isOn: r.enabled)
            HStack {
                DatePicker("Start", selection: time(r.start), displayedComponents: .hourAndMinute)
                DatePicker("Stop", selection: time(r.stop), displayedComponents: .hourAndMinute)
            }
            if let on = r.wrappedValue.on {
                Text("Only on \(on)").font(.caption).foregroundStyle(.secondary)
            } else {
                dayChips(r)
            }
        }
        .padding(.vertical, 2)
    }

    private func dayChips(_ r: Binding<ServerSchedule>) -> some View {
        HStack(spacing: 4) {
            ForEach(0..<7, id: \.self) { d in
                let on = r.wrappedValue.days.contains(d)
                Button {
                    if on { r.wrappedValue.days.remove(d) } else { r.wrappedValue.days.insert(d) }
                } label: {
                    Text(String(Self.days[d].prefix(2)))
                        .font(.caption.weight(.semibold))
                        .frame(maxWidth: .infinity).padding(.vertical, 6)
                        .background(on ? Color.accentColor.opacity(0.2) : Color.gray.opacity(0.12),
                                    in: RoundedRectangle(cornerRadius: 6))
                        .foregroundStyle(on ? Color.accentColor : Color.secondary)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(Self.days[d])
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }

    /// "08:00" as a time today, and back.
    private func time(_ text: Binding<String>) -> Binding<Date> {
        Binding(get: {
            let p = text.wrappedValue.split(separator: ":").compactMap { Int($0) }
            return Calendar.current.date(bySettingHour: p.first ?? 8, minute: p.count > 1 ? p[1] : 0, second: 0, of: .now) ?? .now
        }, set: { d in
            let c = Calendar.current.dateComponents([.hour, .minute], from: d)
            text.wrappedValue = String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
        })
    }

    private func event(_ k: String) -> Binding<Bool> {
        Binding(get: { events[k] ?? true }, set: { events[k] = $0 })
    }

    private func adopt(_ s: ModelServer) {
        rows = s.schedule; email = s.email; desktop = s.desktop; events = s.events
    }

    private func save() async {
        guard let api = state.server else { return }
        busy = true
        defer { busy = false }
        let notify: [String: Any] = ["email": email.trimmingCharacters(in: .whitespaces), "desktop": desktop,
                                     "events": ["ready": events["ready"] ?? true, "stopped": events["stopped"] ?? true,
                                                "failed": events["failed"] ?? true]]
        do {
            store.data = try await api.saveModelServer(id: id, schedule: rows, notify: notify)
            if let s = store.server(id) { adopt(s) }
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
