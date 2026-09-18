import SwiftUI
import UIKit

/// An answer or a whole chat taken out of Orbit: as formatted text to paste
/// into Mail or Pages, a Markdown or HTML file, or a printout / PDF. The HTML
/// is built from the same block parser the transcript draws with.
enum AnswerExport {

    static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }

    /// Inline Markdown as HTML: bold, italics, code, strikethrough and links.
    static func inlineHTML(_ s: String) -> String {
        let attr = MarkdownText.attributed(s)
        var out = ""
        for run in attr.runs {
            var t = escape(String(attr[run.range].characters)).replacingOccurrences(of: "\n", with: "<br>")
            if let i = run.inlinePresentationIntent {
                if i.contains(.code) { t = "<code>\(t)</code>" }
                if i.contains(.stronglyEmphasized) { t = "<strong>\(t)</strong>" }
                if i.contains(.emphasized) { t = "<em>\(t)</em>" }
                if i.contains(.strikethrough) { t = "<del>\(t)</del>" }
            }
            if let link = run.link { t = "<a href=\"\(escape(link.absoluteString))\">\(t)</a>" }
            out += t
        }
        return out
    }

    /// An answer's Markdown as an HTML fragment.
    static func html(markdown: String) -> String {
        MarkdownText.Block.parse(markdown).map(blockHTML).joined(separator: "\n")
    }

    private static func blockHTML(_ b: MarkdownText.Block) -> String {
        switch b {
        case .text(let s): return "<p>\(inlineHTML(s))</p>"
        case .heading(let level, let s): return "<h\(level)>\(inlineHTML(s))</h\(level)>"
        case .code(let lang, let code):
            return "<pre><code class=\"language-\(escape(lang))\">\(escape(code))</code></pre>"
        case .math(let tex): return "<pre class=\"math\">$$\(escape(tex))$$</pre>"
        case .rule: return "<hr>"
        case .table(let rows):
            guard let head = rows.first else { return "" }
            let th = head.map { "<th>\(inlineHTML($0))</th>" }.joined()
            let body = rows.dropFirst().map { "<tr>" + $0.map { "<td>\(inlineHTML($0))</td>" }.joined() + "</tr>" }.joined()
            return "<table><thead><tr>\(th)</tr></thead><tbody>\(body)</tbody></table>"
        case .list(let items):
            let ordered = items.first?.number != nil
            let li = items.map { item -> String in
                let box = item.checked.map { $0 ? "☒ " : "☐ " } ?? ""
                return "<li style=\"margin-left:\(item.depth * 18)px\">\(box)\(inlineHTML(item.text))</li>"
            }.joined()
            return ordered ? "<ol>\(li)</ol>" : "<ul>\(li)</ul>"
        case .quote(let kind, let title, let body):
            let head = kind.map { "<p><strong>\(escape(title ?? $0.capitalized))</strong></p>" } ?? ""
            return "<blockquote>\(head)\(html(markdown: body))</blockquote>"
        }
    }

    static let style = """
        body{font:15px/1.55 -apple-system,Helvetica,sans-serif;max-width:780px;margin:30px auto;padding:0 20px;color:#1c1c1e}
        .u{background:#f4f3f0;border-radius:10px;padding:10px 14px;margin:14px 0}
        pre{background:#f4f3f0;padding:10px;border-radius:8px;overflow-x:auto;white-space:pre-wrap}
        code{font-family:ui-monospace,Menlo,monospace;font-size:92%}
        table{border-collapse:collapse}th,td{border:1px solid #bfbfbf;padding:4px 8px;vertical-align:top}
        th{background:#f2f2f2}blockquote{border-left:3px solid #ccc;margin:0;padding-left:12px;color:#555}
        img{max-width:100%;border-radius:8px}h1{font-size:20px}h3{margin-bottom:4px;color:#666;font-size:13px}
        """

    static func document(title: String, body: String) -> String {
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>\(escape(title))</title><style>\(style)</style></head><body>\(body)</body></html>"
    }

    /// A file under a readable name in its own temporary folder, for the share sheet.
    static func write(_ text: String, name: String, ext: String) throws -> URL {
        var safe = name.replacingOccurrences(of: #"[^\w -]+"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        safe = String(safe.prefix(60))
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-export-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent((safe.isEmpty ? "answer" : safe) + "." + ext)
        try Data(text.utf8).write(to: url, options: .atomic)
        return url
    }

    /// Formatted for Mail, Notes, Pages and Word; plain text for everything else.
    static func copyRich(markdown: String, plain: String) {
        let html = document(title: "", body: html(markdown: markdown))
        UIPasteboard.general.setItems([["public.html": html, "public.utf8-plain-text": plain]])
        Haptics.success()
    }

    /// The system print sheet, which also saves as PDF.
    @MainActor
    static func print(title: String, markdown: String) {
        let c = UIPrintInteractionController.shared
        let info = UIPrintInfo(dictionary: nil)
        info.jobName = title
        info.outputType = .general
        c.printInfo = info
        let f = UIMarkupTextPrintFormatter(markupText: document(title: title, body: html(markdown: markdown)))
        f.perPageContentInsets = UIEdgeInsets(top: 36, left: 36, bottom: 36, right: 36)
        c.printFormatter = f
        c.present(animated: true)
    }

    /// The whole chat as one HTML page, its figures inside it.
    static func chatHTML(title: String, messages: [Message], server: OrbitServer?) async -> String {
        var parts = ["<h1>\(escape(title))</h1>"]
        for m in messages {
            if m.isUser {
                let text = m.bang.map { "! " + $0.cmd + "\n\n" + $0.out } ?? m.text
                parts.append("<h3>You</h3><div class=\"u\">\(escape(text).replacingOccurrences(of: "\n", with: "<br>"))</div>")
                continue
            }
            if m.text.isEmpty && (m.plots ?? []).isEmpty { continue }
            parts.append("<h3>\(escape(m.model ?? "Orbit"))</h3><div>\(html(markdown: m.text))</div>")
            for p in m.plots ?? [] {
                guard let server, let data = try? await server.fetchRaw(p) else { continue }
                let mime = p.lowercased().hasSuffix(".png") ? "image/png"
                    : p.lowercased().hasSuffix(".svg") ? "image/svg+xml" : "image/jpeg"
                parts.append("<p><img src=\"data:\(mime);base64,\(data.base64EncodedString())\"></p>")
            }
        }
        return document(title: title, body: parts.joined(separator: "\n"))
    }
}

// ------------------------------------------------------------------ small pieces for a message

/// Under a note sent mid-answer: whether the answer read it.
struct NoteReadState: View {
    let sid: String?
    let text: String
    @ObservedObject private var store = TranscriptExtras.shared

    var body: some View {
        Text(sid.flatMap { store.notes[$0]?[text] } ?? "sent while it was working")
            .font(.caption2).foregroundStyle(.secondary)
    }
}

/// Pick the words to quote: select them, then Quote.
struct QuotePartSheet: View {
    let text: String
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var selection = ""

    var body: some View {
        NavigationStack {
            SelectableText(text: text, selection: $selection)
                .padding(.horizontal, 12)
                .navigationTitle("Select what to quote")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Quote") {
                            state.quoteInDraft(selection.trimmingCharacters(in: .whitespacesAndNewlines))
                            dismiss()
                        }
                        .disabled(selection.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
        }
    }
}

/// A read-only text view that reports what is selected.
struct SelectableText: UIViewRepresentable {
    let text: String
    @Binding var selection: String

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> UITextView {
        let v = UITextView()
        v.isEditable = false
        v.isSelectable = true
        v.font = .preferredFont(forTextStyle: .body)
        v.adjustsFontForContentSizeCategory = true
        v.backgroundColor = .clear
        v.text = text
        v.delegate = context.coordinator
        return v
    }

    func updateUIView(_ v: UITextView, context: Context) { context.coordinator.parent = self }

    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: SelectableText
        init(_ p: SelectableText) { parent = p }
        func textViewDidChangeSelection(_ v: UITextView) {
            guard let r = v.selectedTextRange else { return }
            parent.selection = v.text(in: r) ?? ""
        }
    }
}
