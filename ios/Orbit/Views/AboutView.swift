import SwiftUI

/// Who made it, what it is, and what it promises about your data.
struct AboutView: View {
    @EnvironmentObject var state: AppState
    /// Orbit on the paired Mac: its version, model, counts, tools and folders.
    @State private var mac: AboutMac?
    @State private var showTools = false

    private var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
    }

    var body: some View {
        List {
            Section {
                VStack(spacing: 10) {
                    Image("OrbitMark").resizable().scaledToFit()
                        .frame(width: 96, height: 96)
                        .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
                    Text("Orbit").font(.title.weight(.semibold))
                    Text("Version \(version)").font(.footnote).foregroundStyle(.secondary)
                    Text("A research assistant that runs on your own Mac — a local model, "
                         + "your papers, your notes, your tools. This app is a window onto it.")
                        .font(.footnote).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .listRowBackground(Color.clear)
            }

            if let mac { onMac(mac) }

            Section("Author") {
                LabeledContent("Made by", value: "Micropeptide")
                Link(destination: URL(string: "https://github.com/Micropeptide/Orbit")!) {
                    LabeledContent("Source", value: "github.com/Micropeptide/Orbit")
                }
                Link(destination: URL(string: "https://github.com/Micropeptide")!) {
                    LabeledContent("More", value: "github.com/Micropeptide")
                }
            }

            Section("Licence") {
                Text("MIT — free to use, change and share. No warranty.")
                    .font(.footnote)
            }

            Section("Your data") {
                Text("Every chat lives on your Mac. This app keeps a read-only copy for "
                     + "reading offline and the pairing token in the Keychain; nothing goes "
                     + "to a cloud unless you configure a hosted model yourself. Deleting "
                     + "moves things to the bin on the Mac, never past it.")
                    .font(.footnote)
            }

            Section("Built with") {
                Text("MTPLX and Apple Silicon MLX for the local model; SwiftUI; optional "
                     + "Claude, OpenAI-compatible and command-line model backends.")
                    .font(.footnote)
            }
        }
        .navigationTitle("About")
        .navigationBarTitleDisplayMode(.inline)
        .task { if mac == nil, let s = state.server { mac = try? await s.aboutMac() } }
    }

    @ViewBuilder private func onMac(_ a: AboutMac) -> some View {
        let c = a.counts ?? [:]
        Section {
            if let v = a.version { LabeledContent("Orbit", value: "v\(v)") }
            if let m = a.model { LabeledContent("Local model", value: m) }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 10) {
                ForEach([("sessions", "chats"), ("projects", "projects"), ("tools", "tools"),
                         ("knowledge", "documents"), ("memories", "memories"), ("skills", "skills"),
                         ("agents", "agents"), ("files", "files")], id: \.0) { key, label in
                    let n = key == "tools" ? (a.tools?.count ?? 0) : (c[key] ?? 0)
                    VStack(spacing: 1) {
                        Text(key == "files" && n >= 5000 ? "5000+" : "\(n)")
                            .font(.headline.monospacedDigit())
                        Text(label).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.vertical, 4)
            if let tools = a.tools, !tools.isEmpty {
                DisclosureGroup("Tools", isExpanded: $showTools) {
                    Text(tools.joined(separator: " · "))
                        .font(.caption.monospaced()).foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("On your Mac")
        }

        if let root = a.root {
            Section {
                Text("""
                \(ClaudeMemoryView.tilde(root))/
                  config/     settings, agents, projects,
                              schedule, secrets, MCP
                  memory/     durable facts
                  skills/     procedures
                  knowledge/  your documents
                  sessions/   chats
                  workspace/  files it creates
                  trash/      recycle bin
                  logs/       server, safety, ledger
                """)
                .font(.caption.monospaced())
                .textSelection(.enabled)
            } header: {
                Text("Where things live")
            }
        }
    }
}
