import SwiftUI
import UIKit

/// Per-phone preferences. None of this is about your data — that stays on the Mac.

enum Haptics {
    static var enabled: Bool { UserDefaults.standard.object(forKey: "haptics") as? Bool ?? true }
    static func tap()     { guard enabled else { return }; UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func press()   { guard enabled else { return }; UIImpactFeedbackGenerator(style: .medium).impactOccurred() }
    static func success() { guard enabled else { return }; UINotificationFeedbackGenerator().notificationOccurred(.success) }
}

/// What you were typing in each chat, kept across leaving and coming back.
enum Drafts {
    private static func key(_ sid: String) -> String { "draft." + sid }
    static func load(_ sid: String) -> String { UserDefaults.standard.string(forKey: key(sid)) ?? "" }
    static func save(_ sid: String, _ text: String) {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            UserDefaults.standard.removeObject(forKey: key(sid))
        } else {
            UserDefaults.standard.set(text, forKey: key(sid))
        }
    }
}

enum Appearance {
    static func scheme(_ raw: String) -> ColorScheme? {
        switch raw {
        case "light": return .light
        case "dark":  return .dark
        default:      return nil
        }
    }
    static func typeSize(_ raw: String) -> DynamicTypeSize? {
        switch raw {
        case "large":  return .xLarge
        case "xlarge": return .xxxLarge
        default:       return nil
        }
    }
}

/// Applies a chosen text size, or leaves the system's alone.
struct AnswerTextSize: ViewModifier {
    @AppStorage("textSize") private var raw = "default"
    func body(content: Content) -> some View {
        if let s = Appearance.typeSize(raw) { content.dynamicTypeSize(s) } else { content }
    }
}

/// A rendered image on its way to the share sheet.
struct ShareImage: Identifiable {
    let id = UUID()
    let image: UIImage
}
