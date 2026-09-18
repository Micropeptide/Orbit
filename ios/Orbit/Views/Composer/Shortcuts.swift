import SwiftUI

/// Every keyboard shortcut, for an iPad with a keyboard. Holding ⌘ also lists
/// them, since each is a titled command.
struct ShortcutsSheet: View {
    @Environment(\.dismiss) private var dismiss

    static let groups: [(String, [(String, String)])] = [
        ("Writing", [
            ("⌘↩", "send (queues it while an answer runs)"),
            ("⌘⇧↩", "send into the running answer, as a note it reads next"),
            ("/", "commands"),
            ("@", "mention a file"),
            ("!", "shell mode — run a command yourself; the output joins the chat"),
            ("#", "save the line to memory"),
            ("⌃R", "search what you sent before"),
            ("⌃L", "clear the box"),
        ]),
        ("While it works", [
            ("Esc", "stop the answer (or clear the box)"),
            ("⌘⌫", "rewind to an earlier message"),
            ("⇧Tab", "cycle the permission mode (plan, accept edits, auto…)"),
            ("⌃O", "show every tool call in full"),
            ("⌃T", "show or hide the todo list"),
            ("⌃H", "hide or show finished tool rows"),
        ]),
        ("Around the chat", [
            ("⌘K", "change the model"),
            ("⌘F", "find in this chat"),
            ("⌘G", "jump to one of your messages"),
            ("⌘N", "new chat"),
            ("⌘/", "this help"),
        ]),
    ]

    var body: some View {
        NavigationStack {
            List {
                ForEach(Self.groups, id: \.0) { group, keys in
                    Section(group) {
                        ForEach(keys, id: \.0) { key, what in
                            HStack(alignment: .firstTextBaseline, spacing: 12) {
                                Text(key).font(.callout.monospaced().weight(.semibold))
                                    .frame(minWidth: 54, alignment: .leading)
                                Text(what).font(.callout).foregroundStyle(.secondary)
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
            }
            .navigationTitle("Keyboard shortcuts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}

/// A hardware keyboard's commands for a conversation. They are real buttons with
/// titles, kept invisible, so iPadOS lists them when ⌘ is held.
struct KeyCommands: View {
    struct Command: Identifiable {
        let title: String
        let key: KeyEquivalent
        let modifiers: EventModifiers
        let enabled: Bool
        let action: () -> Void
        /// By key rather than title: two shortcuts may share a title (Esc and ⌃L both clear the box).
        var id: String { "\(modifiers.rawValue)-\(key.character)" }

        init(_ title: String, _ key: KeyEquivalent, _ modifiers: EventModifiers = [],
             enabled: Bool = true, action: @escaping () -> Void) {
            self.title = title; self.key = key; self.modifiers = modifiers
            self.enabled = enabled; self.action = action
        }
    }

    let commands: [Command]

    var body: some View {
        ZStack {
            ForEach(commands.filter(\.enabled)) { c in
                Button(c.title, action: c.action)
                    .keyboardShortcut(c.key, modifiers: c.modifiers)
            }
        }
        .frame(width: 0, height: 0)
        .opacity(0)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
