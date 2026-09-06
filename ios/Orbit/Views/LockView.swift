import SwiftUI
import LocalAuthentication

/// Optional: ask for Face ID (or the passcode) whenever Orbit comes to the front.
/// If the phone cannot authenticate at all it does not lock — a missing sensor
/// must never lock you out of your own chats.
struct LockGate<Content: View>: View {
    @AppStorage("faceID") private var wanted = false
    @Environment(\.scenePhase) private var phase
    @State private var unlocked = true
    @State private var failed = false
    @ViewBuilder var content: () -> Content

    private var locked: Bool { wanted && !unlocked }

    var body: some View {
        ZStack {
            content()
                .blur(radius: locked ? 18 : 0)
                .allowsHitTesting(!locked)
            if locked {
                VStack(spacing: 14) {
                    Image("OrbitMark").resizable().scaledToFit().frame(width: 72, height: 72)
                    Text("Orbit is locked").font(.headline)
                    Button("Unlock") { authenticate() }
                        .buttonStyle(.borderedProminent)
                    if failed {
                        Text("Couldn't verify. Try again.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.regularMaterial)
            }
        }
        .onChange(of: phase) { _, p in
            if p == .background, wanted { unlocked = false }
            if p == .active, wanted, !unlocked { authenticate() }
        }
        .onAppear { if wanted { unlocked = false; authenticate() } }
    }

    private func authenticate() {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else {
            unlocked = true                     // nothing to check against: never lock out
            return
        }
        ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock Orbit") { ok, _ in
            Task { @MainActor in unlocked = ok; failed = !ok }
        }
    }
}
