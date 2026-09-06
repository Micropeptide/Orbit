import SwiftUI

struct ModelPickerView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    private var grouped: [(String, [ModelInfo])] {
        Dictionary(grouping: state.models) { $0.provider_label ?? $0.provider }
            .sorted { $0.key < $1.key }
    }

    var body: some View {
        NavigationStack {
            List {
                ForEach(grouped, id: \.0) { provider, models in
                    Section(provider) {
                        ForEach(models) { m in
                            Button {
                                Task { await state.choose(model: m); dismiss() }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(m.display).foregroundStyle(.primary)
                                        if let n = m.note, !n.isEmpty {
                                            Text(n).font(.caption2).foregroundStyle(.secondary)
                                        } else if !m.isReady {
                                            Text("needs an API key on your Mac")
                                                .font(.caption2).foregroundStyle(.orange)
                                        } else if let c = m.context {
                                            Text("\(c / 1000)k context")
                                                .font(.caption2).foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    if m.id == state.effectiveModelID {
                                        Image(systemName: "checkmark").foregroundStyle(.tint)
                                    }
                                }
                            }
                            .disabled(!m.isReady)
                        }
                    }
                }
            }
            .navigationTitle("Model for this chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .overlay {
                if state.models.isEmpty {
                    ContentUnavailableView("No models", systemImage: "cpu",
                        description: Text("Your Mac hasn't reported any models yet."))
                }
            }
        }
    }
}
