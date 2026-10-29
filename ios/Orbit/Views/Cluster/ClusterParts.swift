import SwiftUI

/// What the cluster screens share: the last look at the cluster and the small
/// pieces they all draw (a usage bar, a state pill).
///
/// The Mac keeps its last reading, so opening a screen shows it at once and costs
/// the cluster nothing; only Refresh connects to it.
@MainActor
final class ClusterStore: ObservableObject {
    @Published var look: ClusterLook?
    @Published var loading = false
    @Published var error: String?

    var snapshot: ClusterSnapshot? { look?.snapshot }

    /// The Mac's last reading. If it has none yet, it reads the cluster once.
    func open(_ state: AppState) async {
        guard look == nil, let server = state.server else { return }
        await run { try await server.clusterLook(cached: true) }
    }

    /// Read the cluster again. `slow` also re-reads quotas, disk numbers and limits.
    func refresh(_ state: AppState, slow: Bool = false) async {
        guard let server = state.server else { return }
        await run { try await server.clusterLook(force: true, slow: slow) }
    }

    /// An action that answers with a fresh look.
    func apply(_ state: AppState, _ call: @escaping (OrbitServer) async throws -> ClusterLook) async {
        guard let server = state.server else { return }
        await run { try await call(server) }
    }

    private func run(_ call: () async throws -> ClusterLook) async {
        loading = true
        defer { loading = false }
        do {
            look = try await call()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// How full something is: green, then orange from 85%, red from 90%.
struct ClusterBar: View {
    let pct: Int?

    private var tint: Color {
        let p = pct ?? 0
        return p >= 90 ? .red : p >= 85 ? .orange : .accentColor
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.gray.opacity(0.2))
                Capsule().fill(tint)
                    .frame(width: geo.size.width * CGFloat(min(max(pct ?? 0, 0), 100)) / 100)
            }
        }
        .frame(height: 6)
        .accessibilityHidden(true)
    }
}

/// A job's or a server's state as a coloured word.
struct ClusterStatePill: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(tint.opacity(0.15), in: Capsule())
            .foregroundStyle(tint)
    }

    init(text: String, tint: Color) { self.text = text; self.tint = tint }

    /// For a Slurm job state.
    init(job state: String) {
        text = ClusterFormat.stateWords(state)
        switch state {
        case "RUNNING": tint = .green
        case "PENDING": tint = .orange
        case "COMPLETED": tint = .secondary
        default: tint = .red
        }
    }

    /// For a model server's state.
    init(server state: String, label: String) {
        text = label
        switch state {
        case "ready": tint = .green
        case "queued", "loading", "stopping": tint = .orange
        case "failed", "unreachable": tint = .red
        default: tint = .secondary
        }
    }
}

/// A short stat: a number and what it is.
struct ClusterStat: View {
    let value: String
    let caption: String

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).font(.title3.weight(.semibold).monospacedDigit()).lineLimit(1).minimumScaleFactor(0.7)
            Text(caption).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Text the cluster answered with (a log, a diagnosis), selectable and copyable.
struct ClusterTextBlock: View {
    @EnvironmentObject var state: AppState
    let text: String
    var empty = "(nothing)"

    var body: some View {
        ScrollView(.horizontal) {
            Text(text.isEmpty ? empty : text)
                .font(.caption.monospaced())
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        Button {
            UIPasteboard.general.string = text
            state.toast("Copied")
        } label: { Label("Copy", systemImage: "doc.on.doc") }
        .disabled(text.isEmpty)
    }
}
