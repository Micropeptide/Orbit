import SwiftUI

/// The Mac's own Settings, one link each — the same tabs as the web page.
struct MacSettingsSection: View {
    var body: some View { section }

    private var section: some View {
        Section {
            NavigationLink { ModelsKeysView() } label: { Label("Models & keys", systemImage: "key") }
            NavigationLink { FallbackView() } label: {
                Label("When a model keeps failing", systemImage: "arrow.triangle.branch")
            }
            NavigationLink { MacGeneralView() } label: { Label("General", systemImage: "slider.horizontal.3") }
            NavigationLink { LocalServerView() } label: { Label("Local server", systemImage: "cpu") }
            NavigationLink { ToolsRulesView() } label: { Label("Tools & rules", systemImage: "wrench.and.screwdriver") }
            NavigationLink { EasyModeView() } label: { Label("Easy mode", systemImage: "wrench") }
            NavigationLink { MCPServersView() } label: { Label("MCP servers", systemImage: "puzzlepiece.extension") }
            NavigationLink { ClaudeCodeSettingsView() } label: { Label("Claude Code", systemImage: "terminal") }
            NavigationLink { CodexSettingsView() } label: { Label("Codex", systemImage: "chevron.left.forwardslash.chevron.right") }
            NavigationLink { PhoneAccessView() } label: { Label("Phone access", systemImage: "iphone.radiowaves.left.and.right") }
            NavigationLink { StatusHealthView() } label: { Label("Status & health", systemImage: "stethoscope") }
        } header: {
            Text("Settings on the Mac")
        } footer: {
            Text("The same settings as Orbit's page on the Mac. Changes are made there, for every device.")
        }
    }
}

#if DEBUG
/// Development only: `ORBIT_SETTINGS_PAGE=models|fallback|general|tools|easy|mcp|claude|codex|phone|status`
/// (with `ORBIT_TAB=settings`) opens that page, so each can be screenshotted without a finger.
///
/// This belongs to the whole Settings screen, not to one of its sections. A
/// `navigationDestination` inside a `List` sits in a lazy container: the stack can only
/// see it while the rows that hold it are on screen, so the page opened or did not
/// depending on where Settings happened to be scrolled — and SwiftUI says it will stop
/// working altogether. Applied to the List itself, it is always visible to the stack.
struct DebugSettingsDestination: ViewModifier {
    @State private var page: String?
    private static var opened = false

    func body(content: Content) -> some View {
        content
            .navigationDestination(isPresented: Binding(get: { page != nil },
                                                        set: { if !$0 { page = nil } })) {
                switch page {
                case "models": ModelsKeysView()
                case "fallback": FallbackView()
                case "general": MacGeneralView()
                case "server": LocalServerView()
                case "tools": ToolsRulesView()
                case "easy": EasyModeView()
                case "mcp": MCPServersView()
                case "claude": ClaudeCodeSettingsView()
                case "claude-options": ClaudeOptionsView()
                case "claude-permissions": ClaudePermissionsView()
                case "claude-skills": ClaudeSkillsView()
                case "claude-plugins": ClaudePluginsView()
                case "claude-mcp": ClaudeMCPView()
                case "codex": CodexSettingsView()
                case "phone": PhoneAccessView()
                case let p? where p.hasPrefix("provider:"): DebugProviderPage(id: String(p.dropFirst(9)))
                case "codex-options", "codex-agents", "codex-skills", "codex-plugins", "codex-mcp":
                    DebugCodexPage(page: page ?? "")
                default: StatusHealthView()
                }
            }
            .onAppear {
                if !Self.opened, let p = ProcessInfo.processInfo.environment["ORBIT_SETTINGS_PAGE"] {
                    Self.opened = true
                    page = p
                }
            }
    }
}
#endif

extension View {
    /// No-op in a release build.
    func debugSettingsDestination() -> some View {
        #if DEBUG
        return modifier(DebugSettingsDestination())
        #else
        return self
        #endif
    }
}

#if DEBUG
/// Screens that need something loaded first, for the development hook above.
private struct DebugProviderPage: View {
    @EnvironmentObject var state: AppState
    let id: String
    @State private var overview: HarnessOverview?

    var body: some View {
        Group {
            if let overview { ProviderDetailView(providerID: id, overview: overview) } else { LoadingRow() }
        }
        .task { overview = try? await state.requireServer().harness() }
    }
}

private struct DebugCodexPage: View {
    @EnvironmentObject var state: AppState
    let page: String
    @State private var cfg: CodexConfig?

    var body: some View {
        Group {
            if let cfg {
                switch page {
                case "codex-options": CodexOptionsView(saved: cfg.settings, hosts: []) { _ in }
                case "codex-agents": CodexAgentsView(text: cfg.agentsMD, path: cfg.agentsMDPath) { _ in }
                case "codex-skills": CodexSkillsView(skills: cfg.skills) {}
                case "codex-plugins": CodexPluginsView(cfg: cfg) {}
                default: CodexMCPView(cfg: cfg) {}
                }
            } else { LoadingRow() }
        }
        .task { cfg = try? await state.requireServer().codexConfig() }
    }
}
#endif
