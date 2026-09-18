import SwiftUI

/// Code blocks and tables in answers, with the tools the Mac's web UI gives
/// them (codeTools, tableTools): copy in several shapes, save as a file, wrap,
/// format JSON, show CSV as a table, preview a page, sort a table, see it all.

// ------------------------------------------------------------------ actions

/// What a code block asks of the app: put text in the message box, show a
/// toast. Handed down as one unchanging object rather than every block watching
/// the whole app state, which redrew each block on every token of an answer.
@MainActor
final class BlockActions {
    weak var state: AppState?

    nonisolated init() {}

    func insertInDraft(_ text: String) { state?.insertInDraft(text) }
    func toast(_ text: String) { state?.toast(text) }
}

private struct BlockActionsKey: EnvironmentKey {
    /// Unset (a share image, a preview) does nothing.
    static let defaultValue = BlockActions()
}

extension EnvironmentValues {
    var blockActions: BlockActions {
        get { self[BlockActionsKey.self] }
        set { self[BlockActionsKey.self] = newValue }
    }
}

// ------------------------------------------------------------------ code

struct CodeBlock: View {
    let language: String
    let code: String
    /// A block drawn inside a sheet already has all its lines.
    var collapsible = true
    @Environment(\.blockActions) private var actions
    @AppStorage("orbit.codeWrap") private var wrap = false
    @State private var copied = false
    @State private var expanded = false
    @State private var formatted: String?
    @State private var shareURL: URL?
    @State private var preview: PreviewKind?

    private enum PreviewKind: Identifiable {
        case html, table, markdown
        var id: Int { hashValue }
    }

    static let collapseAt = 45
    private var lang: String { language.lowercased().split(separator: " ").first.map(String.init) ?? "" }
    private var shown: String { formatted ?? code }
    private var lineCount: Int { code.reduce(1) { $1 == "\n" ? $0 + 1 : $0 } }
    private var collapsed: Bool { collapsible && !expanded && lineCount > Self.collapseAt }

    private var visible: String {
        guard collapsed else { return shown }
        return shown.split(separator: "\n", omittingEmptySubsequences: false)
            .prefix(Self.collapseAt).joined(separator: "\n")
    }

    private var looksLikeCSV: Bool {
        if ["csv", "tsv"].contains(lang) { return true }
        guard lang.isEmpty else { return false }
        return code.range(of: #"^([^,\n]+,){2,}[^,\n]+\n([^,\n]*,){2,}"#, options: .regularExpression) != nil
    }

    private var isPage: Bool {
        ["html", "htm", "xml", "svg"].contains(lang)
            && code.range(of: #"<(html|body|div|svg|head|!doctype|table|canvas|script)"#,
                          options: [.regularExpression, .caseInsensitive]) != nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                Text(language.isEmpty ? "code" : language)
                    .font(.caption2.smallCaps()).foregroundStyle(.secondary)
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    withAnimation { copied = true }
                    Haptics.success()
                    Task {
                        try? await Task.sleep(nanoseconds: 1_500_000_000)
                        withAnimation { copied = false }
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy",
                          systemImage: copied ? "checkmark" : "doc.on.doc")
                        .font(.caption2)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                Menu { tools } label: {
                    Image(systemName: "ellipsis").font(.caption).frame(width: 22, height: 18)
                }
                .foregroundStyle(.secondary)
                .accessibilityLabel("Code tools")
            }
            .padding(.horizontal, 11).padding(.vertical, 6)

            Group {
                if wrap {
                    Text(visible)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 11)
                } else {
                    ScrollView(.horizontal, showsIndicators: false) {
                        Text(visible)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                            .padding(.horizontal, 11)
                    }
                }
            }
            .padding(.bottom, collapsible && lineCount > Self.collapseAt ? 4 : 10)

            if collapsible && lineCount > Self.collapseAt {
                Button(expanded ? "Show less" : "Show all \(lineCount) lines") {
                    withAnimation(.snappy) { expanded.toggle() }
                }
                .font(.caption2)
                .buttonStyle(.plain)
                .foregroundStyle(.tint)
                .padding(.horizontal, 11).padding(.bottom, 8)
            }
        }
        .background(.quaternary.opacity(0.35), in: .rect(cornerRadius: 10))
        .sheet(item: $shareURL) { ActivityView(items: [$0]).ignoresSafeArea() }
        .sheet(item: $preview) { kind in
            switch kind {
            case .html:
                HTMLPreviewSheet(html: lang == "svg" ? "<!doctype html><meta name=viewport content='width=device-width'><body style='margin:0'>" + code : code)
            case .table:
                TableSheet(title: "Table", rows: CSV.parse(code, separator: lang == "tsv" || (lang.isEmpty && code.contains("\t")) ? "\t" : ","))
            case .markdown:
                NavigationStack {
                    ScrollView { MarkdownText(code).padding() }
                        .navigationTitle("Markdown").navigationBarTitleDisplayMode(.inline)
                }
            }
        }
    }

    @ViewBuilder
    private var tools: some View {
        Button {
            actions.insertInDraft("\n```" + language + "\n" + code.trimmingCharacters(in: .newlines) + "\n```\n")
        } label: { Label("Insert into message", systemImage: "text.insert") }
        Button { save() } label: { Label("Save as a file…", systemImage: "square.and.arrow.down") }
        Toggle(isOn: $wrap) { Label("Wrap long lines", systemImage: "text.word.spacing") }
        if ["json", "jsonl"].contains(lang) {
            Button { formatJSON() } label: {
                Label(formatted == nil ? "Format JSON" : "Show original", systemImage: "curlybraces")
            }
        }
        if looksLikeCSV {
            Button { preview = .table } label: { Label("Show as a table", systemImage: "tablecells") }
        }
        if isPage {
            Button { preview = .html } label: { Label("Preview", systemImage: "globe") }
        }
        if lang == "markdown" || lang == "md" {
            Button { preview = .markdown } label: { Label("Rendered", systemImage: "doc.richtext") }
        }
    }

    private static let extensions: [String: String] = [
        "python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts", "tsx": "tsx",
        "jsx": "jsx", "bash": "sh", "sh": "sh", "zsh": "sh", "shell": "sh", "json": "json", "yaml": "yaml", "yml": "yml",
        "html": "html", "xml": "xml", "svg": "svg", "css": "css", "markdown": "md", "md": "md", "r": "R", "julia": "jl",
        "sql": "sql", "swift": "swift", "rust": "rs", "go": "go", "java": "java", "c": "c", "cpp": "cpp", "c++": "cpp",
        "csv": "csv", "tsv": "tsv", "tex": "tex", "latex": "tex", "toml": "toml", "ruby": "rb", "php": "php",
        "perl": "pl", "lua": "lua", "kotlin": "kt", "diff": "diff", "patch": "patch", "ini": "ini", "text": "txt",
    ]

    private func save() {
        let ext = Self.extensions[lang] ?? (lang.isEmpty ? "txt" : lang)
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-snippet-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("snippet.\(ext)")
        do { try Data(code.utf8).write(to: url, options: .atomic); shareURL = url }
        catch { actions.toast("Could not save it: \(error.localizedDescription)") }
    }

    private func formatJSON() {
        if formatted != nil { formatted = nil; return }
        func pretty(_ s: String) throws -> String {
            let obj = try JSONSerialization.jsonObject(with: Data(s.utf8), options: [.fragmentsAllowed])
            let d = try JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .withoutEscapingSlashes, .fragmentsAllowed])
            return String(decoding: d, as: UTF8.self)
        }
        do {
            formatted = lang == "jsonl"
                ? try code.split(separator: "\n").map { try pretty(String($0)) }.joined(separator: "\n")
                : try pretty(code)
        } catch {
            actions.toast("Not valid JSON")
        }
    }
}

// ------------------------------------------------------------------ CSV

enum CSV {
    /// Quoted fields, doubled quotes, and newlines inside quotes; at most 5000 rows.
    static func parse(_ text: String, separator: Character = ",") -> [[String]] {
        var rows: [[String]] = []
        var row: [String] = []
        var cur = ""
        var quoted = false
        var it = Array(text)
        if it.last == "\n" { it.removeLast() }
        var i = 0
        while i < it.count {
            let c = it[i]
            if quoted {
                if c == "\"" {
                    if i + 1 < it.count, it[i + 1] == "\"" { cur.append("\""); i += 1 } else { quoted = false }
                } else { cur.append(c) }
            } else if c == "\"" && cur.isEmpty {
                quoted = true
            } else if c == separator {
                row.append(cur); cur = ""
            } else if c == "\n" || c == "\r" || c == "\r\n" {
                row.append(cur); rows.append(row); row = []; cur = ""
                if rows.count >= 5000 { break }
            } else {
                cur.append(c)
            }
            i += 1
        }
        if !cur.isEmpty || !row.isEmpty { row.append(cur); rows.append(row) }
        let width = rows.map(\.count).max() ?? 0
        return rows.map { $0 + Array(repeating: "", count: width - $0.count) }
    }

    static func cell(_ v: String, _ sep: String) -> String {
        v.contains(sep) || v.contains("\"") || v.contains("\n") ? "\"" + v.replacingOccurrences(of: "\"", with: "\"\"") + "\"" : v
    }
}

// ------------------------------------------------------------------ tables

/// Rows of cells, with the shapes they copy as and the order they sort in.
struct TableData {
    var rows: [[String]]

    /// Cell text without Markdown marks, as it would paste into a spreadsheet.
    static func plain(_ s: String) -> String {
        String(MarkdownText.attributed(s).characters).trimmingCharacters(in: .whitespaces)
    }

    var plainRows: [[String]] { rows.map { $0.map(Self.plain) } }

    var markdown: String {
        guard let head = rows.first else { return "" }
        let line = { (r: [String]) in "| " + r.map { $0.replacingOccurrences(of: "|", with: "\\|") }.joined(separator: " | ") + " |" }
        return ([line(head), "| " + head.map { _ in "---" }.joined(separator: " | ") + " |"] + rows.dropFirst().map(line))
            .joined(separator: "\n")
    }
    var csv: String { plainRows.map { $0.map { CSV.cell($0, ",") }.joined(separator: ",") }.joined(separator: "\n") }
    var tsv: String { plainRows.map { $0.map { $0.replacingOccurrences(of: "\t", with: " ") }.joined(separator: "\t") }.joined(separator: "\n") }

    private static let numberRE = try! NSRegularExpression(
        pattern: #"^[-+−]?[$€£¥]?\s?[\d,]*\.?\d+(e[-+]?\d+)?\s?(%|[kKMBx×]|ms|s|GB|MB|KB|bp|kb)?$"#)

    /// Columns whose every filled cell is a number: they line up on the right.
    var numericColumns: Set<Int> {
        guard rows.count > 1 else { return [] }
        var out = Set<Int>()
        for c in 0..<(rows.first?.count ?? 0) {
            let vals = rows.dropFirst().map { c < $0.count ? Self.plain($0[c]) : "" }.filter { !$0.isEmpty }
            if !vals.isEmpty, vals.allSatisfy({ Self.numberRE.firstMatch(in: $0, range: NSRange($0.startIndex..., in: $0)) != nil }) {
                out.insert(c)
            }
        }
        return out
    }

    static func number(_ s: String) -> Double? {
        Double(plain(s).replacingOccurrences(of: #"[,$€£¥%\s]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "−", with: "-"))
    }

    func sorted(by column: Int?, ascending: Bool) -> [[String]] {
        guard let column, rows.count > 2 else { return rows }
        let body = rows.dropFirst().sorted { a, b in
            let x = column < a.count ? a[column] : "", y = column < b.count ? b[column] : ""
            if let nx = Self.number(x), let ny = Self.number(y) { return ascending ? nx < ny : nx > ny }
            let r = Self.plain(x).localizedStandardCompare(Self.plain(y))
            return ascending ? r == .orderedAscending : r == .orderedDescending
        }
        return [rows[0]] + body
    }
}

/// Work a table's rows cost once, kept across redraws: which columns are numbers
/// (a Markdown parse and a pattern per cell) and the rows in the order picked.
/// A class, so filling it while drawing does not ask for another draw.
private final class TableCache {
    private var rows: [[String]]?
    private(set) var numeric: Set<Int> = []
    private(set) var widths: [CGFloat] = []
    private var sortKey: (column: Int?, ascending: Bool)?
    private var sortedRows: [[String]] = []

    /// Resets itself when the table's content changes (an answer still writing it).
    private func use(_ new: [[String]], full: Bool) {
        guard rows != new else { return }
        rows = new
        let data = TableData(rows: new)
        numeric = data.numericColumns
        widths = full ? Self.columnWidths(new) : []
        sortKey = nil
        sortedRows = new
    }

    func prepare(_ new: [[String]], full: Bool) -> TableCache {
        use(new, full: full)
        return self
    }

    func sorted(by column: Int?, ascending: Bool) -> [[String]] {
        guard let rows else { return [] }
        if let k = sortKey, k.column == column, k.ascending == ascending { return sortedRows }
        sortKey = (column, ascending)
        sortedRows = TableData(rows: rows).sorted(by: column, ascending: ascending)
        return sortedRows
    }

    /// A lazy list has no grid to line columns up, so each gets a width from its
    /// longest text among the first rows.
    private static func columnWidths(_ rows: [[String]]) -> [CGFloat] {
        let n = rows.first?.count ?? 0
        var longest = Array(repeating: 0, count: n)
        for row in rows.prefix(300) {
            for (c, cell) in row.enumerated() where c < n {
                longest[c] = max(longest[c], min(cell.count, 60))
            }
        }
        return longest.map { min(320, max(44, CGFloat($0) * 8 + 8)) }
    }
}

/// A Markdown table as a real grid: header, rule, rows; scrolls sideways when wide.
/// In a sheet (`full`) it scrolls both ways and draws only the rows on screen.
struct TableBlock: View {
    let rows: [[String]]
    var inline: (String) -> AttributedString = MarkdownText.attributed
    /// In a sheet: every row, and a filter.
    var full = false
    @State private var sortColumn: Int?
    @State private var ascending = true
    @State private var showAll = false
    @State private var enlarged = false
    @State private var shareURL: URL?
    @State private var filter = ""
    @State private var cache = TableCache()

    static let clipAt = 26

    var body: some View {
        let prepared = cache.prepare(rows, full: full)
        let numeric = prepared.numeric
        var shownRows = prepared.sorted(by: sortColumn, ascending: ascending)
        let q = filter.trimmingCharacters(in: .whitespaces).lowercased()
        if full, !q.isEmpty, shownRows.count > 1 {
            shownRows = [shownRows[0]] + shownRows.dropFirst().filter { $0.joined(separator: " ").lowercased().contains(q) }
        }
        let clipped = !full && !showAll && shownRows.count > Self.clipAt
        let visible = clipped ? Array(shownRows.prefix(Self.clipAt - 1)) : shownRows
        let columns = rows.first?.count ?? 0

        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text("\(max(0, rows.count - 1)) × \(columns)")
                    .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                if full && rows.count > 8 {
                    TextField("filter rows…", text: $filter)
                        .font(.caption).textFieldStyle(.roundedBorder)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Spacer()
                Menu { tools() } label: {
                    Image(systemName: "ellipsis.circle").font(.caption)
                }
                .foregroundStyle(.secondary)
                .accessibilityLabel("Table tools")
            }
            .padding(.horizontal, 4)

            if full {
                lazyTable(visible, numeric: numeric, widths: prepared.widths)
            } else {
                ScrollView(.horizontal, showsIndicators: true) {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                        ForEach(Array(visible.enumerated()), id: \.offset) { i, row in
                            GridRow {
                                ForEach(Array(row.enumerated()), id: \.offset) { c, cell in
                                    cellView(cell, header: i == 0, column: c, numeric: numeric.contains(c))
                                }
                            }
                            if i == 0 { Divider().gridCellUnsizedAxes(.horizontal) }
                        }
                    }
                    .padding(.horizontal, 12).padding(.vertical, 9)
                }
                .background(.quaternary.opacity(0.28), in: .rect(cornerRadius: 10))
            }

            if !full && shownRows.count > Self.clipAt {
                Button(showAll ? "Show fewer" : "Show all \(shownRows.count - 1) rows") {
                    withAnimation(.snappy) { showAll.toggle() }
                }
                .font(.caption2).buttonStyle(.plain).foregroundStyle(.tint)
                .padding(.horizontal, 4)
            }
        }
        .sheet(isPresented: $enlarged) { TableSheet(title: "Table", rows: rows, inline: inline) }
        .sheet(item: $shareURL) { ActivityView(items: [$0]).ignoresSafeArea() }
    }

    /// Every row of a big table, drawn as it scrolls into view, the header kept on top.
    private func lazyTable(_ visible: [[String]], numeric: Set<Int>, widths: [CGFloat]) -> some View {
        func line(_ row: [String], header: Bool) -> some View {
            HStack(alignment: .top, spacing: 16) {
                ForEach(Array(row.enumerated()), id: \.offset) { c, cell in
                    cellView(cell, header: header, column: c, numeric: numeric.contains(c))
                        .frame(width: c < widths.count ? widths[c] : 120,
                               alignment: numeric.contains(c) ? .trailing : .leading)
                }
            }
        }
        return ScrollView([.vertical, .horizontal]) {
            LazyVStack(alignment: .leading, spacing: 6, pinnedViews: [.sectionHeaders]) {
                Section {
                    ForEach(Array(visible.dropFirst().enumerated()), id: \.offset) { _, row in
                        line(row, header: false)
                    }
                } header: {
                    if let head = visible.first {
                        VStack(alignment: .leading, spacing: 6) {
                            line(head, header: true)
                            Divider()
                        }
                        .padding(.top, 9)
                        .background(.background)
                    }
                }
            }
            .padding(.horizontal, 12).padding(.bottom, 9)
        }
        .background(.quaternary.opacity(0.28), in: .rect(cornerRadius: 10))
    }

    @ViewBuilder
    private func cellView(_ cell: String, header: Bool, column: Int, numeric: Bool) -> some View {
        let text = Text(inline(cell))
            .font(header ? .subheadline.weight(.semibold) : .subheadline)
            .frame(maxWidth: 320, alignment: numeric ? .trailing : .leading)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
        if header {
            text
                .gridColumnAlignment(numeric ? .trailing : .leading)
                .overlay(alignment: .trailing) {
                    if sortColumn == column {
                        Image(systemName: ascending ? "arrow.up" : "arrow.down")
                            .font(.caption2).foregroundStyle(.tint).offset(x: 13)
                    }
                }
                .onTapGesture { sort(column) }
        } else {
            text
        }
    }

    private func sort(_ column: Int) {
        withAnimation(.snappy) {
            if sortColumn == column { ascending.toggle() } else { sortColumn = column; ascending = true }
        }
    }

    @ViewBuilder
    private func tools() -> some View {
        let data = TableData(rows: rows)
        Menu {
            Button { copy(data.markdown) } label: { Text("Markdown") }
            Button { copy(data.csv) } label: { Text("CSV") }
            Button { copy(data.tsv) } label: { Text("TSV (pastes into a spreadsheet)") }
        } label: { Label("Copy as…", systemImage: "doc.on.clipboard") }
        Button { share(data) } label: { Label("Share as CSV…", systemImage: "square.and.arrow.up") }
        if let head = rows.first, rows.count > 2 {
            Menu {
                ForEach(Array(head.enumerated()), id: \.offset) { c, h in
                    Button { sort(c) } label: {
                        let name = TableData.plain(h)
                        Text((name.isEmpty ? "Column \(c + 1)" : name)
                             + (sortColumn == c ? (ascending ? "  ↑" : "  ↓") : ""))
                    }
                }
                if sortColumn != nil {
                    Divider()
                    Button("Original order") { withAnimation { sortColumn = nil } }
                }
            } label: { Label("Sort by", systemImage: "arrow.up.arrow.down") }
        }
        if !full {
            Button { enlarged = true } label: {
                Label("Enlarge", systemImage: "arrow.up.left.and.arrow.down.right")
            }
        }
    }

    private func copy(_ s: String) {
        UIPasteboard.general.string = s
        Haptics.success()
    }

    private func share(_ data: TableData) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-table-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("table.csv")
        // a byte-order mark so Excel reads it as UTF-8
        if (try? Data(("\u{FEFF}" + data.csv).utf8).write(to: url, options: .atomic)) != nil { shareURL = url }
    }
}

/// A table on its own screen: every row, a filter, both directions of scroll.
struct TableSheet: View {
    let title: String
    let rows: [[String]]
    var inline: (String) -> AttributedString = MarkdownText.attributed
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            // the table scrolls itself, so only the rows on screen are drawn
            TableBlock(rows: rows, inline: inline, full: true).padding()
                .navigationTitle(title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
