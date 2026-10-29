import SwiftUI

/// Start a crew: what to build or improve, which models build and review, and when to stop.
struct NewCrewView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let onStarted: () async -> Void
    @State private var title = ""
    @State private var brief = ""
    @State private var folder = ""
    @State private var builder = ""
    @State private var reviewer = ""
    @State private var hours = 0
    @State private var rounds = 0
    @State private var confirm = false
    @State private var busy = false
    @State private var error: String?

    private var ready: [ModelInfo] { state.models.filter(\.isReady) }
    private var canStart: Bool { !brief.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !builder.isEmpty }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $title)
                    TextField("What should it build or improve?", text: $brief, axis: .vertical).lineLimit(4...12)
                } footer: {
                    Text("Write it so a stranger could do it: the goal, what good looks like, what to leave alone.")
                }
                Section {
                    modelPicker("Builder", $builder, optional: false)
                    modelPicker("Reviewer", $reviewer, optional: true)
                } footer: {
                    Text("The builder works in the folder; the reviewer scores each round and says what to do next. "
                         + "A reviewer from another model catches more than the builder would alone.")
                }
                Section {
                    TextField("Folder on the Mac (empty: a new one)", text: $folder)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Section {
                    Stepper(value: $hours, in: 0...168) { LabeledContent("Stop after", value: hours == 0 ? "no time limit" : "\(hours) h") }
                    Stepper(value: $rounds, in: 0...200) { LabeledContent("At most", value: rounds == 0 ? "no round limit" : "\(rounds) rounds") }
                } header: {
                    Text("Limits")
                } footer: {
                    Text("With no limit it goes on until you stop it.")
                }
                if let error { Section { ErrorRow(message: error) } }
            }
            .navigationTitle("New crew")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Start") { confirm = true }.disabled(!canStart || busy)
                }
            }
            .confirmationDialog("Start this crew?", isPresented: $confirm, titleVisibility: .visible) {
                Button("Start") { Task { await start() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The builder starts working on the Mac now and spends tokens on its model each round, until a limit or until you stop it.")
            }
            .task { if state.models.isEmpty { await state.loadModels() } }
        }
    }

    private func modelPicker(_ title: String, _ selection: Binding<String>, optional: Bool) -> some View {
        Picker(title, selection: selection) {
            Text(optional ? "None" : "Choose…").tag("")
            ForEach(ready) { Text($0.display + " · " + $0.group).tag($0.id) }
        }
        .pickerStyle(.navigationLink)
    }

    private func start() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            try await server.crewStart(title: title, brief: brief, folder: folder.trimmingCharacters(in: .whitespaces),
                                       builder: builder, reviewer: reviewer, hours: Double(hours), maxRounds: rounds)
            Haptics.success()
            await onStarted()
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}

/// A crew's limits. Raising one on a finished crew lets it carry on.
struct CrewLimitsSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let run: CrewRun
    let onSaved: () async -> Void
    @State private var hours = 0
    @State private var rounds = 0
    @State private var tokensM = 0
    @State private var error: String?
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Stepper(value: $hours, in: 0...336) { LabeledContent("Stop after", value: hours == 0 ? "no limit" : "\(hours) h") }
                    Stepper(value: $rounds, in: 0...500) { LabeledContent("At most", value: rounds == 0 ? "no limit" : "\(rounds) rounds") }
                    Stepper(value: $tokensM, in: 0...500) { LabeledContent("At most", value: tokensM == 0 ? "no limit" : "\(tokensM) M tokens") }
                } footer: {
                    Text("0 means no limit. A crew that reached a limit starts again when it is raised.")
                }
                if let error { Section { ErrorRow(message: error) } }
            }
            .navigationTitle("Limits")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
            .task {
                guard !loaded else { return }
                hours = Int(run.hours.rounded(.up)); rounds = run.maxRounds; tokensM = run.maxTokens / 1_000_000
                loaded = true
            }
        }
    }

    private func save() async {
        guard let server = state.server else { return }
        do {
            try await server.crewLimits(id: run.id, hours: Double(hours), maxRounds: rounds, maxTokens: tokensM * 1_000_000)
            Haptics.success()
            await onSaved()
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}
