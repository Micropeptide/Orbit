import SwiftUI

/// A step's tool calls the way Claude Code prints them: `⏺ Read notes.md`
/// and under it `⎿ Read 32 lines`. Tap a row for its arguments and full
/// output; finished look-ups in a row fold into one line.
struct ToolRunsView: View {
    let runs: [ToolRun]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(ToolFold.fold(runs)) { item in
                switch item {
                case .single(let run, _): ToolRunRow(run: run)
                case .group(let runs, _): ToolGroupRow(runs: runs)
                }
            }
        }
    }
}

/// Opened by a tap; `/verbose` opens every row at once, and a tap then folds that one.
private struct Expandable {
    static let verboseKey = "orbit.verboseTools"
}

struct ToolRunRow: View {
    let run: ToolRun
    @AppStorage(Expandable.verboseKey) private var verbose = false
    @State private var flipped = false

    private var open: Bool { verbose != flipped }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { flipped.toggle() }
            } label: { header }
            .buttonStyle(.plain)
            .accessibilityHint(open ? "Hides the details" : "Shows the arguments and output")
            // The whole row is the tap target, which is right on a phone — but that
            // leaves the command, the path and the result unselectable. Long press
            // copies them, folded or not, which is what you actually reach for.
            .contextMenu {
                if !run.target.isEmpty {
                    Button { UIPasteboard.general.string = run.target } label: {
                        Label("Copy \(run.display.lowercased()) target", systemImage: "doc.on.doc")
                    }
                }
                if run.done, !run.summary.isEmpty {
                    Button { UIPasteboard.general.string = run.summary } label: {
                        Label("Copy result", systemImage: "text.quote")
                    }
                }
                Button {
                    UIPasteboard.general.string = [run.display, run.target, run.summary]
                        .filter { !$0.isEmpty }.joined(separator: "\n")
                } label: { Label("Copy the whole line", systemImage: "list.clipboard") }
            }
            if open, run.done { ToolRunDetail(run: run).padding(.leading, 18) }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                ToolDot(running: run.running, failed: run.failed)
                (Text(run.running ? ToolText.verb(run.display) : run.display).fontWeight(.semibold)
                 + Text(run.target.isEmpty ? "" : " " + run.target).foregroundStyle(.secondary))
                    .font(.footnote)
                    .lineLimit(open ? 4 : 1)
                    .truncationMode(.tail)
                    .modifier(Working(on: run.running))
                Spacer(minLength: 4)
                ToolClock(run: run)
            }
            if let sa = run.subagent, !sa.steps.isEmpty, run.running || sa.background || open {
                SubagentSteps(info: sa, all: open)
            }
            if run.done {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("⎿").foregroundStyle(.tertiary)
                    Text(run.summary)
                        .foregroundStyle(run.failed ? Color.red : .secondary)
                        .lineLimit(open ? 3 : 1)
                }
                .font(.caption)
                .padding(.leading, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(.rect)
    }
}

/// "Read 3 files, Searched for 1 pattern" — opens to the rows it stands for.
struct ToolGroupRow: View {
    let runs: [ToolRun]
    @AppStorage(Expandable.verboseKey) private var verbose = false
    @State private var flipped = false

    private var open: Bool { verbose != flipped }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { flipped.toggle() }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    ToolDot(running: false, failed: false)
                    Text(ToolText.familyLabel(runs)).font(.footnote.weight(.semibold))
                        .lineLimit(2)
                        .layoutPriority(1)
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.caption2).foregroundStyle(.tertiary)
                    if !open { names }
                    Spacer(minLength: 4)
                    let secs = runs.compactMap(\.secs).reduce(0, +)
                    if secs >= 0.5 {
                        Text(ToolText.secs(secs)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            if open {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(runs.enumerated()), id: \.offset) { _, r in ToolRunRow(run: r) }
                }
                .padding(.leading, 14)
            }
        }
    }

    /// Which files, not just how many — two on a phone, because the header already
    /// competes with the duration and the chevron.
    private var names: some View {
        let all = ToolText.familyNames(runs)
        let show = all.prefix(2)
        return HStack(spacing: 4) {
            ForEach(Array(show), id: \.self) { n in
                Text(n)
                    .font(.caption2.monospaced())
                    .lineLimit(1).truncationMode(.middle)
                    .padding(.horizontal, 5)
                    .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 4))
                    .foregroundStyle(.secondary)
            }
            if all.count > show.count {
                Text("+\(all.count - show.count)").font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .accessibilityLabel(all.isEmpty ? "" : "touched " + all.joined(separator: ", "))
    }
}

struct ToolDot: View {
    var running: Bool
    var failed: Bool

    var body: some View {
        // A spinner per running row is one display-link-driven animation per call, and a
        // parallel fan-out is eight of them at once, on top of re-parsing streaming
        // Markdown. The glyph stays; the row says it is working by sweeping its name.
        Text("⏺")
            .font(.caption2)
            .foregroundStyle(running ? Color.orange : failed ? Color.red : Color.green)
            .frame(width: 12)
            .accessibilityLabel(running ? "running" : failed ? "failed" : "done")
    }
}

/// A running call's name, breathing, so you can see which row is working without a
/// spinner on every one of them. Still, under Reduce Motion.
private struct Working: ViewModifier {
    var on: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var dim = false

    func body(content: Content) -> some View {
        if on && !reduceMotion {
            content
                .opacity(dim ? 0.55 : 1)
                .animation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true), value: dim)
                .onAppear { dim = true }
                // not onDisappear: setting the animated value while a repeatForever
                // animation is still attached is how one gets left running on a view
                // that has gone
        } else {
            content.opacity(1)
        }
    }
}

/// One clock for every running row on screen, instead of one timer each — and none at
/// all while the app is in the background or nothing is running.
@MainActor final class LiveClock: ObservableObject {
    static let shared = LiveClock()
    @Published private(set) var now = Date()
    private var timer: Timer?
    private var watchers = 0

    func join() {
        watchers += 1
        start()
    }

    func leave() {
        watchers = max(0, watchers - 1)
        if watchers == 0 { stop() }
    }

    /// Nothing to show while the app is not on screen, and a timer on the common run
    /// loop keeps firing there. Called from the scene-phase change.
    func awake(_ on: Bool) {
        asleep = !on
        if on { start() } else { stop() }
    }

    private var asleep = false

    private func start() {
        guard timer == nil, watchers > 0, !asleep else { return }
        now = Date()
        let t = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.now = Date() }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func stop() { timer?.invalidate(); timer = nil }
}

/// How long it took, or a running clock while it runs.
///
/// The running case is its own view on purpose: an `@ObservedObject` is a subscription,
/// and a stored one would subscribe every finished row in the chat too — three hundred
/// static "1.4s" labels re-rendering once a second to say the same thing. Only the rows
/// that are actually running watch the clock.
private struct ToolClock: View {
    let run: ToolRun

    var body: some View {
        if run.running, let t0 = run.startedAt {
            RunningFor(since: t0)
        } else if let s = run.secs, s >= 0.5 {
            Text(ToolText.secs(s)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
        }
    }
}

private struct RunningFor: View {
    let since: Date
    @ObservedObject private var clock = LiveClock.shared

    var body: some View {
        Text(ToolText.secs(clock.now.timeIntervalSince(since)))
            .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
            .onAppear { clock.join() }
            .onDisappear { clock.leave() }
    }
}

/// The arguments in full, then everything that came back.
struct ToolRunDetail: View {
    let run: ToolRun
    private static let cap = 30_000

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !run.args.isEmpty {
                Text(run.argsText)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if run.name == "plan", let out = run.output, !PlanStep.parse(out).isEmpty {
                TodoList(steps: PlanStep.parse(out))
            } else if let out = run.output, !out.isEmpty {
                if !run.args.isEmpty { Divider() }
                ScrollView {
                    Text(out.count > Self.cap
                         ? String(out.prefix(Self.cap)) + "\n… \((out.count - Self.cap).formatted()) more characters — copy for all of it"
                         : out)
                        .font(.caption2.monospaced())
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 280)
                .modifier(CodeTextSize())
            }
            HStack {
                Spacer()
                Button {
                    UIPasteboard.general.string = [run.argsText, run.output ?? ""].filter { !$0.isEmpty }
                        .joined(separator: "\n\n")
                    Haptics.success()
                } label: { Label("Copy", systemImage: "doc.on.doc").font(.caption2) }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
        }
        .padding(9)
        .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 8))
    }
}

/// Claude Code's todo marks: ☒ done (struck through), ◼ in hand (bold), ☐ to do.
struct TodoList: View {
    let steps: [PlanStep]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Array(steps.enumerated()), id: \.offset) { i, s in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(s.mark)
                        .foregroundStyle(s.active && !s.done ? Color.accentColor : .secondary)
                    Text(s.text)
                        .strikethrough(s.done, color: .secondary)
                        .fontWeight(s.active && !s.done ? .semibold : .regular)
                        .foregroundStyle(s.done ? Color.secondary : s.active ? Color.accentColor : .primary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .font(.footnote)
                .id("todo-\(i)")          // so a long plan can open on the step in hand
            }
        }
    }
}

/// "✻ Thinking…" while it thinks, "✻ Thought for 12s" after — folded away until opened.
struct ThinkingBlock: View {
    let text: String
    var live = false
    var secs: Double? = nil
    @State private var open = false
    @State private var showAll = false
    /// You opened or closed it yourself, so nothing opens or closes it for you again.
    @State private var userTouched = false
    /// The answer has begun at least once, so thinking is no longer the thing to read.
    @State private var answered = false

    /// Long thinking shows its first lines (the latest ones while it is written) and a
    /// "Show all"; the rest is a tap away.
    private static let lines = 14
    private var lineCount: Int { text.split(separator: "\n", omittingEmptySubsequences: false).count }
    private var long: Bool { lineCount > Self.lines + 2 || text.count > Self.lines * 140 }
    private var shown: String {
        guard long, !showAll else { return text }
        if live {                                   // while it thinks: the newest part
            let tail = text.split(separator: "\n", omittingEmptySubsequences: false).suffix(Self.lines)
            return "…\n" + String(tail.joined(separator: "\n").suffix(Self.lines * 140))
        }
        return text
    }

    private var thoughts: some View {
        Text(shown)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
            .lineLimit(long && !showAll && !live ? Self.lines : nil)
            .textSelection(.enabled)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var label: String {
        if live { return "✻ Thinking…" }
        if let secs { return "✻ Thought for \(ToolText.secs(secs))" }
        return "✻ Thought"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                userTouched = true
                withAnimation(.easeInOut(duration: 0.15)) { open.toggle() }
            } label: {
                HStack(spacing: 5) {
                    Text(label).font(.caption.italic())
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.caption2)
                }
                .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            if open {
                // While it thinks it may not fill the screen — the answer is what you
                // are waiting for. Capping it with .clipped() cut text that had no
                // "Show all" to open (that button only exists for LONG thinking), so it
                // scrolls inside itself instead and nothing is unreachable.
                ScrollView { thoughts }
                    .frame(maxHeight: live && !showAll ? 240 : .infinity)
                    .scrollBounceBehavior(.basedOnSize)
                    .scrollDisabled(!(live && !showAll))
                if long {
                    Button(showAll ? "Show less" : "Show all · \(ToolText.plural(lineCount, "line", "lines"))") {
                        withAnimation(.easeInOut(duration: 0.15)) { showAll.toggle() }
                    }
                    .font(.caption).buttonStyle(.plain).foregroundStyle(.tint)
                }
            }
        }
        // It is written out to be read: open while it thinks, folded away when the
        // answer starts. Nothing ever opened it, so streaming it was work for nobody.
        .onAppear { if live && !userTouched { open = true } }
        .onChange(of: live) { _, nowLive in
            guard !userTouched else { return }
            // "live" goes true again between the steps of one answer, so following it
            // both ways made the box open and shut repeatedly mid-answer. It opens once
            // and closes once: when the answer starts, it is done opening.
            if nowLive { if !answered { withAnimation(.easeInOut(duration: 0.2)) { open = true } } }
            else { answered = true; withAnimation(.easeInOut(duration: 0.2)) { open = false } }
        }
    }
}

/// A `!` command and what it printed, terminal style.
struct BangBlock: View {
    let run: BangRun

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            Text("you ran").font(.caption2).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Text("! " + run.cmd)
                    .font(.footnote.monospaced().weight(.semibold))
                    .textSelection(.enabled)
                if run.running {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("running…").font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                } else {
                    ScrollView {
                        Text(run.out.trimmingTrailingWhitespace.isEmpty ? "(no output)" : run.out.trimmingTrailingWhitespace)
                            .font(.caption2.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 240)
                .modifier(CodeTextSize())
                    .fixedSize(horizontal: false, vertical: true)
                    Text(run.meta)
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(run.rc == 0 ? Color.secondary : Color.red)
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.primary.opacity(0.06), in: .rect(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .strokeBorder(run.rc == 0 || run.running ? Color.orange.opacity(0.35) : Color.red.opacity(0.5)))
            .contextMenu {
                Button {
                    UIPasteboard.general.string = "$ " + run.cmd + "\n" + run.out
                } label: { Label("Copy", systemImage: "doc.on.doc") }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }
}

private extension String {
    var trimmingTrailingWhitespace: String {
        var s = Substring(self)
        while let last = s.last, last.isWhitespace { s = s.dropLast() }
        return String(s)
    }
}


/// A subagent's steps under its Agent row: the last three and "+N more tool uses" while
/// it works, every step (and what it reported) when the row is opened.
struct SubagentSteps: View {
    let info: SubagentInfo
    var all = false

    var body: some View {
        let shown = all ? info.steps : Array(info.steps.suffix(3))
        VStack(alignment: .leading, spacing: 1) {
            ForEach(Array(shown.enumerated()), id: \.offset) { i, st in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(i == 0 ? "⎿" : " ").foregroundStyle(.tertiary).frame(width: 10)
                    Text(st.line).lineLimit(1).truncationMode(.tail)
                }
            }
            let more = max(info.tools, info.steps.count) - shown.count
            if more > 0 {
                HStack(spacing: 6) {
                    Text(" ").frame(width: 10)
                    Text("+" + ToolText.plural(more, "more tool use", "more tool uses")).foregroundStyle(.tertiary)
                }
            }
            if all, let s = info.summary, !s.isEmpty {
                Text(s).font(.caption).foregroundStyle(.secondary).padding(.top, 3).lineLimit(12)
            }
        }
        .font(.caption.monospaced())
        .foregroundStyle(.secondary)
        .padding(.leading, 18)
    }
}
