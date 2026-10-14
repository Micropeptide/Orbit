import SwiftUI

/// Orbit's look on the phone, the same as on the Mac: cool porcelain paper with ink that has
/// a little blue in it, the icon's cobalt for what you act on (the asset catalog's
/// AccentColor) and its violet for thinking. One moving thing -- a planet going round its
/// ring wherever a chat is at work -- and everything else quiet.
enum OrbitTheme {
    /// The page behind a conversation and the chat list.
    static let paper = Color(light: 0xF7F8FB, dark: 0x14171E)
    /// Cards, the composer, the user's own messages' ground.
    static let surface = Color(light: 0xFFFFFF, dark: 0x1C2029)
    /// Hairlines round cards and the composer.
    static let line = Color(light: 0xD3D9E3, dark: 0x343A47)
    static let think = Color(light: 0x7C5CFA, dark: 0xA58BFF)
    static let tool = Color(light: 0x9A6510, dark: 0xE0B25C)
    static let waiting = Color(light: 0xC27C0E, dark: 0xE6A845)
}

extension Color {
    /// A colour that follows light and dark mode, from two 0xRRGGBB values.
    init(light: UInt32, dark: UInt32) {
        self = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

/// A chat at work: a ring with its planet going round. Still, as a ring and a dot, when
/// Reduce Motion is on.
struct OrbitSpinner: View {
    var size: CGFloat = 14
    var tint: Color = .accentColor
    @Environment(\.accessibilityReduceMotion) private var still
    @State private var turning = false

    var body: some View {
        ZStack {
            Circle().stroke(tint.opacity(0.28), lineWidth: max(1.2, size / 10))
            Circle().fill(tint)
                .frame(width: size * 0.36, height: size * 0.36)
                .offset(y: -size / 2)
        }
        .frame(width: size, height: size)
        .rotationEffect(.degrees(turning ? 360 : 0))
        .onAppear {
            guard !still else { return }
            withAnimation(.linear(duration: 1.15).repeatForever(autoreverses: false)) { turning = true }
        }
        .accessibilityLabel("working")
    }
}

/// Orbit's mark, drawn: a larger, slower orbit for empty states and the welcome.
struct OrbitMark: View {
    var size: CGFloat = 44
    @Environment(\.accessibilityReduceMotion) private var still
    @State private var turning = false

    var body: some View {
        ZStack {
            Circle().stroke(Color.accentColor.opacity(0.25), lineWidth: 2)
            Circle()
                .fill(RadialGradient(colors: [.white, Color.accentColor.opacity(0.75), .accentColor],
                                     center: UnitPoint(x: 0.35, y: 0.3), startRadius: 0, endRadius: size * 0.16))
                .frame(width: size * 0.27, height: size * 0.27)
                .overlay(Circle().stroke(OrbitTheme.paper, lineWidth: 3))
                .shadow(color: Color.accentColor.opacity(0.4), radius: 4, y: 2)
                .offset(y: -size / 2)
                .rotationEffect(.degrees(turning ? 360 : 0))
        }
        .frame(width: size, height: size)
        .onAppear {
            guard !still else { return }
            withAnimation(.linear(duration: 16).repeatForever(autoreverses: false)) { turning = true }
        }
        .accessibilityHidden(true)
    }
}

extension View {
    /// The floating surface the composer and cards sit on: a quiet card with a hairline and a
    /// soft shadow. Not Liquid Glass: glass is drawn on a layer of its own that animates
    /// separately, and while a chat opened (the tab bar hiding) the box slid away from the
    /// lines laid out under it, which were left drawn across it.
    func orbitSurface(cornerRadius: CGFloat = 22) -> some View {
        self.background(OrbitTheme.surface, in: .rect(cornerRadius: cornerRadius))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius).strokeBorder(OrbitTheme.line, lineWidth: 0.75))
            .shadow(color: .black.opacity(0.07), radius: 10, y: 3)
    }
}

extension OrbitTheme {
    /// The icon's own blue-to-violet, for the one action on a screen that matters most.
    static let gradient = LinearGradient(
        colors: [Color(light: 0x5287FF, dark: 0x6E94FF), Color(light: 0x2C5BF0, dark: 0x4D74F5),
                 Color(light: 0x5A4CF0, dark: 0x7462F2)],
        startPoint: .topLeading, endPoint: .bottomTrailing)
}

/// The main action on a screen: a capsule in the icon's gradient, white text, a little give
/// when pressed.
struct OrbitPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(OrbitTheme.gradient, in: .capsule)
            .shadow(color: Color(light: 0x2C5BF0, dark: 0x000000).opacity(0.25), radius: 10, y: 4)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.92 : 1)
            .animation(.spring(duration: 0.2), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == OrbitPrimaryButtonStyle {
    static var orbitPrimary: OrbitPrimaryButtonStyle { OrbitPrimaryButtonStyle() }
}
