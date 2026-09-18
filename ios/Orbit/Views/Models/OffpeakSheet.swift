import SwiftUI

/// Cheaper hours: which providers charge less (or count less of a plan) at
/// certain hours, where they stand now, and the next 24 hours at a glance.
/// The web page's "Cheaper hours" sheet.
struct OffpeakSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var loading = true
    @State private var expanded: Set<String> = []

    private var current: ModelInfo? { state.models.first { $0.id == state.effectiveModelID } }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Some providers charge less at certain hours, and some plans count less of your "
                         + "allowance then. It depends on where you use a model: DeepSeek through its own API "
                         + "or through OpenCode Go follows DeepSeek's hours, while the same model elsewhere may "
                         + "not. Models in the pickers are marked green while it is cheaper and orange when it "
                         + "is cheaper at other hours. Times are shown in the provider's time zone and in yours."
                         + (current?.offpeak == nil ? " The model this chat uses has no cheaper hours." : ""))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let list = state.usage.offpeak {
                    if list.isEmpty {
                        Text("No provider in Orbit's list has time-based pricing on record.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(list) { p in
                        Section {
                            DisclosureGroup(isExpanded: Binding(
                                get: { expanded.contains(p.id) },
                                set: { if $0 { expanded.insert(p.id) } else { expanded.remove(p.id) } })) {
                                details(p)
                            } label: {
                                summary(p)
                            }
                        }
                    }
                } else if loading {
                    LoadingRow()
                }
            }
            .navigationTitle("Cheaper hours")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .task {
                await state.loadOffpeak()
                loading = false
                // open the policy for the provider this chat's model goes through
                if let id = current?.id, let pid = ModelID.provider(id) {
                    for p in state.usage.offpeak ?? [] where p.provider == pid { expanded.insert(p.id) }
                }
            }
            .refreshable { await state.loadOffpeak() }
        }
    }

    private func summary(_ p: OffpeakPolicy) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Circle()
                .fill((p.status?.isActive ?? false) ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text(p.provider + (p.appliesTo.map { " · " + $0 } ?? "")).font(.subheadline.weight(.medium))
                if let l = p.status?.label { Text(l).font(.caption).foregroundStyle(.secondary) }
            }
        }
    }

    @ViewBuilder private func details(_ p: OffpeakPolicy) -> some View {
        if let st = p.status {
            VStack(alignment: .leading, spacing: 4) {
                DayBar(spans: st.spans)
                if let c = countdown(st) { Text(c).font(.caption).foregroundStyle(.secondary) }
            }
            .padding(.vertical, 4)
            info("Peak", st.peak.map { $0.replacingOccurrences(of: #"^peak:\s*"#, with: "", options: .regularExpression) })
            info("Cheaper hours (provider)", st.windows.joined(separator: ", "))
            info("Cheaper hours (your time, this week)", st.windowsLocal.joined(separator: ", "))
        }
        info("What you pay then", p.discountText)
        info("Models", p.modelsText)
        info("In force", [p.effective.map { "from " + $0 }, p.ends.map { "until " + $0 }]
                .compactMap { $0 }.joined(separator: " ").nonEmpty ?? "no end date announced")
        info("Notes", p.note)
        info("Their words", p.quote.map { "“" + $0 + "”" })
        info("Checked", p.checkedAt)
        if !p.sources.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text("Source").font(.caption).foregroundStyle(.secondary)
                ForEach(p.sources, id: \.self) { u in
                    if let url = URL(string: u) { Link(u, destination: url).font(.caption) }
                }
            }
        }
    }

    @ViewBuilder private func info(_ title: String, _ value: String?) -> some View {
        if let value, !value.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Text(value).font(.callout)
            }
        }
    }

    /// "cheaper for another 3 h 12 min — until 18:00"
    private func countdown(_ st: OffpeakPolicy.Status) -> String? {
        let active = st.isActive
        guard let next = active ? st.endsAt : st.startsAt else { return nil }
        let mins = max(0, Int(((next - Date().timeIntervalSince1970) / 60).rounded()))
        let span = (mins >= 60 ? "\(mins / 60) h " : "") + "\(mins % 60) min"
        let when = OffpeakText.when(next)
        return active ? "cheaper for another \(span) — until \(when)"
                      : "full rate for another \(span) — cheaper from \(when)"
    }
}

/// The next 24 hours as a bar: green while it is cheaper.
private struct DayBar: View {
    let spans: [[Double]]

    var body: some View {
        let now = Date().timeIntervalSince1970
        let day = 86_400.0
        VStack(spacing: 2) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.orange.opacity(0.3))
                    ForEach(Array(spans.enumerated()), id: \.offset) { _, s in
                        if s.count == 2 {
                            let start = max(0, (s[0] - now) / day)
                            let width = max(0.005, min(1, (s[1] - max(s[0], now)) / day))
                            Rectangle().fill(Color.green)
                                .frame(width: geo.size.width * min(width, 1 - min(start, 1)))
                                .offset(x: geo.size.width * min(start, 1))
                        }
                    }
                }
                .clipShape(Capsule())
            }
            .frame(height: 12)
            HStack {
                ForEach([0, 6, 12, 18, 24], id: \.self) { h in
                    Text(h == 0 ? "now" : Date(timeIntervalSince1970: now + Double(h) * 3600)
                            .formatted(date: .omitted, time: .shortened))
                    if h != 24 { Spacer() }
                }
            }
            .font(.system(size: 10)).foregroundStyle(.secondary)
        }
        .accessibilityHidden(true)
    }
}

enum OffpeakText {
    /// "15:00", or "Mon 15:00" when it is not today.
    static func when(_ t: Double) -> String {
        let d = Date(timeIntervalSince1970: t)
        let time = d.formatted(date: .omitted, time: .shortened)
        return Calendar.current.isDateInToday(d) ? time : d.formatted(.dateTime.weekday(.abbreviated)) + " " + time
    }
}

/// The open chat's model is cheaper now, or will be later: a small mark by
/// the composer's model chip that opens the cheaper-hours sheet.
struct OffpeakBadge: View {
    @EnvironmentObject var state: AppState
    @State private var show = false

    var body: some View {
        if let op = state.currentOffpeak {
            Button { show = true } label: {
                HStack(spacing: 3) {
                    Image(systemName: op.isActive ? "leaf.fill" : "clock").font(.caption2)
                    Text(text(op)).font(.caption2.weight(.medium)).lineLimit(1)
                }
                .foregroundStyle(op.isActive ? Color.green : Color.orange)
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background((op.isActive ? Color.green : Color.orange).opacity(0.12), in: .capsule)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Cheaper hours: \(op.shortText)")
            .sheet(isPresented: $show) { OffpeakSheet() }
        }
    }

    private func text(_ op: OffPeak) -> String {
        let w = op.what ?? "cheaper"
        if op.isActive { return w + (op.ends_at.map { " · until " + OffpeakText.when($0) } ?? "") }
        return op.starts_at.map { "\(w) from " + OffpeakText.when($0) } ?? (op.quota == true ? "full rate" : "peak price")
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
