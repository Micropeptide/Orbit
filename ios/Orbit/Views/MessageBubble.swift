import SwiftUI

struct MessageBubble: View {
    let message: Message

    var body: some View {
        if message.isUser {
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(.tint.opacity(0.14), in: .rect(cornerRadius: 17))
            }
        } else {
            VStack(alignment: .leading, spacing: 7) {
                if let model = message.model, !model.isEmpty {
                    Text(model).font(.caption2.smallCaps()).foregroundStyle(.secondary)
                }
                ForEach(message.tools ?? [], id: \.self) { t in
                    Text(t)
                        .font(.caption.monospaced())
                        .foregroundStyle(.orange)
                        .padding(.vertical, 5).padding(.horizontal, 9)
                        .background(.orange.opacity(0.10), in: .rect(cornerRadius: 7))
                }
                MarkdownText(message.text)
                if let thinking = message.thinking, !thinking.isEmpty {
                    ThinkingBlock(text: thinking)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contextMenu {
                Button {
                    UIPasteboard.general.string = message.text
                } label: { Label("Copy", systemImage: "doc.on.doc") }
            }
        }
    }
}

/// Markdown, rendered block by block.
///
/// `AttributedString(markdown:)` alone collapses fenced code and lists into one
/// run of text, which is exactly what you least want to read on a phone. This
/// splits the answer into blocks first and gives code its own scrollable,
/// selectable, monospaced box.
struct MarkdownText: View {
    let raw: String
    init(_ raw: String) { self.raw = raw }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(Block.parse(raw).enumerated()), id: \.offset) { _, block in
                switch block {
                case .code(let language, let code):
                    CodeBlock(language: language, code: code)
                case .text(let markdown):
                    Text(Self.attributed(markdown))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private static func attributed(_ s: String) -> AttributedString {
        (try? AttributedString(
            markdown: s,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
        ?? AttributedString(s)
    }

    enum Block {
        case text(String)
        case code(language: String, code: String)

        /// Split on ``` fences. Deliberately simple: it handles what models
        /// actually emit, and never loses characters — anything unrecognised
        /// stays text rather than disappearing.
        static func parse(_ raw: String) -> [Block] {
            var blocks: [Block] = []
            var buffer: [String] = []
            var code: [String] = []
            var language = ""
            var inCode = false

            func flushText() {
                let t = buffer.joined(separator: "\n").trimmingCharacters(in: .newlines)
                if !t.isEmpty { blocks.append(.text(t)) }
                buffer = []
            }

            for line in raw.components(separatedBy: .newlines) {
                if line.hasPrefix("```") {
                    if inCode {
                        blocks.append(.code(language: language,
                                            code: code.joined(separator: "\n")))
                        code = []; language = ""; inCode = false
                    } else {
                        flushText()
                        language = String(line.dropFirst(3))
                            .trimmingCharacters(in: .whitespaces)
                        inCode = true
                    }
                    continue
                }
                if inCode { code.append(line) } else { buffer.append(line) }
            }
            // an answer cut off mid-fence still shows what arrived
            if inCode && !code.isEmpty {
                blocks.append(.code(language: language, code: code.joined(separator: "\n")))
            }
            flushText()
            return blocks
        }
    }
}

struct CodeBlock: View {
    let language: String
    let code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language.isEmpty ? "code" : language)
                    .font(.caption2.smallCaps()).foregroundStyle(.secondary)
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    withAnimation { copied = true }
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
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
            }
            .padding(.horizontal, 11).padding(.vertical, 6)

            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(.horizontal, 11)
                    .padding(.bottom, 10)
            }
        }
        .background(.quaternary.opacity(0.35), in: .rect(cornerRadius: 10))
    }
}
