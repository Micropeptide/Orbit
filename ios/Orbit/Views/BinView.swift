import SwiftUI

/// What you binned on the Mac — chats and files — with a way back. The Mac
/// purges old items on its own schedule; deleting forever here is for the one
/// you are sure about, and always asks first.
struct BinView: View {
    @EnvironmentObject var state: AppState
    @State private var items: [TrashItem] = []
    @State private var loading = true
    @State private var note: String?
    @State private var confirmPurge: TrashItem?
    @State private var confirmEmpty = false

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
                .swipeActions(edge: .trailing) {
                    Button { confirmPurge = t } label: {
                        Label("Delete forever", systemImage: "trash.slash")
                    }.tint(.red)
                }
                .contextMenu {
                    Button { Task { await restore(t) } } label: {
                        Label("Restore", systemImage: "arrow.uturn.backward")
                    }
                    Button(role: .destructive) { confirmPurge = t } label: {
                        Label("Delete forever", systemImage: "trash.slash")
                    }
                }
            }
        }
        .navigationTitle("Bin")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !items.isEmpty {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Empty", role: .destructive) { confirmEmpty = true }
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete \(confirmPurge?.displayName ?? "this") forever?",
                            isPresented: Binding(get: { confirmPurge != nil },
                                                 set: { if !$0 { confirmPurge = nil } }),
                            titleVisibility: .visible) {
            Button("Delete forever", role: .destructive) {
                if let t = confirmPurge { Task { await purge([t]) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It is removed from the Mac for good. This can't be undone.")
        }
        .confirmationDialog("Empty the bin?", isPresented: $confirmEmpty, titleVisibility: .visible) {
            Button("Delete \(items.count) item\(items.count == 1 ? "" : "s") forever", role: .destructive) {
                Task { await purge(items) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every chat and file in the bin is removed from the Mac for good. This can't be undone.")
        }
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
        await clearNote()
    }

    /// One by one, by name: the Mac's purge without a name only takes what has expired.
    private func purge(_ list: [TrashItem]) async {
        confirmPurge = nil
        guard let server = state.server else { return }
        var gone = 0
        do {
            for t in list {
                gone += try await server.purgeTrash(name: t.name)
                items.removeAll { $0.name == t.name }
            }
            note = gone == 1 ? "Deleted forever" : "Deleted \(gone) items forever"
            Haptics.success()
        } catch {
            note = error.localizedDescription
            await load()
        }
        await clearNote()
    }

    private func clearNote() async {
        try? await Task.sleep(nanoseconds: 2_200_000_000)
        note = nil
    }
}
