import SwiftUI

/// What you binned on the Mac — chats and files — with a way back. Purging is
/// the Mac's job on its own schedule; there is deliberately no button for it here.
struct BinView: View {
    @EnvironmentObject var state: AppState
    @State private var items: [TrashItem] = []
    @State private var loading = true
    @State private var note: String?

    var body: some View {
        List {
            if items.isEmpty && !loading {
                ContentUnavailableView("The bin is empty", systemImage: "trash")
            }
            ForEach(items) { t in
                VStack(alignment: .leading, spacing: 3) {
                    Text(t.displayName).lineLimit(1)
                    Text(t.subtitle).font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions(edge: .leading) {
                    Button { Task { await restore(t) } } label: {
                        Label("Restore", systemImage: "arrow.uturn.backward")
                    }.tint(.green)
                }
                .contextMenu {
                    Button { Task { await restore(t) } } label: {
                        Label("Restore", systemImage: "arrow.uturn.backward")
                    }
                }
            }
        }
        .navigationTitle("Bin")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .overlay(alignment: .bottom) {
            if let note {
                Text(note).font(.footnote.weight(.medium))
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.thinMaterial, in: .capsule)
                    .padding(.bottom, 12)
            }
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        items = (try? await server.trash()) ?? []
    }

    private func restore(_ t: TrashItem) async {
        guard let server = state.server else { return }
        do {
            let ok = try await server.restore(name: t.name)
            note = ok ? "Put back where it was" : "The Mac couldn't restore that"
            items.removeAll { $0.name == t.name }
            await state.loadChats()
        } catch { note = error.localizedDescription }
        try? await Task.sleep(nanoseconds: 2_200_000_000)
        note = nil
    }
}
