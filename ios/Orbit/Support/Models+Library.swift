import Foundation

// The Library: saved prompts, the document library, agents, skills, memory and
// instructions. Shapes follow the Mac's endpoints exactly; anything optional on
// the Mac is optional here, so an older or newer Mac still decodes.

/// One saved prompt. The Mac lists them as a dictionary keyed by name; the
/// built-in ones (`/init`, `/review`) carry `builtin` and cannot be deleted.
struct SavedPrompt: Identifiable, Hashable {
    var name: String
    var text: String
    var desc: String
    var builtin: Bool
    var id: String { name }
}

struct KnowledgeDoc: Identifiable, Codable, Hashable {
    var name: String
    var bytes: Int?
    var mtime: Double?
    var project: String?
    var chunks: Int?
    var id: String { name }

    var sizeText: String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes ?? 0), countStyle: .file)
    }
}

/// What a reindex reports.
struct KnowledgeIndexStats: Codable {
    struct Failure: Codable, Hashable { var doc: String?; var why: String? }
    var docs: Int?
    var chunks: Int?
    var failures: [Failure]?
    var error: String?
}

struct AgentPreset: Identifiable, Hashable {
    var name: String
    var instructions: String
    var desc: String
    /// nil or empty means every tool
    var tools: [String]?
    var id: String { name }
}

struct SkillInfo: Identifiable, Codable, Hashable {
    var name: String
    var title: String?
    var chars: Int?
    var id: String { name }
}

struct MemoryNote: Identifiable, Codable, Hashable {
    var name: String
    var title: String?
    var chars: Int?
    var mtime: Double?
    var id: String { name }
}

/// A memory the Mac suggests saving from the open chat.
struct SuggestedMemory: Identifiable, Codable, Hashable {
    var name: String
    var content: String
    var id: String { name + "|" + content.prefix(40) }
}

/// Claude Code's own instructions and memory for a folder, as a terminal
/// session sees them.
struct ClaudeMemoryState: Codable {
    struct InstructionFile: Codable, Identifiable, Hashable {
        var scope: String
        var path: String
        var label: String
        var exists: Bool?
        var text: String?
        var id: String { scope }
    }
    struct Item: Codable, Identifiable, Hashable {
        var file: String
        var name: String
        var description: String?
        var type: String?
        var mtime: Double?
        var text: String?
        var id: String { file }
    }
    struct Memory: Codable {
        var cwd: String?
        var dir: String?
        var index: String?
        var items: [Item]?
    }
    struct Folder: Codable, Identifiable, Hashable {
        var key: String?
        var path: String
        var count: Int?
        var mtime: Double?
        var id: String { path }
    }
    var cwd: String
    var instructions: [InstructionFile]?
    var memory: Memory?
    var folders: [Folder]?
    var chat_instructions: String?
}

struct ClaudeCommand: Codable, Hashable {
    var name: String?
    var description: String?
    var argumentHint: String?
}

/// What the Mac holds for the chat it has open: its agent and its own instructions.
struct ChatLibraryState: Codable {
    var sid: String?
    var agent: String?
    var sys_override: String?
    var project: String?
}

// ------------------------------------------------------------ prompt expansion

enum PromptExpander {
    /// `/name words`: `$ARGUMENTS` becomes the words, `$1`… (or `${1}`) each one,
    /// with quotes grouping — only for as many words as were given, so "$5 cap"
    /// stays. With words and no placeholder they go at the end. Same as the Mac.
    static func expand(_ body: String, rest: String) -> String {
        var out = body
        let words = positional(rest)
        var used = false
        if out.contains("$ARGUMENTS") {
            out = out.replacingOccurrences(of: "$ARGUMENTS", with: rest)
            used = true
        }
        // ${n} | $n not followed by a digit, or by [.,] and a digit
        if let re = try? NSRegularExpression(pattern: #"\$\{(\d)\}|\$(\d)(?!\d|[.,]\d)"#) {
            let ns = out as NSString
            var result = ""
            var last = 0
            for m in re.matches(in: out, range: NSRange(location: 0, length: ns.length)) {
                result += ns.substring(with: NSRange(location: last, length: m.range.location - last))
                let g = m.range(at: 1).location != NSNotFound ? m.range(at: 1) : m.range(at: 2)
                let n = Int(ns.substring(with: g)) ?? 0
                if n > 0 && n <= words.count {
                    result += words[n - 1]
                    used = true
                } else {
                    result += ns.substring(with: m.range)
                }
                last = m.range.location + m.range.length
            }
            result += ns.substring(from: last)
            out = result
        }
        if !rest.isEmpty && !used {
            while let c = out.last, c.isWhitespace { out.removeLast() }
            out += "\n\n" + rest
        }
        return out
    }

    /// Words, with "quoted phrases" kept together and their quotes dropped.
    static func positional(_ s: String) -> [String] {
        guard let re = try? NSRegularExpression(pattern: #""[^"]*"|\S+"#) else { return [] }
        let ns = s as NSString
        return re.matches(in: s, range: NSRange(location: 0, length: ns.length)).map {
            var w = ns.substring(with: $0.range)
            if w.hasPrefix("\"") { w.removeFirst() }
            if w.hasSuffix("\"") { w.removeLast() }
            return w
        }
    }
}
