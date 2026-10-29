import SwiftUI

/// What the Mac saw while watching the cluster: jobs submitted, started, finished or failed, an error
/// in a running job's output, a disk filling up. A failed job comes with its cause and what usually
/// helps. This is the list the Mac keeps, so reading it costs the cluster nothing.
struct ClusterEventsView: View {
    @ObservedObject var store: ClusterStore
    @State private var onlyTrouble = false

    private var events: [ClusterEvent] {
        let all = store.look?.events ?? []
        return onlyTrouble ? all.filter(\.isTrouble) : all
    }

    var body: some View {
        List {
            Section {
                Toggle("Only what went wrong", isOn: $onlyTrouble)
            }
            Section {
                if events.isEmpty {
                    Text(onlyTrouble ? "Nothing has gone wrong." : "Nothing yet: jobs starting, finishing and failing show up here.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(events) { e in eventRow(e) }
            } footer: {
                Text(store.look?.config.watch == false
                     ? "The Mac is not watching the queue now. Turn it on under Watching and settings."
                     : "The Mac watches the queue by itself and keeps the latest events.")
            }
        }
        .navigationTitle("What happened")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func eventRow(_ e: ClusterEvent) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: icon(e)).foregroundStyle(tint(e)).frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(e.text).font(.callout)
                    Text(store.look?.ago(e.t) ?? "").font(.caption2).foregroundStyle(.secondary)
                }
            }
            if let title = e.causeTitle {
                VStack(alignment: .leading, spacing: 2) {
                    if let x = e.causeExplained { Text(x).font(.footnote) }
                    Text(title + ".").font(.footnote.weight(.semibold))
                    if let fix = e.causeFix { Text(fix).font(.footnote).foregroundStyle(.secondary) }
                }
                .padding(.leading, 26)
            }
            if let d = e.detail {
                DisclosureGroup("Details") {
                    ScrollView(.horizontal) {
                        Text(d).font(.caption2.monospaced()).textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .font(.footnote)
                .padding(.leading, 26)
            }
        }
        .padding(.vertical, 2)
    }

    private func icon(_ e: ClusterEvent) -> String {
        switch e.kind {
        case "failed", "error": return "exclamationmark.octagon.fill"
        case "pending", "disk": return "exclamationmark.triangle.fill"
        case "finished", "ended": return "checkmark.circle"
        case "started": return "play.circle"
        case "cancelled": return "xmark.circle"
        case "measure", "refresh": return "ruler"
        default: return "circle.dotted"
        }
    }

    private func tint(_ e: ClusterEvent) -> Color {
        switch e.kind {
        case "failed", "error": return .red
        case "pending", "disk": return .orange
        case "finished", "ended": return .green
        default: return .secondary
        }
    }
}
