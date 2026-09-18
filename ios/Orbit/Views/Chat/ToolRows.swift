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
                Spacer(minLength: 4)
                ToolClock(run: run)
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
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.caption2).foregroundStyle(.tertiary)
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
}

struct ToolDot: View {
    var running: Bool
    var failed: Bool

    var body: some View {
        if running {
            ProgressView().controlSize(.mini).frame(width: 12)
        } else {
            Text("⏺")
                .font(.caption2)
                .foregroundStyle(failed ? Color.red : Color.green)
                .frame(width: 12)
                .accessibilityLabel(failed ? "failed" : "done")
        }
    }
}

/// How long it took, or a running clock while it runs.
private struct ToolClock: View {
    let run: ToolRun

    var body: some View {
        if run.running, let t0 = run.startedAt {
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                Text(ToolText.secs(ctx.date.timeIntervalSince(t0)))
            }
            .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
        } else if let s = run.secs, s >= 0.5 {
            Text(ToolText.secs(s)).font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
        }
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
            ForEach(Array(steps.enumerated()), id: \.offset) { _, s in
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

    private var label: String {
        if live { return "✻ Thinking…" }
        if let secs { return "✻ Thought for \(ToolText.secs(secs))" }
        return "✻ Thought"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
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
                Text(text)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 9))
            }
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
