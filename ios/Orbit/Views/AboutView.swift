import SwiftUI

/// Who made it, what it is, and what it promises about your data.
struct AboutView: View {
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
    }
}
