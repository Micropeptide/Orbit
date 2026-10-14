import SwiftUI

/// Each device paired with the Mac: its own token, when it was last heard from, what it
/// may do, and revoking it alone. "Chats only" keeps it out of settings, keys and pairing.
struct PairedDevice: Identifiable, Hashable {
    var id: String
    var name: String
    var scope: String
    var via: String
    var created: Double
    var lastSeen: Double

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String else { return nil }
        self.id = id
        name = (d["name"] as? String) ?? "Device"
        scope = (d["scope"] as? String) ?? "full"
        via = (d["via"] as? String) ?? "app"
        created = (d["created"] as? Double) ?? 0
        lastSeen = (d["last_seen"] as? Double) ?? 0
    }
}

extension OrbitServer {
    /// `/api/devices`: list | rename | scope | revoke | retire_legacy.
    func devices(_ op: String = "list", id: String? = nil, name: String? = nil,
                 scope: String? = nil) async throws -> (devices: [PairedDevice], legacy: Bool, you: String?) {
        var body: [String: Any] = ["op": op]
        if let id { body["id"] = id }
        if let name { body["name"] = name }
        if let scope { body["scope"] = scope }
        let r = try await postJSON("/api/devices", body)
        let list = ((r["devices"] as? [[String: Any]]) ?? []).compactMap(PairedDevice.init)
        return (list, (r["legacy"] as? Bool) ?? false, r["you"] as? String)
    }
}

struct DevicesSection: View {
    @EnvironmentObject var state: AppState
    @State private var devices: [PairedDevice] = []
    @State private var legacy = false
    @State private var you: String?
    @State private var failed: String?
    @State private var revoking: PairedDevice?
    @State private var retiring = false

    var body: some View {
        Section {
            if let failed {
                Text(failed).font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(devices) { d in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(d.name + (d.id == you ? " (this phone)" : "")).font(.body)
                        Spacer()
                        Picker("", selection: Binding(get: { d.scope }, set: { v in Task { await change(d, scope: v) } })) {
                            Text("Everything").tag("full")
                            Text("Chats only").tag("chat")
                        }
                        .labelsHidden()
                    }
                    Text("\(d.via == "web" ? "browser" : "app") · last seen "
                         + (d.lastSeen > 0 ? Date(timeIntervalSince1970: d.lastSeen).formatted(.relative(presentation: .named)) : "never"))
                        .font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions {
                    Button("Revoke", role: .destructive) { revoking = d }
                }
            }
            if legacy {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Paired before device tokens" + (you == "legacy" ? " — including this phone" : ""))
                    Button("Retire the old shared token", role: .destructive) { retiring = true }
                        .font(.caption)
                }
            }
            if devices.isEmpty && !legacy && failed == nil {
                Text("No devices paired.").foregroundStyle(.secondary)
            }
        } header: {
            Text("Devices")
        } footer: {
            Text("Each device has a token of its own. Swipe one to revoke it alone. \"Chats only\" lets it chat "
                 + "but not change settings, keys, permissions or pairing.")
        }
        .task { await load() }
        .confirmationDialog("Revoke \(revoking?.name ?? "")?", isPresented: Binding(
            get: { revoking != nil }, set: { if !$0 { revoking = nil } }), titleVisibility: .visible) {
            Button("Revoke", role: .destructive) { if let d = revoking { Task { await revoke(d) } } }
        } message: {
            Text("It stops working at once, and must scan the QR on the Mac to come back.")
        }
        .confirmationDialog("Retire the old shared token?", isPresented: $retiring, titleVisibility: .visible) {
            Button("Retire it", role: .destructive) { Task { await run("retire_legacy") } }
        } message: {
            Text("Anything paired with it" + (you == "legacy" ? ", this phone included," : "")
                 + " must scan the QR on the Mac again.")
        }
    }

    private func load() async { await run("list") }

    private func change(_ d: PairedDevice, scope: String) async { await run("scope", id: d.id, scope: scope) }

    private func revoke(_ d: PairedDevice) async { revoking = nil; await run("revoke", id: d.id) }

    private func run(_ op: String, id: String? = nil, scope: String? = nil) async {
        do {
            let r = try await state.requireServer().devices(op, id: id, scope: scope)
            devices = r.devices; legacy = r.legacy; you = r.you; failed = nil
        } catch {
            failed = error.localizedDescription
        }
    }
}
