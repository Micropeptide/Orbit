import SwiftUI

struct RootView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.horizontalSizeClass) private var width
    @AppStorage("theme") private var theme = "system"
    @State private var showSample = false
    /// The welcome tips are shown once, after this phone first pairs.
    @AppStorage("orbit.tipsShown") private var tipsShown = false
    /// The welcome — what Orbit is, connecting it, the guide — once, the first time the app opens.
    @AppStorage("orbit.welcomed") private var welcomed = false
    /// One object for the life of the app, so code blocks read it without redrawing.
    @State private var blockActions = BlockActions()

    /// Development only: `ORBIT_TAB=scheduled|files|library|settings` opens on that tab so the
    /// simulator can be screenshotted without a finger. Compiled out of release.
    /// Development only: `ORBIT_SKIP_WELCOME=1` keeps the welcome out of the way of scripted runs;
    /// `ORBIT_WELCOME=1` shows it again.
    private static var skipWelcome: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.environment["ORBIT_SKIP_WELCOME"] == "1"
        #else
        return false
        #endif
    }

    private static var initialTab: String {
        #if DEBUG
        return ProcessInfo.processInfo.environment["ORBIT_TAB"] ?? "chats"
        #else
        return "chats"
        #endif
    }

    var body: some View {
        LockGate {
        Group {
            if state.isPaired {
                // .tabItem rather than the iOS 18 `Tab` type, so this still runs
                // on iOS 17 devices.
                TabView(selection: $state.tab) {
                    // On an iPad or a landscape Max, the list and the
                    // conversation sit side by side.
                    Group {
                        if width == .regular { SplitChats() } else { ChatListView() }
                    }
                    .tabItem { Label("Chats", systemImage: "bubble.left.and.bubble.right") }
                    .tag("chats")
                    ScheduledView()
                        .tabItem { Label("Scheduled", systemImage: "clock") }
                        .tag("scheduled")
                    FilesView()
                        .tabItem { Label("Files", systemImage: "folder") }
                        .tag("files")
                    LibraryView()
                        .tabItem { Label("Library", systemImage: "books.vertical") }
                        .tag("library")
                    SettingsView()
                        .tabItem { Label("Settings", systemImage: "gearshape") }
                        .tag("settings")
                }
                // `/tasks`, from anywhere: set state.work.showTasks (AppState+Work.swift)
                .sheet(isPresented: $state.work.showTasks) { TasksSheet() }
                .sheet(isPresented: $state.work.showTips) {
                    OnboardingTips { tipsShown = true }
                }
            } else {
                PairingView()
            }
        }
        .animation(.default, value: state.isPaired)
        .onChange(of: state.isPaired) { _, paired in
            // a moment after the list appears, not over the pairing screen as it goes
            guard paired, !tipsShown else { return }
            Task {
                try? await Task.sleep(nanoseconds: 700_000_000)
                if state.isPaired, !tipsShown { state.work.showTips = true }
            }
        }
        }
        .fullScreenCover(isPresented: Binding(get: { !welcomed && !Self.skipWelcome }, set: { if !$0 { welcomed = true } })) {
            WelcomeView { welcomed = true }
        }
        .preferredColorScheme(Appearance.scheme(theme))
        .alert("Pair with a different Mac?", isPresented: Binding(
            get: { state.pendingPair != nil }, set: { if !$0 { state.pendingPair = nil } })) {
            Button("Replace pairing", role: .destructive) {
                if let p = state.pendingPair { state.pair(from: p.url, confirmed: true) }
            }
            Button("Cancel", role: .cancel) { state.pendingPair = nil }
        } message: {
            Text("A link asked to pair this phone with \(state.pendingPair?.host ?? "another computer"). "
                 + "Your chats, prompts and attachments would go there instead of \(state.pairing?.name ?? "your Mac"). "
                 + "Only continue if you just showed this code on your own Mac.")
        }
        .environment(\.blockActions, blockActions)
        .onAppear {
            blockActions.state = state
            state.tab = Self.initialTab
            #if DEBUG
            if ProcessInfo.processInfo.environment["ORBIT_WELCOME"] == "1" { welcomed = false }
            #endif
            #if DEBUG
            showSample = MarkdownSample.wanted
            #endif
        }
        #if DEBUG
        .sheet(isPresented: $showSample) { MarkdownSample() }
        #endif
    }
}

/// A small banner rather than an alert: losing the Mac mid-scroll should not
/// take over the screen, but it must not be silent either.
struct ConnectionBanner: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(spacing: 0) {
            if state.refusedByMac {
                HStack(spacing: 8) {
                    Image(systemName: "lock.slash")
                    VStack(alignment: .leading, spacing: 1) {
                        Text("This phone is no longer paired with \(state.macDisplayName)")
                            .font(.footnote.weight(.semibold))
                        Text("It was revoked or unpaired on the Mac. Scan the QR in Settings → Phone there to pair again.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Pair again") { state.unpair() }
                        .font(.caption.weight(.semibold))
                        .buttonStyle(.bordered)
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(.thinMaterial)
                .overlay(Divider(), alignment: .bottom)
            } else if state.reachable == false {
                HStack(spacing: 8) {
                    Image(systemName: "wifi.slash")
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Can't reach \(state.macDisplayName)")
                            .font(.footnote.weight(.semibold))
                        Text("Showing the last copy. It will catch up when the Mac is awake.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Retry") { Task { await state.refreshEverything() } }
                        .font(.caption.weight(.semibold))
                        .buttonStyle(.bordered)
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(.thinMaterial)
                .overlay(Divider(), alignment: .bottom)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
            // reachable but running old code: the interface needs a restart
            InterfaceStaleBanner()
        }
    }
}

#if DEBUG
/// Development only: `ORBIT_MARKDOWN_SAMPLE=1` opens a sheet rendering every
/// Markdown form an answer can use, so the renderer can be checked in the
/// simulator without sending anything. `ORBIT_SAMPLE_SID` names the chat file
/// names are looked up in; `ORBIT_SAMPLE_PATH` adds one path to the sample.
struct MarkdownSample: View {
    static var wanted: Bool { ProcessInfo.processInfo.environment["ORBIT_MARKDOWN_SAMPLE"] != nil }
    @EnvironmentObject var state: AppState
    @ObservedObject private var links = FileLinks.shared

    private var text: String {
        let path = ProcessInfo.processInfo.environment["ORBIT_SAMPLE_PATH"] ?? "README.md"
        return """
        # Heading one
        ## Heading two
        Some **bold**, *italic*, ~~struck~~ and `inline code`, a [link](https://example.com) and https://example.org.

        > [!NOTE]
        > Callouts render with a title and a coloured bar.

        > [!WARNING] Careful
        > A warning with its own title.

        > A plain quote.

        - [x] a finished task
        - [ ] an open task
        - a bullet
          - a nested bullet
        1. first
        2. second

        | Column | Another wide column | Third column that is quite long | Fourth |
        |---|---|---|---|
        | a | `b` | c | d |
        | 1 | 2 | 3 | 4 |

        ```python
        print("hello")
        ```

        $$
        E = mc^2
        $$

        ---
        The file is `\(path)`.
        """
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                MarkdownText(text).padding()
            }
            .environment(\.fileLinkSid, ProcessInfo.processInfo.environment["ORBIT_SAMPLE_SID"])
            .navigationTitle("Markdown sample")
            .navigationBarTitleDisplayMode(.inline)
            .sheet(item: $links.presenting) { FilePreviewSheet(target: $0) }
        }
    }
}
#endif
