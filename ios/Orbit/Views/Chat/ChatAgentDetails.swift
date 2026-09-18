import SwiftUI

/// The rest of a Claude Code or Codex chat's panel, under "Where this chat
/// works": extra folders it may use, how to continue it in a terminal, the
/// session's profile, skills and MCP servers, what Claude Code reports while it
/// answers, and for Codex the ChatGPT limits and tools for this chat's host.

/// "Also allow": more folders the chat may use besides its own (`--add-dir`).
struct AlsoAllowSection: View {
    @Binding var dirs: [String]
    let host: String
    let harness: HarnessKind
    @State private var adding = ""

    private var trimmed: String { adding.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Section {
            ForEach(dirs, id: \.self) { d in
                HStack {
                    Image(systemName: "folder").foregroundStyle(.secondary)
                    Text(PathText.short(d, keep: 3))
                        .font(.callout.monospaced()).lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 0)
                    Button {
                        dirs.removeAll { $0 == d }
                    } label: {
                        Image(systemName: "minus.circle.fill").foregroundStyle(.red)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Stop allowing \(d)")
                }
            }
            HStack(spacing: 10) {
                TextField(host.isEmpty ? "another folder on the Mac" : "another folder on \(host)", text: $adding)
                    .font(.callout.monospaced())
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .onSubmit(add)
                Button("Add", action: add).disabled(trimmed.isEmpty)
            }
            if !host.isEmpty {
                NavigationLink {
                    RemoteFolderBrowser(host: host, start: "~") { p in
                        if !dirs.contains(p) { dirs.append(p) }
                    }
                } label: {
                    Label("Choose on \(host)…", systemImage: "folder.badge.plus")
                }
            }
        } header: {
            Text("Also allow")
        } footer: {
            Text(harness == .codex
                 ? "More folders Codex may write to, besides its own (on this Mac). Saved with the chat."
                 : "More folders Claude Code may use, besides its own (--add-dir). Saved with the chat.")
        }
    }

    private func add() {
        for part in adding.split(whereSeparator: \.isNewline) {
            let p = part.trimmingCharacters(in: .whitespaces)
            if !p.isEmpty, !dirs.contains(p) { dirs.append(p) }
        }
        adding = ""
    }
}

/// Continue in a terminal, session details, and live reports.
struct ChatAgentDetailSections: View {
    @EnvironmentObject var state: AppState
    let sid: String
    let info: ChatAgentInfo
    @State private var codex: CodexInfo?
    @State private var reply: ControlReply?
    @State private var asking: String?
    @State private var hostBusy: String?
    @State private var hostNote: String?
    @State private var confirmCopyLogin = false

    /// Whether Claude Code is answering in this chat now. `info.running` is only
    /// what it was when the sheet opened; the app's own state follows it after that.
    private var running: Bool {
        (state.streaming && state.openChat?.sid == sid) || state.runningChats.contains(sid)
    }

    var body: some View {
        if let cmd = info.terminalCommand {
            Section {
                Text(cmd)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
                Button {
                    UIPasteboard.general.string = cmd
                    Haptics.tap()
                    state.toast("Command copied")
                } label: { Label("Copy command", systemImage: "doc.on.doc") }
            } header: {
                Text("Continue in a terminal")
            } footer: {
                Text(info.codex
                     ? "The same thread opens in the Codex CLI and app."
                     : "Run it on your Mac to carry on this chat's Claude session in a terminal.")
            }
        }

        if info.codex {
            codexSections
        } else {
            claudeSections
        }
    }

    // ------------------------------------------------------------ Claude Code

    @ViewBuilder
    private var claudeSections: some View {
        Section {
            LabeledContent("Claude session") {
                Text(info.session ?? "starts with the next message")
                    .font(info.session == nil ? .callout : .caption.monospaced())
                    .lineLimit(1).truncationMode(.middle)
            }
            if let p = info.profile { LabeledContent("Profile", value: p) }
            LabeledContent("Skills offered") {
                Text(info.skills.isEmpty ? "—" : info.skills.joined(separator: ", "))
                    .multilineTextAlignment(.trailing).lineLimit(4)
            }
            LabeledContent("Claude Code", value: info.version ?? (info.installed ? "installed" : "not installed"))
            if info.mcp.isEmpty {
                LabeledContent("MCP servers",
                               value: info.mcpConfigured.isEmpty ? "none" : info.mcpConfigured.joined(separator: ", "))
            }
        } header: {
            Text("Session")
        }

        if !info.mcp.isEmpty {
            Section("MCP servers") {
                ForEach(info.mcp) { m in
                    HStack(spacing: 8) {
                        Circle().fill(m.ok ? Color.green : m.status == "needs-auth" ? .orange : .red)
                            .frame(width: 7, height: 7)
                        Text(m.name).lineLimit(1).truncationMode(.middle)
                        Spacer()
                        Text(m.status).font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }

        Section {
            controlButton("Context usage", systemImage: "gauge.with.dots.needle.33percent",
                          subtype: "get_context_usage")
            controlButton("MCP status", systemImage: "point.3.connected.trianglepath.dotted",
                          subtype: "mcp_status")
        } header: {
            Text("While it answers")
        } footer: {
            Text(running ? "Claude Code is answering: ask it directly."
                              : "Available while Claude Code is answering in this chat.")
        }
        .sheet(item: $reply) { r in ControlReplyView(reply: r) }
    }

    private func controlButton(_ title: String, systemImage: String, subtype: String) -> some View {
        Button {
            Task { await ask(title, subtype) }
        } label: {
            HStack {
                Label(title, systemImage: systemImage)
                if asking == subtype { Spacer(); ProgressView().controlSize(.small) }
            }
        }
        .disabled(!running || asking != nil)
    }

    private func ask(_ title: String, _ subtype: String) async {
        guard let server = state.server else { return }
        asking = subtype
        defer { asking = nil }
        do {
            reply = ControlReply(title: title, text: try await server.claudeControl(sid: sid, subtype: subtype))
        } catch {
            state.toast(error.localizedDescription)
        }
    }

    // ------------------------------------------------------------ Codex

    @ViewBuilder
    private var codexSections: some View {
        Section {
            if let c = codex {
                LabeledContent("Installed", value: c.installed ? (c.version ?? "yes") : "no — brew install codex")
                LabeledContent("Your account") {
                    Text(c.loginLine).multilineTextAlignment(.trailing)
                }
                if let rl = c.rateLimits, rl.primary?.usedPercent != nil || rl.secondary?.usedPercent != nil {
                    if let p = rl.primary, p.usedPercent != nil {
                        LabeledContent("5 hours", value: limitText(p))
                    }
                    if let s = rl.secondary, s.usedPercent != nil {
                        LabeledContent("Week", value: limitText(s))
                    }
                }
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Reading Codex…").font(.footnote).foregroundStyle(.secondary)
                }
            }
            LabeledContent("This chat") {
                Text(info.codexThread.map { "thread \($0)" } ?? "starts a Codex thread with its first message")
                    .font(info.codexThread == nil ? .callout : .caption.monospaced())
                    .multilineTextAlignment(.trailing).lineLimit(2).truncationMode(.middle)
            }
        } header: {
            Text("Codex")
        } footer: {
            Text("Your ChatGPT account's models use Codex's own sign-in and its 5-hour and weekly limits. "
                 + "Every other provider runs through Orbit's gateway, with your key kept in Orbit.")
        }
        .task { if codex == nil, let server = state.server { codex = try? await server.codexInfo() } }

        if let h = info.host {
            Section {
                Button {
                    Task { await install(h) }
                } label: {
                    HStack {
                        Label("Install or check Codex there", systemImage: "arrow.down.app")
                        if hostBusy == "install" { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(hostBusy != nil)
                Button {
                    confirmCopyLogin = true
                } label: {
                    HStack {
                        Label("Copy this Mac's Codex sign-in there", systemImage: "person.badge.key")
                        if hostBusy == "login" { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(hostBusy != nil)
                if let hostNote { Text(hostNote).font(.caption).foregroundStyle(.secondary) }
            } header: {
                Text("On \(h)")
            } footer: {
                Text("Codex runs on \(h), reaching your models through Orbit. The sign-in is only needed "
                     + "for your ChatGPT account's models.")
            }
            .confirmationDialog("Copy your Codex sign-in to \(h)?", isPresented: $confirmCopyLogin,
                                titleVisibility: .visible) {
                Button("Copy sign-in") { Task { await copyLogin(h) } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This Mac's ~/.codex/auth.json is saved there readable only by your account. "
                     + "Other people with admin rights on that machine could still read it.")
            }
        }
    }

    private func limitText(_ l: CodexInfo.Limit) -> String {
        var s = "\(l.left)% left"
        if let r = l.resetsAt {
            s += ", resets " + Date(timeIntervalSince1970: r).formatted(.dateTime.weekday(.abbreviated).hour().minute())
        }
        return s
    }

    private func install(_ host: String) async {
        guard let server = state.server else { return }
        hostBusy = "install"
        hostNote = "Checking \(host)… an install can take a few minutes."
        defer { hostBusy = nil }
        do {
            let r = try await server.codexInstall(host: host)
            hostNote = "Codex \(r.version ?? "") on \(host)" + (r.path.map { ": \($0)" } ?? "")
        } catch { hostNote = error.localizedDescription }
    }

    private func copyLogin(_ host: String) async {
        guard let server = state.server else { return }
        hostBusy = "login"
        defer { hostBusy = nil }
        do {
            try await server.codexCopyLogin(host: host)
            hostNote = "Signed in on \(host)."
        } catch { hostNote = error.localizedDescription }
    }
}

/// What Claude Code answered to a control request, as it sent it.
struct ControlReply: Identifiable {
    let id = UUID()
    let title: String
    let text: String
}

struct ControlReplyView: View {
    let reply: ControlReply
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(reply.text.isEmpty ? "(no reply)" : reply.text)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
            .navigationTitle(reply.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarLeading) {
                    Button { UIPasteboard.general.string = reply.text } label: { Image(systemName: "doc.on.doc") }
                        .accessibilityLabel("Copy")
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
