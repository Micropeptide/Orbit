import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// The bar at the bottom of a conversation. Attachments come from three places
/// — the photo library, the camera, or the Files app — and each opens the real
/// system picker, so it looks and behaves like every other app on the phone.
struct Composer: View {
    @EnvironmentObject var state: AppState
    @Binding var draft: String
    var typing: FocusState<Bool>.Binding
    var modelName: String
    var onPickModel: () -> Void
    /// Returns true when it handled a `/command`, so the text is not sent as a message.
    var onCommand: ((String) -> Bool)? = nil

    static let commands: [(String, String)] = [
        ("/new", "start a new chat"), ("/model", "change the model"),
        ("/compact", "compact the history"), ("/find", "find in this chat"),
    ]
    private var commandHints: [(String, String)] {
        guard draft.hasPrefix("/"), !draft.contains(" ") else { return [] }
        return Self.commands.filter { $0.0.hasPrefix(draft.lowercased()) }
    }

    @State private var showAttachMenu = false
    @State private var showLibrary = false
    @State private var showCamera = false
    @State private var showFiles = false
    @State private var picked: [PhotosPickerItem] = []

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !state.attachments.isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            // Which model answers is the single fact you most want in view, so it
            // lives here rather than in a toolbar that folds it away when cramped.
            Button(action: onPickModel) {
                HStack(spacing: 5) {
                    Image(systemName: "cpu").font(.caption2)
                    Text(state.streaming && !state.liveModel.isEmpty ? state.liveModel : modelName)
                        .font(.caption.weight(.medium)).lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down").font(.caption2)
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(.quaternary.opacity(0.35), in: .capsule)
            }
            .buttonStyle(.plain)
            .padding(.top, 6)
            .accessibilityLabel("Model: \(modelName). Tap to change.")
            if !state.attachments.isEmpty || state.uploading { attachmentStrip }
            if !commandHints.isEmpty { commandStrip }
            HStack(alignment: .bottom, spacing: 8) {
                Button {
                    Haptics.tap()
                    showAttachMenu = true
                } label: {
                    Image(systemName: "plus")
                        .font(.body.weight(.semibold))
                        .frame(width: 36, height: 36)
                        .background(.quaternary.opacity(0.5), in: .circle)
                }
                .disabled(state.streaming)
                .accessibilityLabel("Attach")

                TextField("Message", text: $draft, axis: .vertical)
                    .lineLimit(1...6)
                    .focused(typing)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.background, in: .rect(cornerRadius: 20))
                    .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(.quaternary))

                if state.streaming {
                    Button {
                        Task { await state.stopGenerating() }
                    } label: {
                        Image(systemName: "stop.fill")
                            .font(.footnote.weight(.bold))
                            .frame(width: 36, height: 36)
                            .background(.red, in: .circle)
                            .foregroundStyle(.white)
                    }
                    .accessibilityLabel("Stop")
                } else {
                    Button {
                        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                        draft = ""
                        Haptics.tap()
                        if text.hasPrefix("/"), onCommand?(text) == true { return }
                        Task { await state.send(text) }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.body.weight(.bold))
                            .frame(width: 36, height: 36)
                            .background(canSend ? Color.accentColor : Color.secondary.opacity(0.35),
                                        in: .circle)
                            .foregroundStyle(.white)
                    }
                    .disabled(!canSend)
                    .keyboardShortcut(.return, modifiers: .command)
                    .accessibilityLabel("Send")
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .padding(.bottom, 8)
        }
        .background(.bar)
        // Three real pickers. Each is a system sheet, presented from a bool it
        // owns, so nothing is hidden under anything else.
        .confirmationDialog("Attach", isPresented: $showAttachMenu, titleVisibility: .hidden) {
            Button("Photo Library") { showLibrary = true }
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button("Take Photo") { showCamera = true }
            }
            Button("Choose File") { showFiles = true }
            Button("Cancel", role: .cancel) {}
        }
        .photosPicker(isPresented: $showLibrary, selection: $picked,
                      maxSelectionCount: 4, matching: .images)
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            let batch = items
            picked = []
            Task { for item in batch { await state.attach(photo: item) } }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                showCamera = false
                guard let image else { return }
                Task { await state.attach(image: image) }
            }
            .ignoresSafeArea()
        }
        .fileImporter(isPresented: $showFiles, allowedContentTypes: [.item],
                      allowsMultipleSelection: true) { result in
            if case .success(let urls) = result {
                Task { for u in urls { await state.attach(fileAt: u) } }
            }
        }
    }

    /// Type "/" and the commands offer themselves.
    private var commandStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(commandHints, id: \.0) { cmd, what in
                    Button {
                        draft = ""
                        Haptics.tap()
                        _ = onCommand?(cmd)
                    } label: {
                        HStack(spacing: 5) {
                            Text(cmd).font(.caption.monospaced().weight(.semibold))
                            Text(what).font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.quaternary.opacity(0.5), in: .capsule)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12).padding(.top, 8)
        }
        .frame(height: 40)
    }

    /// What is going up with the next message, and how to change your mind.
    private var attachmentStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(state.attachments) { a in
                    HStack(spacing: 6) {
                        if let thumb = a.thumbnail {
                            Image(uiImage: thumb).resizable().scaledToFill()
                                .frame(width: 28, height: 28).clipShape(.rect(cornerRadius: 6))
                        } else {
                            Image(systemName: a.kind == "image" ? "photo" : "doc").font(.caption)
                        }
                        Text(a.name).font(.caption).lineLimit(1).frame(maxWidth: 140)
                        Button {
                            state.attachments.removeAll { $0.id == a.id }
                        } label: { Image(systemName: "xmark.circle.fill").font(.caption) }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(.leading, 6).padding(.trailing, 9).padding(.vertical, 5)
                    .background(.quaternary.opacity(0.5), in: .capsule)
                }
                if state.uploading {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("uploading").font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 9).padding(.vertical, 6)
                }
            }
            .padding(.horizontal, 12).padding(.top, 8)
        }
        .frame(height: 46)
    }
}

/// The system camera, wrapped. Returns nil if the person backs out.
struct CameraPicker: UIViewControllerRepresentable {
    var onDone: (UIImage?) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let c = UIImagePickerController()
        c.sourceType = .camera
        c.delegate = context.coordinator
        return c
    }
    func updateUIViewController(_ vc: UIImagePickerController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(onDone: onDone) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onDone: (UIImage?) -> Void
        init(onDone: @escaping (UIImage?) -> Void) { self.onDone = onDone }
        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onDone(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onDone(nil) }
    }
}
