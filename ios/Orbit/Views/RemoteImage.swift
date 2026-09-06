import SwiftUI

/// An image that lives on the Mac.
///
/// `AsyncImage` cannot carry the pairing token, so over the network every
/// thumbnail and every plot would come back 401. This fetches through the same
/// authenticated client as everything else and keeps a small in-memory cache so
/// scrolling a file list does not re-download what it just showed.
struct RemoteImage<Placeholder: View>: View {
    let path: String                       // e.g. /api/thumb/… or /api/ws/…
    var contentMode: ContentMode = .fill
    @ViewBuilder var placeholder: () -> Placeholder

    @EnvironmentObject private var state: AppState
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if failed {
                Image(systemName: "photo.badge.exclamationmark")
                    .foregroundStyle(.secondary)
            } else {
                placeholder()
            }
        }
        .task(id: path) { await load() }
    }

    private func load() async {
        failed = false
        if let hit = ImageCache.shared.image(for: path) { image = hit; return }
        guard let server = state.server else { failed = true; return }
        do {
            let data = try await server.fetchRaw(path)
            guard let ui = UIImage(data: data) else { failed = true; return }
            ImageCache.shared.store(ui, for: path)
            image = ui
        } catch {
            failed = true
        }
    }
}

extension RemoteImage where Placeholder == AnyView {
    init(path: String, contentMode: ContentMode = .fill) {
        self.init(path: path, contentMode: contentMode) {
            AnyView(ProgressView().controlSize(.mini))
        }
    }
}

/// Bounded by count rather than bytes — a plot is small and a phone list is
/// short, and NSCache already evicts under memory pressure.
final class ImageCache {
    static let shared = ImageCache()
    private let cache = NSCache<NSString, UIImage>()
    private init() { cache.countLimit = 120 }

    func image(for key: String) -> UIImage? { cache.object(forKey: key as NSString) }
    func store(_ image: UIImage, for key: String) { cache.setObject(image, forKey: key as NSString) }
}

/// A plot or picture inside a message: tappable, and it opens full-screen
/// because a chart on a phone is unreadable at thumbnail size.
struct MessageImage: View {
    let path: String
    @State private var full = false

    var body: some View {
        RemoteImage(path: path, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .frame(maxHeight: 240)
            .clipShape(.rect(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).strokeBorder(.quaternary))
            .onTapGesture { full = true }
            .fullScreenCover(isPresented: $full) {
                ZoomableImage(path: path) { full = false }
            }
    }
}

/// Pinch and pan, then tap to dismiss. Enough to read an axis label.
struct ZoomableImage: View {
    let path: String
    var close: () -> Void
    @State private var scale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var saved = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            RemoteImage(path: path, contentMode: .fit)
                .scaleEffect(scale)
                .offset(offset)
                .gesture(
                    MagnifyGesture()
                        .onChanged { scale = max(1, min(6, $0.magnification)) }
                        .onEnded { _ in if scale < 1.05 { withAnimation { scale = 1; offset = .zero } } }
                )
                .simultaneousGesture(
                    DragGesture()
                        .onChanged { if scale > 1 { offset = $0.translation } }
                        .onEnded { _ in if scale <= 1 { withAnimation { offset = .zero } } }
                )
                .onTapGesture(count: 2) {
                    withAnimation { scale = scale > 1 ? 1 : 2.5; offset = .zero }
                }
            HStack(spacing: 14) {
                Button {
                    // the image is in the cache by the time it is on screen
                    guard let img = ImageCache.shared.image(for: path) else { return }
                    UIImageWriteToSavedPhotosAlbum(img, nil, nil, nil)
                    Haptics.success()
                    withAnimation { saved = true }
                    Task { try? await Task.sleep(nanoseconds: 1_600_000_000); withAnimation { saved = false } }
                } label: {
                    Image(systemName: saved ? "checkmark.circle.fill" : "square.and.arrow.down.fill")
                        .font(.title)
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .black.opacity(0.4))
                }
                .accessibilityLabel("Save to Photos")
                Button(action: close) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title)
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .black.opacity(0.4))
                }
                .accessibilityLabel("Close")
            }
            .padding(18)
            if saved {
                Text("Saved to Photos").font(.footnote.weight(.medium))
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.thinMaterial, in: .capsule)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                    .padding(.bottom, 40)
            }
        }
        .statusBarHidden()
    }
}
