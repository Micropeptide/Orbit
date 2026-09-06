import SwiftUI

struct RootView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.horizontalSizeClass) private var width
    @AppStorage("theme") private var theme = "system"

    /// Development only: `ORBIT_TAB=files|settings` opens on that tab so the
    /// simulator can be screenshotted without a finger. Compiled out of release.
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
                    FilesView()
                        .tabItem { Label("Files", systemImage: "folder") }
                        .tag("files")
                    SettingsView()
                        .tabItem { Label("Settings", systemImage: "gearshape") }
                        .tag("settings")
                }
            } else {
                PairingView()
            }
        }
        .animation(.default, value: state.isPaired)
        }
        .preferredColorScheme(Appearance.scheme(theme))
        .onAppear { state.tab = Self.initialTab }
    }
}

/// A small banner rather than an alert: losing the Mac mid-scroll should not
/// take over the screen, but it must not be silent either.
struct ConnectionBanner: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if state.reachable == false {
            HStack(spacing: 8) {
                Image(systemName: "wifi.slash")
                VStack(alignment: .leading, spacing: 1) {
                    Text("Can't reach \(state.pairing?.name ?? "your Mac")")
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
    }
}
