import SwiftUI

struct MessageBubble: View {
    let message: Message
    var isLast = false
    var onEdit: ((Message) -> Void)? = nil
    var onRegenerate: (() -> Void)? = nil
    var onQuote: ((Message) -> Void)? = nil
    /// Fork, retry deeper, continue, check DOIs, undo file changes (Views/Chat).
    var actions: MessageActions? = nil
    /// One answer, one block: only its first step names the model.
    var showByline = true
    /// Which of your messages this answers, when it is the last step of that
    /// answer: the sources, hooks and notices that came with it are drawn under it.
    var turn: (index: Int, prompt: String)? = nil
    @State private var shareImage: ShareImage?
    @State private var quoting: String?
    @Environment(\.fileLinkSid) private var linkSid

    /// Uploaded images come back as data: URLs, which UIImage cannot read directly.
    static func decodeDataURL(_ s: String) -> Data? {
        guard let comma = s.firstIndex(of: ","), s.hasPrefix("data:") else { return nil }
        return Data(base64Encoded: String(s[s.index(after: comma)...]))
    }

    var body: some View {
        Group {
        if message.isUser, let bang = message.bang {
            BangBlock(run: bang)
        } else if message.isUser {
            VStack(alignment: .trailing, spacing: 7) {
            ForEach(message.images ?? [], id: \.self) { src in
                if let data = Self.decodeDataURL(src), let ui = UIImage(data: data) {
                    Image(uiImage: ui).resizable().aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 220, maxHeight: 220)
                        .clipShape(.rect(cornerRadius: 13))
                }
            }
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(.tint.opacity(0.14), in: .rect(cornerRadius: 17))
                    .contextMenu {
                        Button {
                            UIPasteboard.general.string = message.text
                        } label: { Label("Copy", systemImage: "doc.on.doc") }
                        if let onQuote {
                            Button { onQuote(message) } label: { Label("Quote", systemImage: "text.quote") }
                            Button { quoting = message.text } label: {
                                Label("Quote a part…", systemImage: "text.quote")
                            }
                        }
                        if let onEdit {
                            Button { onEdit(message) } label: {
                                Label("Edit and resend", systemImage: "pencil.line")
                            }
                        }
                        if let actions { actions.userItems(message) }
                    }
            }
            if message.note == true {
                NoteReadState(sid: linkSid, text: message.text)
            }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        } else {
            VStack(alignment: .leading, spacing: 7) {
                if showByline, let model = message.model, !model.isEmpty {
                    Text(model).font(.caption2.smallCaps()).foregroundStyle(.secondary)
                }
                // a step reads in the order it happened: what it said, then the tools it called
                if !message.text.isEmpty { MarkdownText(message.text) }
                ForEach(toolLines, id: \.self) { ToolLine(text: $0) }
                if let runs = message.tool_runs, !runs.isEmpty { ToolRunsView(runs: runs) }
                ForEach(message.plots ?? [], id: \.self) { MessageImage(path: $0) }
                if let thinking = message.thinking, !thinking.isEmpty {
                    ThinkingBlock(text: thinking, secs: message.thoughtFor)
                }
                AnswerFileStrip(message: message)
                if let turn { TurnExtras(sid: linkSid, turn: turn.index, prompt: turn.prompt) }
                AnswerFooter(message: message, actions: actions)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contextMenu {
                Button {
                    UIPasteboard.general.string = message.text
                } label: { Label("Copy", systemImage: "doc.on.doc") }
                ShareLink(item: message.text) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                Button { shareAsImage() } label: {
                    Label("Share as image", systemImage: "photo.on.rectangle")
                }
                if let onQuote {
                    Button { onQuote(message) } label: { Label("Quote", systemImage: "text.quote") }
                    Button { quoting = message.text } label: {
                        Label("Quote a part…", systemImage: "text.quote")
                    }
                }
                if isLast, let onRegenerate {
                    Button { onRegenerate() } label: {
                        Label("Ask again", systemImage: "arrow.clockwise")
                    }
                }
                if let actions { actions.answerItems(message, isLast: isLast) }
            }
        }
        }
        .sheet(item: $shareImage) { ActivityView(items: [$0.image]).ignoresSafeArea() }
        .sheet(isPresented: Binding(get: { quoting != nil }, set: { if !$0 { quoting = nil } })) {
            QuotePartSheet(text: quoting ?? "")
        }
    }

    /// With tool rows to show, the saved list of tool names says nothing new;
    /// only the notices (auto-approved, refused, a switch of model) stay.
    private var toolLines: [String] {
        let lines = message.tools ?? []
        guard message.tool_runs?.isEmpty == false else { return lines }
        return lines.filter { $0.hasPrefix("✓") || $0.hasPrefix("↪") || $0.hasPrefix("refused") }
    }

    /// The answer as a picture — for a group chat that would mangle Markdown.
    @MainActor private func shareAsImage() {
        let renderer = ImageRenderer(content: AnswerCard(text: message.text, model: message.model))
        renderer.scale = 3
        if let img = renderer.uiImage { shareImage = ShareImage(image: img) }
    }
}

/// One line about what the answer did: a tool call (orange), an automatic
/// approval (green), or a notice such as a switch to another model (blue).
struct ToolLine: View {
    let text: String

    var body: some View {
        let tint: Color = text.hasPrefix("✓ auto-approved") ? .green : text.hasPrefix("↪") ? .blue : .orange
        Text(text)
            .font(text.hasPrefix("↪") ? .caption : .caption.monospaced())
            .foregroundStyle(tint)
            .padding(.vertical, 5).padding(.horizontal, 9)
            .background(tint.opacity(0.10), in: .rect(cornerRadius: 7))
    }
}

/// A rendered answer with a small byline, sized for sharing.
struct AnswerCard: View {
    let text: String
    let model: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image("OrbitMark").resizable().scaledToFit().frame(width: 22, height: 22)
                Text("Orbit").font(.subheadline.weight(.semibold))
                if let model, !model.isEmpty {
                    Text("· \(model)").font(.caption).foregroundStyle(.secondary)
                }
            }
            MarkdownText(text)
        }
        .padding(18)
        .frame(width: 380, alignment: .leading)
        .background(Color(.systemBackground))
    }
}

/// Markdown, rendered block by block.
///
/// `AttributedString(markdown:)` alone collapses fenced code and lists into one
/// run of text, which is exactly what you least want to read on a phone. This
/// splits the answer into blocks first — headings, lists and task lists, quotes
/// and `> [!NOTE]` callouts, tables, code, rules, display maths — and renders
/// the inline parts (bold, links, `code`, ~~strikethrough~~) with the system parser.
/// File names that exist on the Mac become links that open a preview.
struct MarkdownText: View {
    let raw: String
    init(_ raw: String) { self.raw = raw }

    @Environment(\.fileLinkSid) private var sid
    @ObservedObject private var links = FileLinks.shared

    var body: some View {
        let blocks = Block.parse(raw)
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                view(for: block)
            }
        }
        .environment(\.openURL, OpenURLAction { url in
            if let sid, links.open(url, sid: sid) { return .handled }
            return url.scheme == FileLinks.scheme ? .handled : .systemAction
        })
        .task(id: sid.map { $0 + "\u{0}" + raw }) {
            // only a finished answer is looked up — a live one changes 20 times a second
            guard let sid else { return }
            let names = blocks.flatMap(\.inlineTexts).flatMap { FileLinks.candidates(in: Self.attributed($0)) }
            links.request(sid: sid, names: names)
        }
    }

    @ViewBuilder
    private func view(for block: Block) -> some View {
        switch block {
        // a live answer (no sid) keeps the source: its diagram or formula is still arriving
        case .code(let language, let code):
            if sid != nil, language.lowercased() == "mermaid" { MermaidBlock(source: code) }
            else { CodeBlock(language: language, code: code) }
        case .math(let tex):
            if sid != nil { MathBlock(tex: tex) } else { CodeBlock(language: "math", code: tex) }
        case .table(let rows):
            TableBlock(rows: rows, inline: inline)
        case .text(let markdown):
            Text(inline(markdown))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        case .heading(let level, let text):
            Text(inline(text))
                .font(Self.headingFont(level))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, level <= 2 ? 4 : 0)
        case .rule:
            Divider().padding(.vertical, 2)
        case .list(let items):
            VStack(alignment: .leading, spacing: 5) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        marker(item)
                        Text(inline(item.text))
                            .strikethrough(item.checked == true, color: .secondary)
                            .foregroundStyle(item.checked == true ? .secondary : .primary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.leading, CGFloat(min(item.depth, 6)) * 16)
                }
            }
        case .quote(let kind, let title, let body):
            QuoteBlock(kind: kind, title: title.map { inline($0) }) {
                MarkdownText(body)
            }
        }
    }

    @ViewBuilder
    private func marker(_ item: ListItem) -> some View {
        if let checked = item.checked {
            Image(systemName: checked ? "checkmark.square.fill" : "square")
                .foregroundStyle(checked ? Color.accentColor : .secondary)
                .font(.body)
                .accessibilityLabel(checked ? "done" : "not done")
        } else if let n = item.number {
            Text(n).monospacedDigit().foregroundStyle(.secondary)
        } else {
            Text(item.depth == 0 ? "•" : "◦").foregroundStyle(.secondary)
        }
    }

    static func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return .title2.weight(.bold)
        case 2: return .title3.weight(.semibold)
        case 3: return .headline
        default: return .subheadline.weight(.semibold)
        }
    }

    /// Inline Markdown, with file names and web addresses linked.
    private func inline(_ s: String) -> AttributedString {
        links.linkify(Self.attributed(s), sid: sid)
    }

    static func attributed(_ s: String) -> AttributedString {
        (try? AttributedString(
            markdown: s,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
        ?? AttributedString(s)
    }

    struct ListItem {
        var depth: Int
        var number: String?          // "3." for an ordered item
        var checked: Bool?           // a task list item
        var text: String
    }

    enum Block {
        case text(String)
        case heading(level: Int, text: String)
        case code(language: String, code: String)
        case math(String)
        case table(rows: [[String]])
        case list([ListItem])
        case quote(kind: String?, title: String?, body: String)
        case rule

        /// The inline Markdown pieces, for finding file names in them.
        var inlineTexts: [String] {
            switch self {
            case .text(let s), .heading(_, let s): return [s]
            case .table(let rows): return rows.flatMap { $0 }
            case .list(let items): return items.map(\.text)
            case .quote(_, let title, let body):
                return (title.map { [$0] } ?? []) + Block.parse(body).flatMap(\.inlineTexts)
            case .code, .math, .rule: return []
            }
        }

        private static let headingRE = try! NSRegularExpression(pattern: #"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$"#)
        private static let ruleRE = try! NSRegularExpression(pattern: #"^ {0,3}([-*_])(\s*\1){2,}\s*$"#)
        private static let itemRE = try! NSRegularExpression(pattern: #"^(\s*)([-*+]|\d{1,4}[.)])\s+(.*)$"#)
        private static let calloutRE = try! NSRegularExpression(pattern: #"^\[!(\w+)\][+-]?\s*(.*)$"#)

        private static func groups(_ re: NSRegularExpression, _ s: String) -> [String]? {
            guard let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
            return (0..<m.numberOfRanges).map { i in
                Range(m.range(at: i), in: s).map { String(s[$0]) } ?? ""
            }
        }

        /// Split an answer into blocks. Deliberately forgiving: it handles what
        /// models actually emit, and never loses characters — anything
        /// unrecognised stays text rather than disappearing.
        static func parse(_ raw: String) -> [Block] {
            var blocks: [Block] = []
            var buffer: [String] = []

            func flushText() {
                let t = buffer.joined(separator: "\n").trimmingCharacters(in: .newlines)
                if !t.trimmingCharacters(in: .whitespaces).isEmpty { blocks.append(.text(t)) }
                buffer = []
            }

            let lines = raw.components(separatedBy: .newlines)
            var i = 0
            while i < lines.count {
                let line = lines[i]
                let trimmed = line.trimmingCharacters(in: .whitespaces)

                // fenced code, ``` or ~~~, possibly indented inside a list
                if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") {
                    flushText()
                    let fence = String(trimmed.prefix(3))
                    let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                    var code: [String] = []
                    var j = i + 1
                    while j < lines.count,
                          !lines[j].trimmingCharacters(in: .whitespaces).hasPrefix(fence) {
                        code.append(lines[j]); j += 1
                    }
                    // an answer cut off mid-fence still shows what arrived
                    blocks.append(.code(language: language, code: code.joined(separator: "\n")))
                    i = j + 1; continue
                }

                // display maths: shown as its source, in monospace
                if trimmed.hasPrefix("$$") || trimmed == "\\[" {
                    flushText()
                    let close = trimmed.hasPrefix("$$") ? "$$" : "\\]"
                    let rest = String(trimmed.dropFirst(2))
                    if close == "$$", rest.hasSuffix("$$"), rest.count >= 2 {
                        blocks.append(.math(String(rest.dropLast(2)).trimmingCharacters(in: .whitespaces)))
                        i += 1; continue
                    }
                    var body: [String] = rest.isEmpty ? [] : [rest]
                    var j = i + 1
                    while j < lines.count {
                        let t = lines[j].trimmingCharacters(in: .whitespaces)
                        if t.hasSuffix(close) {
                            let last = String(t.dropLast(2))
                            if !last.isEmpty { body.append(last) }
                            break
                        }
                        body.append(lines[j]); j += 1
                    }
                    blocks.append(.math(body.joined(separator: "\n")))
                    i = j + 1; continue
                }

                // a pipe table: header row, separator row, then the body
                if trimmed.hasPrefix("|"), i + 1 < lines.count, isSeparator(lines[i + 1]) {
                    flushText()
                    var rows = [cells(line)]
                    var j = i + 2
                    while j < lines.count,
                          lines[j].trimmingCharacters(in: .whitespaces).hasPrefix("|") {
                        rows.append(cells(lines[j])); j += 1
                    }
                    let width = rows.map(\.count).max() ?? 0
                    blocks.append(.table(rows: rows.map {
                        $0 + Array(repeating: "", count: width - $0.count) }))
                    i = j; continue
                }

                if let g = groups(headingRE, line) {
                    flushText()
                    blocks.append(.heading(level: g[1].count, text: g[2]))
                    i += 1; continue
                }

                if groups(ruleRE, line) != nil {
                    flushText()
                    blocks.append(.rule)
                    i += 1; continue
                }

                // block quotes, and GitHub's > [!NOTE] callouts
                if trimmed.hasPrefix(">") {
                    flushText()
                    var body: [String] = []
                    var j = i
                    while j < lines.count {
                        let t = lines[j].trimmingCharacters(in: .whitespaces)
                        guard t.hasPrefix(">") else { break }
                        var s = String(t.dropFirst())
                        if s.hasPrefix(" ") { s.removeFirst() }
                        body.append(s); j += 1
                    }
                    var kind: String? = nil
                    var title: String? = nil
                    if let first = body.first, let g = groups(calloutRE, first) {
                        kind = g[1].lowercased()
                        title = g[2].isEmpty ? nil : g[2]
                        body.removeFirst()
                    }
                    blocks.append(.quote(kind: kind, title: title, body: body.joined(separator: "\n")))
                    i = j; continue
                }

                // bullets, numbers and task lists; indented lines continue an item
                if groups(itemRE, line) != nil {
                    flushText()
                    var items: [ListItem] = []
                    var j = i
                    while j < lines.count {
                        let l = lines[j]
                        if let g = groups(itemRE, l) {
                            let indent = g[1].replacingOccurrences(of: "\t", with: "    ").count
                            var text = g[3]
                            var checked: Bool? = nil
                            let lower = text.lowercased()
                            if lower.hasPrefix("[ ] ") || lower == "[ ]" { checked = false; text = String(text.dropFirst(3)) }
                            else if lower.hasPrefix("[x] ") || lower == "[x]" { checked = true; text = String(text.dropFirst(3)) }
                            let marker = g[2]
                            items.append(ListItem(depth: indent / 2,
                                                  number: marker.first?.isNumber == true ? marker : nil,
                                                  checked: checked,
                                                  text: text.trimmingCharacters(in: .whitespaces)))
                            j += 1
                        } else if !l.trimmingCharacters(in: .whitespaces).isEmpty,
                                  l.hasPrefix(" ") || l.hasPrefix("\t"), !items.isEmpty,
                                  !l.trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                            items[items.count - 1].text += "\n" + l.trimmingCharacters(in: .whitespaces)
                            j += 1
                        } else {
                            break
                        }
                    }
                    blocks.append(.list(items))
                    i = j; continue
                }

                buffer.append(line); i += 1
            }
            flushText()
            return blocks
        }

        static func isSeparator(_ s: String) -> Bool {
            let t = s.trimmingCharacters(in: .whitespaces)
            guard t.contains("-") else { return false }
            let rest = t.filter { !"|:- ".contains($0) }
            return rest.isEmpty
        }

        static func cells(_ s: String) -> [String] {
            var t = s.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("|") { t.removeFirst() }
            if t.hasSuffix("|") && !t.hasSuffix("\\|") { t.removeLast() }
            // a pipe escaped as \| belongs to the cell
            let marker = "\u{1}"
            return t.replacingOccurrences(of: "\\|", with: marker)
                .components(separatedBy: "|")
                .map { $0.replacingOccurrences(of: marker, with: "|").trimmingCharacters(in: .whitespaces) }
        }
    }
}

/// A block quote, or a GitHub callout with its coloured bar and title.
struct QuoteBlock<Content: View>: View {
    let kind: String?
    let title: AttributedString?
    @ViewBuilder var content: () -> Content

    private var tint: Color {
        switch kind {
        case "tip": return .green
        case "warning": return .orange
        case "caution", "danger", "error": return .red
        case "important": return .purple
        case nil: return .secondary
        default: return .blue
        }
    }

    private var icon: String {
        switch kind {
        case "tip": return "lightbulb"
        case "warning": return "exclamationmark.triangle"
        case "caution", "danger", "error": return "exclamationmark.octagon"
        case "important": return "exclamationmark.bubble"
        default: return "info.circle"
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 1.5).fill(tint.opacity(kind == nil ? 0.5 : 0.9))
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 5) {
                if let kind {
                    Label {
                        if let title { Text(title) } else { Text(kind.capitalized) }
                    } icon: { Image(systemName: icon) }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(tint)
                }
                content()
                    .foregroundStyle(kind == nil ? .secondary : .primary)
            }
            .padding(.vertical, kind == nil ? 2 : 7)
            .padding(.trailing, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .fixedSize(horizontal: false, vertical: true)
        .background(kind == nil ? Color.clear : tint.opacity(0.07), in: .rect(cornerRadius: 8))
    }
}
