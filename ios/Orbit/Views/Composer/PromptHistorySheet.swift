import SwiftUI

/// "Earlier messages": what you sent before, newest first, to send again or change.
/// The web's Ctrl+R; kept on this phone.
struct PromptHistorySheet: View {
    var pick: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var filter = ""
    @State private var history = PromptHistory.load()

    private var shown: [String] {
        let f = filter.lowercased()
        return Array(history.reversed().filter { f.isEmpty || $0.lowercased().contains(f) }.prefix(40))
    }

    var body: some View {
        NavigationStack {
            List {
                if history.isEmpty {
                    Text("No earlier messages yet").foregroundStyle(.secondary)
                } else if shown.isEmpty {
                    Text("None match").foregroundStyle(.secondary)
                }
                ForEach(shown, id: \.self) { t in
                    Button {
                        pick(t)
                        dismiss()
                    } label: {
                        Text(t.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(160))
                            .font(.callout).lineLimit(3).foregroundStyle(.primary)
                    }
                }
            }
            .searchable(text: $filter, placement: .navigationBarDrawer(displayMode: .always), prompt: "Filter")
            .onSubmit(of: .search) {
                if let first = shown.first { pick(first); dismiss() }
            }
            .navigationTitle("Earlier messages")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}
