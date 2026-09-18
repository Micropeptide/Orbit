import SwiftUI

/// File names and paths in answers, made tappable.
///
/// An answer mentions `results/plot.png` or a full path; the Mac knows whether
/// that is a real file where the chat works. Candidates are collected from the
/// rendered text, looked up in one batched request, and the ones that exist
/// become links that open a preview.
@MainActor
final class FileLinks: ObservableObject {
    static let shared = FileLinks()
    var server: OrbitServer?

    /// sid -> name as written -> what the Mac found
    @Published private(set) var resolved: [String: [String: ResolvedPath]] = [:]
    /// The file whose preview is showing.
    @Published var presenting: FilePreviewTarget?
    /// A path an answer named that is not there: find files with its name instead.
    @Published var missing: FilePreviewTarget?
    /// The folder each chat works in, as the Mac last said, for relative paths.
    @Published private(set) var cwd: [String: String] = [:]

    private var asked: [String: [String: Date]] = [:]
    private var pending: [String: Set<String>] = [:]
    private var flushTask: Task<Void, Never>?

    static let scheme = "orbit-file"

    func info(sid: String, name: String) -> ResolvedPath? { resolved[sid]?[name] }

    /// Ask about these names, unless asked recently. Found files are kept for
    /// two minutes, misses for twenty seconds (the answer may be about to write it).
    func request(sid: String, names: [String]) {
        guard server != nil, !names.isEmpty else { return }
        let now = Date()
        for n in Set(names) {
            if let at = asked[sid]?[n] {
                let found = resolved[sid]?[n]?.exists == true
                if now.timeIntervalSince(at) < (found ? 120 : 20) { continue }
            }
            asked[sid, default: [:]][n] = now
            pending[sid, default: []].insert(n)
        }
        guard !pending.isEmpty, flushTask == nil else { return }
        flushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 80_000_000)      // one request for a screenful
            await self?.flush()
        }
    }

    private func flush() async {
        let work = pending
        pending = [:]
        flushTask = nil
        guard let server else { return }
        for (sid, names) in work {
            let all = Array(names)
            for start in stride(from: 0, to: all.count, by: 250) {
                let chunk = Array(all[start..<min(all.count, start + 250)])
                guard let r = try? await server.resolvePathsWithFolder(sid: sid, chunk) else { continue }
                var map = resolved[sid] ?? [:]
                for (k, v) in r.items { map[k] = v }
                resolved[sid] = map
                if let c = r.cwd, cwd[sid] != c { cwd[sid] = c }
            }
        }
    }

    /// Handle a tapped link. True when it was one of ours.
    func open(_ url: URL, sid: String) -> Bool {
        guard url.scheme == Self.scheme,
              let name = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "n" })?.value,
              let info = info(sid: sid, name: name) else { return false }
        Haptics.tap()
        if info.exists { presenting = FilePreviewTarget(sid: sid, info: info) }
        else { missing = FilePreviewTarget(sid: sid, info: info) }
        return true
    }

    /// Look these names up now and wait for the answer (cached ones are not asked again).
    func resolveNow(sid: String, names: [String]) async -> [String: ResolvedPath] {
        let known = resolved[sid] ?? [:]
        let need = Array(Set(names.filter { known[$0] == nil }))
        if let server, !need.isEmpty {
            for start in stride(from: 0, to: need.count, by: 250) {
                let chunk = Array(need[start..<min(need.count, start + 250)])
                guard let r = try? await server.resolvePathsWithFolder(sid: sid, chunk) else { continue }
                var map = resolved[sid] ?? [:]
                for (k, v) in r.items { map[k] = v; asked[sid, default: [:]][k] = Date() }
                resolved[sid] = map
                if let c = r.cwd, cwd[sid] != c { cwd[sid] = c }
            }
        }
        return resolved[sid] ?? [:]
    }

    /// A path relative to the chat's folder, when it is inside it.
    func relative(_ path: String, sid: String) -> String {
        guard let c = cwd[sid], path.hasPrefix(c + "/") else { return path }
        return String(path.dropFirst(c.count + 1))
    }

    /// The file names one message mentions, plus the files its tool calls wrote.
    static func names(in m: Message) -> [String] {
        var out: [String] = []
        if !m.text.isEmpty {
            out = MarkdownText.Block.parse(m.text).flatMap(\.inlineTexts)
                .flatMap { candidates(in: MarkdownText.attributed($0)) }
        }
        for r in m.tool_runs ?? [] where ["Write", "Update", "Edit notebook"].contains(r.display) {
            if let p = r.args["file_path"] ?? r.args["notebook_path"] ?? r.args["path"], !p.isEmpty { out.append(p) }
        }
        return out
    }

    static func link(for name: String) -> URL? {
        var c = URLComponents()
        c.scheme = scheme
        c.host = "open"
        c.queryItems = [URLQueryItem(name: "n", value: name)]
        return c.url
    }

    // ------------------------------------------------------------ finding candidates

    private static let exts = "png|jpe?g|gif|webp|svg|pdf|html?|md|markdown|mdx|csv|tsv|xlsx?|xlsm|docx?|pptx?|numbers|pages|key|json|jsonl|ndjson|ya?ml|toml|xml|txt|log|py|ipynb|[rR]|[rR]md|qmd|js|mjs|cjs|ts|tsx|jsx|css|scss|sh|bash|zsh|c|h|cc|cpp|hpp|rs|go|java|kt|swift|rb|php|pl|jl|lua|sql|tex|bib|bed|bam|sam|vcf|fa|fasta|fq|fastq|gff3?|gtf|bw|bigwig|pdb|cif|nwk|zip|tar|gz|tgz|bz2|xz|7z|mp4|mov|m4v|webm|mkv|mp3|wav|m4a|flac|parquet|feather|h5|hdf5|npy|npz|pkl|rds|RData|sqlite|db|smk|nf|wdl|diff|patch|heic|tiff?|bmp|avif|ico|ini|cfg|conf|rst|org|srt|vtt|epub|rtf|odt|ods|lock|env|dockerfile|Dockerfile|Makefile|Snakefile"
    private static let roots = "Users|private|tmp|Volumes|opt|Applications|var|etc|Library|System|usr|home|u|scratch|data|mnt|srv|project|lustre|gpfs|work|nfs|storage|groups"

    private static let absRE = try! NSRegularExpression(pattern:
        #"(^|[\s(\[{"'`“‘:=>])((?:~|/(?:"# + roots + #"))/[^\s'"`<>()\[\]{},;|]*[^\s'"`<>()\[\]{},;|.:!?])"#)
    private static let relRE = try! NSRegularExpression(pattern:
        #"(^|[\s(\[{"'“‘:=>*])((?:\.{1,2}/)?(?:[\w@+.-]+/)*[\w@+-][\w@+.-]*\.(?:"# + exts
        + #")(?::\d+(?::\d+)?)?)(?=$|[\s)\]}"'”’,;:!?*]|\.(?:\s|$))"#)
    private static let inlineRE = try! NSRegularExpression(pattern:
        #"^(?:(?:~|\.{1,2})?/)?(?:[\p{L}\p{N}_@+.,()' -]+/)*[\p{L}\p{N}_@+() -][\p{L}\p{N}_@+.,()' -]*(?:\.(?:"#
        + exts + #")|/)(?::\d+(?::\d+)?)?$|^(?:~|/(?:"# + roots + #"))(?:/[^\s]*)?$|^[\w@+.-]+(?:/[\w@+.-]+)+/?$"#)
    private static let urlRE = try! NSRegularExpression(pattern: #"https?://[^\s<>()\[\]{}"'`]+[^\s<>()\[\]{}"'`.,;:!?]"#)
    private static let versionRE = try! NSRegularExpression(pattern: #"^\d+(\.\d+)+$"#)
    private static let domainRE = try! NSRegularExpression(pattern: #"^[\w-]+\.(com|org|net|io|edu|gov|ai|dev|app)$"#,
                                                          options: .caseInsensitive)

    private static func whole(_ re: NSRegularExpression, _ s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    enum Span { case file(String), web(URL) }

    /// Where in this text the file names and bare web addresses are.
    static func spans(in attr: AttributedString) -> [(Range<AttributedString.Index>, Span)] {
        var out: [(Range<AttributedString.Index>, Span)] = []
        for run in attr.runs {
            if run.link != nil { continue }
            let text = String(attr[run.range].characters)
            guard text.contains("/") || text.contains(".") else { continue }
            if run.inlinePresentationIntent?.contains(.code) == true {
                // a whole code span that looks like a file name
                let v = text.trimmingCharacters(in: .whitespaces)
                guard v.count >= 2, v.count <= 600, !v.contains("://"), !v.contains("  "),
                      whole(inlineRE, v) else { continue }
                out.append((run.range, .file(v)))
                continue
            }
            var taken: [NSRange] = []
            let ns = NSRange(text.startIndex..., in: text)
            func add(_ r: NSRange, _ span: Span) {
                guard !taken.contains(where: { NSIntersectionRange($0, r).length > 0 }),
                      let sr = Range(r, in: text) else { return }
                let lo = text.distance(from: text.startIndex, to: sr.lowerBound)
                let len = text.distance(from: sr.lowerBound, to: sr.upperBound)
                let a = attr.index(run.range.lowerBound, offsetByCharacters: lo)
                let b = attr.index(a, offsetByCharacters: len)
                taken.append(r)
                out.append((a..<b, span))
            }
            for m in urlRE.matches(in: text, range: ns) {
                if let r = Range(m.range, in: text), let u = URL(string: String(text[r])) { add(m.range, .web(u)) }
            }
            for m in absRE.matches(in: text, range: ns) {
                let r = m.range(at: 2)
                if let sr = Range(r, in: text) { add(r, .file(String(text[sr]))) }
            }
            for m in relRE.matches(in: text, range: ns) {
                let r = m.range(at: 2)
                guard let sr = Range(r, in: text) else { continue }
                let s = String(text[sr])
                if whole(versionRE, s) || whole(domainRE, s) { continue }
                add(r, .file(s))
            }
        }
        return out
    }

    static func candidates(in attr: AttributedString) -> [String] {
        spans(in: attr).compactMap { if case .file(let n) = $0.1 { return n } else { return nil } }
    }

    /// The text with the files that exist turned into links (and bare web
    /// addresses too, which the Markdown parser leaves as text).
    func linkify(_ attr: AttributedString, sid: String?) -> AttributedString {
        var out = attr
        for (range, span) in Self.spans(in: attr) {
            switch span {
            case .web(let u):
                out[range].link = u
            case .file(let name):
                guard let sid, let info = resolved[sid]?[name], let u = Self.link(for: name) else { continue }
                if info.exists {
                    out[range].link = u
                    out[range].underlineStyle = .single
                } else if name.hasPrefix("/") || name.hasPrefix("~") {
                    // a full path that is not there: still tappable, to find files with its name
                    out[range].link = u
                    out[range].strikethroughStyle = .single
                    out[range].foregroundColor = .secondary
                }
            }
        }
        return out
    }
}

struct FilePreviewTarget: Identifiable {
    let id = UUID()
    let sid: String
    let info: ResolvedPath
}

private struct FileLinkSidKey: EnvironmentKey {
    static let defaultValue: String? = nil
}

extension EnvironmentValues {
    /// The chat whose files names in an answer are looked up against. Unset
    /// (a share image, a live answer) means no lookups.
    var fileLinkSid: String? {
        get { self[FileLinkSidKey.self] }
        set { self[FileLinkSidKey.self] = newValue }
    }
}
