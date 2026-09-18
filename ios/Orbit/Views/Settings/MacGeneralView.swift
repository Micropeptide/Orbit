import SwiftUI

/// Settings → General on the Mac: how answers run, the bin, sampling and the
/// system prompt — the web page's General tab, plus the background behaviour
/// switches Orbit keeps in the same settings file. Edits collect until Save.
struct MacGeneralView: View {
    @EnvironmentObject var state: AppState
    @State private var saved: JSONValue?
    @State private var draft: [String: JSONValue] = [:]
    @State private var error: String?
    @State private var note: String?
    @State private var saving = false
    @State private var confirmDiscard = false

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            if saved != nil {
                conversation
                quiet
                background
                sampling
                prompt
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("General")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") { Task { await save() } }
                    .disabled(draft.isEmpty || saving)
            }
            if !draft.isEmpty {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Discard") { draft = [:] }
                }
            }
        }
        .task { if saved == nil { await load() } }
        .settingsNote($note)
    }

    // MARK: sections

    private var conversation: some View {
        Section {
            Toggle("Thinking mode", isOn: bool("thinking", false))
            Picker("Reasoning effort", selection: string("reasoning_effort", "medium")) {
                Text("low").tag("low"); Text("medium").tag("medium"); Text("xhigh").tag("xhigh")
            }
            Toggle("Show thinking", isOn: bool("show_thinking", false))
            IntField(title: "Max tool rounds", value: int("max_tool_rounds", 0))
            IntField(title: "Max minutes per answer", value: int("max_turn_minutes", 0))
            IntField(title: "Say it's still going every", value: int("long_run_notice_min", 30), suffix: "min")
            IntField(title: "Auto-compact at", value: int("autocompact_pct", 80), suffix: "%")
            IntField(title: "Recycle bin keeps", value: int("trash_days", 30), suffix: "days")
        } header: {
            Text("Conversation")
        } footer: {
            Text("Thinking is slower but much more accurate. Tool rounds: research tasks need 40+. "
                 + "0 means no limit for rounds, minutes and the reminder. Auto-compact summarises "
                 + "older turns once the context fills past that share (0 = off).")
        }
    }

    private var quiet: some View {
        let until = value("quiet_until")?.double ?? 0
        let on = until > Date.now.timeIntervalSince1970
        return Section {
            LabeledContent("Quiet mode", value: on
                           ? "on until " + Date(timeIntervalSince1970: until).formatted(date: .omitted, time: .shortened)
                           : "off")
            Button("Quiet for 3 hours") { Task { await setQuiet(Date.now.timeIntervalSince1970 + 3 * 3600) } }
            if on { Button("Turn quiet mode off") { Task { await setQuiet(0) } } }
        } footer: {
            Text("While quiet, the model server runs with the fans left to macOS — no boost while "
                 + "it generates. Takes effect the next time the server starts. Saved straight away.")
        }
    }

    private var background: some View {
        Section {
            Toggle("Keep the Mac awake while answering", isOn: bool("keep_awake", true))
            Toggle("Resume answers after a restart", isOn: bool("resume_after_restart", true))
            Toggle("Save memories automatically", isOn: bool("auto_memory", true))
            Toggle("Local model: one chat at a time", isOn: bool("one_chat_at_a_time", true))
            IntField(title: "Scheduled jobs wait", value: int("schedule_gap_min", 3), suffix: "min")
            IntField(title: "Plan reminders", value: int("plan_nudges", 3))
        } header: {
            Text("In the background")
        } footer: {
            Text("Scheduled jobs wait that long after the last answer finished. Plan reminders: how "
                 + "often Orbit nudges a model that stops while plan steps remain.")
        }
    }

    private var sampling: some View {
        Section {
            samplingField("Temperature", "temperature", "auto (1.0 thinking / 0.7 instruct)")
            samplingField("Top P", "top_p", "auto (0.95 / 0.8)")
            samplingField("Top K", "top_k", "auto (20)")
            samplingField("Presence penalty", "presence_penalty", "auto (0 / 1.5)")
        } header: {
            Text("Sampling")
        } footer: {
            Text("Blank uses the model's own defaults for the current mode.")
        }
    }

    private var prompt: some View {
        Section {
            TextEditor(text: string("system_prompt", ""))
                .font(.footnote.monospaced())
                .frame(minHeight: 180)
                .autocorrectionDisabled()
            Toggle("Include instructions", isOn: bool("use_instructions", true))
            Toggle("Include memory", isOn: bool("use_memory", true))
        } header: {
            Text("System prompt")
        }
    }

    // MARK: bindings over settings + draft

    private func value(_ key: String) -> JSONValue? { draft[key] ?? saved?[key] }

    private func bool(_ key: String, _ def: Bool) -> Binding<Bool> {
        Binding(get: { value(key)?.bool ?? def },
                set: { set(key, .bool($0)) })
    }

    private func int(_ key: String, _ def: Int) -> Binding<Int> {
        Binding(get: { value(key)?.int ?? def },
                set: { set(key, .number(Double(max(0, $0)))) })
    }

    private func string(_ key: String, _ def: String) -> Binding<String> {
        Binding(get: { value(key)?.string ?? def },
                set: { set(key, .string($0)) })
    }

    private func set(_ key: String, _ v: JSONValue) {
        if saved?[key] == v { draft[key] = nil } else { draft[key] = v }
    }

    private func samplingField(_ title: String, _ key: String, _ hint: String) -> some View {
        let binding = Binding<String>(
            get: {
                guard let v = value("sampling")?[key], let d = v.double else { return "" }
                return d == d.rounded() && key == "top_k" ? String(Int(d)) : String(d)
            },
            set: { text in
                var obj = value("sampling")?.object ?? [:]
                let t = text.trimmingCharacters(in: .whitespaces)
                obj[key] = t.isEmpty ? .null : (Double(t).map { .number($0) } ?? obj[key] ?? .null)
                set("sampling", .object(obj))
            })
        return HStack {
            Text(title)
            Spacer()
            TextField(hint, text: binding)
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .font(.callout)
        }
    }

    // MARK: I/O

    private func load() async {
        do { saved = try await state.requireServer().settings(); error = nil }
        catch { self.error = error.localizedDescription }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let r = try await state.requireServer().saveSettings(draft.mapValues(\.foundation))
            saved = r.settings
            draft = [:]
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func setQuiet(_ until: Double) async {
        do {
            let r = try await state.requireServer().saveSettings(["quiet_until": until])
            saved = r.settings
            draft["quiet_until"] = nil
            note = until > 0 ? "quiet for 3 hours" : "quiet mode off"
        } catch { note = error.localizedDescription }
    }
}
