import SwiftUI
import Charts

/// The home page under a new chat's greeting, as on the Mac: what wants you now,
/// what is running, what is coming up, how much you have used Orbit lately, and
/// what is left of each allowance. Kept current while it is on screen.
@MainActor
final class HomeModel: ObservableObject {
    @Published var home: HomeOverview?
    /// The Mac has no `/api/home` (an older Orbit): show nothing rather than an error.
    @Published var unsupported = false

    func load(_ state: AppState) async {
        guard let server = state.server else { return }
        do {
            let h = try await server.home()
            home = h
            unsupported = false
        } catch {
            if home == nil, "\(error)".contains("404") { unsupported = true }
        }
    }

    func poll(_ state: AppState) async {
        while !Task.isCancelled {
            await load(state)
            try? await Task.sleep(nanoseconds: 20_000_000_000)
        }
    }
}

struct HomeDashboard: View {
    @EnvironmentObject var state: AppState
    @StateObject private var model = HomeModel()
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var showStats = false
    @State private var stopping: Set<String> = []

    var body: some View {
        Group {
            if model.unsupported {
                EmptyView()
            } else {
                VStack(spacing: 10) {
                    alerts
                    if sizeClass == .regular {
                        HStack(alignment: .top, spacing: 10) {
                            VStack(spacing: 10) { runningCard; activityCard }
                            VStack(spacing: 10) { upcomingCard; allowanceCard }
                        }
                    } else {
                        runningCard
                        upcomingCard
                        activityCard
                        allowanceCard
                    }
                }
                .frame(maxWidth: sizeClass == .regular ? 760 : 520)
            }
        }
        .task { await model.poll(state) }
        .sheet(isPresented: $showStats) { UsageStatsView(sid: nil) }
    }

    private var home: HomeOverview? { model.home }

    // ------------------------------------------------------------ what wants you now

    @ViewBuilder private var alerts: some View {
        if let h = home {
            let waiting = h.tasks.filter { $0.kind == .answer && $0.status == "waiting for you" }
            VStack(spacing: 6) {
                ForEach(waiting) { t in
                    alertRow("pause.circle.fill", "“\(t.title)” is waiting for your answer", tint: .orange) {
                        if let sid = t.sid { state.deepLink = sid }
                    }
                }
                ForEach(h.problems) { p in
                    alertRow("exclamationmark.triangle.fill", "\(p.name): \(p.detail)", tint: .red) {}
                }
                ForEach(h.failed) { f in
                    alertRow("xmark.octagon.fill",
                             "Scheduled task “\(f.title)” failed" + ((f.result ?? "").isEmpty ? "" : ": \(f.result!)"),
                             tint: .red) {
                        if let sid = f.sid { state.deepLink = sid } else { state.tab = "scheduled" }
                    }
                }
                ForEach(h.allowances) { a in
                    if let w = a.windows.first(where: \.limited) {
                        alertRow("hand.raised.fill", "\(a.name): limit reached"
                                 + (w.resets.map { " — back \(Self.inTime($0))" } ?? ""), tint: .red) {}
                    } else if let until = a.exhaustedUntil {
                        alertRow("hand.raised.fill", "\(a.name): used up — back \(Self.inTime(until))", tint: .red) {}
                    } else if let w = a.windows.first(where: { $0.left <= 15 }) {
                        alertRow("gauge.with.dots.needle.0percent",
                                 "\(a.name): only \(w.left)% of the \(w.name) allowance left", tint: .orange) {}
                    }
                }
            }
        }
    }

    private func alertRow(_ symbol: String, _ text: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(text).font(.footnote).lineLimit(2).multilineTextAlignment(.leading)
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(tint.opacity(0.1), in: .rect(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).strokeBorder(tint.opacity(0.3)))
        }
        .buttonStyle(.plain)
    }

    // ------------------------------------------------------------ cards

    private func card<Content: View>(_ title: String, live: Bool = false, link: String? = nil,
                                      onLink: @escaping () -> Void = {},
                                      @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                if live {
                    Image(systemName: "circle.fill").font(.system(size: 7)).foregroundStyle(.green)
                        .symbolEffect(.pulse)
                }
                Text(title.uppercased()).font(.caption2.weight(.semibold)).tracking(0.6)
                    .foregroundStyle(.secondary)
                Spacer()
                if let link {
                    Button(link) { Haptics.tap(); onLink() }
                        .font(.caption).buttonStyle(.plain).foregroundStyle(.tint)
                }
            }
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 12))
    }

    private func skeleton() -> some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(0..<3, id: \.self) { i in
                RoundedRectangle(cornerRadius: 4).fill(.quaternary.opacity(0.6))
                    .frame(height: 10).frame(maxWidth: CGFloat(220 - i * 50))
            }
        }
        .redacted(reason: .placeholder)
    }

    private func row(_ symbol: String, _ title: String, sub: String? = nil, side: String? = nil,
                     tint: Color = .secondary, action: (() -> Void)? = nil) -> some View {
        Button { action?() } label: {
            HStack(spacing: 9) {
                Image(systemName: symbol).font(.caption).foregroundStyle(tint).frame(width: 16)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.callout).lineLimit(1).foregroundStyle(.primary)
                    if let sub, !sub.isEmpty {
                        Text(sub).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 6)
                if let side { Text(side).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }

    private var runningCard: some View {
        let tasks = home?.tasks ?? []
        let live = tasks.filter { $0.kind == .answer || ($0.kind == .shell && $0.canStop) || ($0.kind == .background && $0.running) }
        let queued = Dictionary(grouping: tasks.filter { $0.kind == .queued && !($0.status ?? "").hasPrefix("at ") },
                                by: { $0.sid ?? "" })
        return card("Running now", live: !live.isEmpty, link: tasks.isEmpty ? nil : "All tasks",
                    onLink: { state.presentTasks() }) {
            if home == nil {
                skeleton()
            } else if live.isEmpty && queued.isEmpty {
                Text("Nothing running — Orbit is idle.").font(.footnote).foregroundStyle(.secondary)
            } else {
                ForEach(live.prefix(4)) { t in
                    HStack(spacing: 6) {
                        row(t.kind == .shell ? "terminal" : t.kind == .background ? "hourglass" : t.status == "waiting for you" ? "pause.circle.fill" : "circle.fill",
                            t.title,
                            sub: t.kind == .background ? t.status : t.kind == .answer && t.status != "answering" ? t.status : nil,
                            side: t.since.map { Self.duration((home?.now ?? 0) - $0) },
                            tint: t.status == "waiting for you" ? .orange : t.kind == .shell ? .secondary : .green,
                            action: t.sid.map { sid in { state.deepLink = sid } })
                        if t.canStop {
                            Button(stopping.contains(t.id) ? "Stopped" : "Stop") {
                                stopping.insert(t.id)
                                Task {
                                    _ = await state.stopBackground(t)
                                    await model.load(state)
                                }
                            }
                            .font(.caption).buttonStyle(.bordered).controlSize(.mini)
                            .disabled(stopping.contains(t.id))
                        }
                    }
                }
                ForEach(Array(queued.keys.sorted().prefix(3)), id: \.self) { sid in
                    let items = queued[sid] ?? []
                    row("tray.full", items.first?.title ?? "chat",
                        sub: items.first?.text.map { "next: \($0)" },
                        side: "\(items.count) queued",
                        action: sid.isEmpty ? nil : { state.deepLink = sid })
                }
            }
        }
    }

    private var upcomingCard: some View {
        let up = home?.upcoming ?? []
        return card("Coming up", link: "Scheduled", onLink: { state.tab = "scheduled" }) {
            if home == nil {
                skeleton()
            } else if up.isEmpty {
                Text("Nothing scheduled. Hold Send to send a message later.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else {
                ForEach(up.prefix(4)) { u in
                    let resume = u.kind == "limit_resume"
                    row(resume ? "arrow.clockwise" : u.kind == "message" ? "envelope" : u.repeats ? "repeat" : "clock",
                        resume ? "Resume “\(Self.stripPrefix(u.title))” after the limit" : u.title,
                        sub: u.text,
                        side: u.missed ? "missed" : Self.inTime(u.at),
                        action: {
                            if u.kind == "message", let sid = u.sid { state.deepLink = sid }
                            else { state.tab = "scheduled" }
                        })
                }
            }
        }
    }

    private var activityCard: some View {
        card("Activity", link: "Details", onLink: { showStats = true }) {
            if let h = home {
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                    stat("\(h.today.turns)", "today")
                    VStack(alignment: .leading, spacing: 1) {
                        HStack(alignment: .firstTextBaseline, spacing: 3) {
                            Text("\(h.week.turns)").font(.title3.weight(.semibold).monospacedDigit())
                            if let c = h.weekChange {
                                Text("\(c >= 0 ? "▲" : "▼")\(abs(c))%")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(c >= 0 ? Color.green : Color.secondary)
                            }
                        }
                        Text("this week").font(.caption2).foregroundStyle(.secondary)
                    }
                    stat(Self.tokens(h.week.tokens), "tokens")
                    stat(Self.duration(h.week.seconds), "model time")
                }
                Chart(Array(h.days.enumerated()), id: \.offset) { i, d in
                    BarMark(x: .value("Day", i), y: .value("Use", max(d.weight, 0.05)))
                        .foregroundStyle(i == h.days.count - 1 ? Color.accentColor : Color.accentColor.opacity(d.weight > 0 ? 0.3 : 0.12))
                        .cornerRadius(2)
                }
                .chartXAxis(.hidden).chartYAxis(.hidden)
                .frame(height: 50)
                .accessibilityLabel("Answers per day over the last two weeks")
                HStack {
                    Text("2 weeks ago"); Spacer()
                    if h.streak > 1 { Text("\(h.streak)-day streak").foregroundStyle(.primary.opacity(0.7)) }
                    Spacer(); Text("today")
                }
                .font(.caption2).foregroundStyle(.tertiary)
            } else {
                skeleton()
            }
        }
        .onTapGesture { showStats = true }
    }

    private func stat(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).font(.title3.weight(.semibold).monospacedDigit()).lineLimit(1).minimumScaleFactor(0.7)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var allowanceCard: some View {
        let accounts = (home?.allowances ?? []).filter { !$0.windows.isEmpty || $0.exhaustedUntil != nil }
        card(accounts.isEmpty ? "This week" : "Allowance left") {
            if home == nil { skeleton() }
            ForEach(accounts.prefix(3)) { a in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(a.name).font(.footnote.weight(.medium))
                        Spacer()
                        if let m = a.spentMonth, m > 0 {
                            Text(String(format: "~$%.2f this month", m)).font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(a.windows) { w in
                        HStack(spacing: 8) {
                            Text(w.name).font(.caption).foregroundStyle(.secondary).frame(width: 40, alignment: .leading)
                            ProgressView(value: Double(w.limited ? 0 : w.left), total: 100)
                                .tint(w.limited || w.left <= 15 ? .red : w.left <= 40 ? .orange : .green)
                            Text(w.limited ? "0%" : "\(w.left)%").font(.caption.monospacedDigit())
                                .frame(width: 36, alignment: .trailing)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityValue(w.resets.map { "resets \(Self.inTime($0))" } ?? "")
                    }
                }
                .padding(.bottom, 4)
            }
            if let h = home, !h.models.isEmpty {
                if !accounts.isEmpty {
                    Text("MOST USED · 7 DAYS").font(.caption2.weight(.semibold)).tracking(0.6)
                        .foregroundStyle(.secondary).padding(.top, 2)
                }
                let most = h.models.map(\.turns).max() ?? 1
                ForEach(h.models.prefix(accounts.isEmpty ? 4 : 3)) { m in
                    HStack(spacing: 8) {
                        Text(m.model.replacingOccurrences(of: " · your subscription", with: ""))
                            .font(.caption).lineLimit(1)
                        Spacer(minLength: 4)
                        Capsule().fill(Color.accentColor.opacity(0.5))
                            .frame(width: max(6, 60 * CGFloat(m.turns) / CGFloat(max(most, 1))), height: 5)
                        Text("\(m.turns)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            .frame(width: 26, alignment: .trailing)
                    }
                }
            } else if home != nil && accounts.isEmpty {
                Text("Nothing used this week yet.").font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    // ------------------------------------------------------------ formatting

    static func inTime(_ t: Double, now: Date = .now) -> String {
        let s = t - now.timeIntervalSince1970
        if s <= 60 { return s < -60 ? "overdue" : "now" }
        let m = Int((s / 60).rounded())
        if m < 60 { return "in \(m)m" }
        let h = m / 60
        if h < 24 { return "in \(h)h" + (h < 6 && m % 60 > 0 ? " \(m % 60)m" : "") }
        return Date(timeIntervalSince1970: t).formatted(.dateTime.weekday(.abbreviated).hour().minute())
    }

    static func duration(_ secs: Double) -> String {
        let s = Int(max(0, secs))
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s / 60)m \(s % 60)s" }
        return "\(s / 3600)h \((s % 3600) / 60)m"
    }

    static func tokens(_ n: Int) -> String {
        let d = Double(n)
        if d >= 1e9 { return String(format: "%.1fB", d / 1e9) }
        if d >= 1e6 { return String(format: "%.1fM", d / 1e6) }
        if d >= 1e4 { return "\(Int((d / 1e3).rounded()))k" }
        if d >= 1e3 { return String(format: "%.1fk", d / 1e3) }
        return "\(n)"
    }

    /// "resume: My chat" → "My chat"
    static func stripPrefix(_ s: String) -> String {
        guard let r = s.range(of: ": ") else { return s }
        return String(s[r.upperBound...])
    }
}
