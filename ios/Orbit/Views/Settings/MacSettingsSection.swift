import SwiftUI

/// The Mac's own Settings, one link each — the same tabs as the web page.
struct MacSettingsSection: View {
    #if DEBUG
    /// Development only: `ORBIT_SETTINGS_PAGE=models|fallback|general|tools|mcp|claude|codex|phone|status`
    /// (with `ORBIT_TAB=settings`) opens that page, so each can be screenshotted without a finger.
    @State private var debugPage: String?
    private static var debugOpened = false
    #endif

    var body: some View {
        section
        #if DEBUG
            .navigationDestination(isPresented: Binding(get: { debugPage != nil },
                                                        set: { if !$0 { debugPage = nil } })) {
                switch debugPage {
                case "models": ModelsKeysView()
                case "fallback": FallbackView()
                case "general": MacGeneralView()
                case "server": LocalServerView()
                case "tools": ToolsRulesView()
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
                    DebugCodexPage(page: debugPage ?? "")
                default: StatusHealthView()
                }
            }
            .onAppear {
                if !Self.debugOpened, let p = ProcessInfo.processInfo.environment["ORBIT_SETTINGS_PAGE"] {
                    Self.debugOpened = true
                    debugPage = p
                }
            }
        #endif
    }

    private var section: some View {
        Section {
            NavigationLink { ModelsKeysView() } label: { Label("Models & keys", systemImage: "key") }
            NavigationLink { FallbackView() } label: {
                Label("When a model keeps failing", systemImage: "arrow.triangle.branch")
            }
            NavigationLink { MacGeneralView() } label: { Label("General", systemImage: "slider.horizontal.3") }
            NavigationLink { LocalServerView() } label: { Label("Local server", systemImage: "cpu") }
            NavigationLink { ToolsRulesView() } label: { Label("Tools & rules", systemImage: "wrench.and.screwdriver") }
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
