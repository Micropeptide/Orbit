import SwiftUI
import AVFoundation
import Network

struct PairingView: View {
    @EnvironmentObject var state: AppState
    @State private var scanning = false
    @State private var manual = false
    @State private var host = ""
    @State private var token = ""
    @State private var found: [DiscoveredMac] = []
    @State private var failed: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 26) {
                    header

                    Button {
                        scanning = true
                    } label: {
                        Label("Scan the QR code", systemImage: "qrcode.viewfinder")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    steps

                    if !found.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("On this network").font(.footnote.smallCaps())
                                .foregroundStyle(.secondary)
                            ForEach(found) { mac in
                                HStack {
                                    Image(systemName: "desktopcomputer")
                                    VStack(alignment: .leading) {
                                        Text(mac.name).font(.callout.weight(.medium))
                                        Text(mac.host).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Text("needs the code").font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                                .padding(10)
                                .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 10))
                            }
                            Text("Found automatically, but pairing still needs the QR — "
                                 + "being on the same Wi-Fi is not permission.")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }

                    Button("Enter the address by hand") { manual = true }
                        .font(.footnote)

                    if let failed {
                        Text(failed).font(.footnote).foregroundStyle(.red)
                            .multilineTextAlignment(.center)
                    }
                }
                .padding(22)
            }
            .navigationTitle("Connect to Orbit")
            .navigationBarTitleDisplayMode(.inline)
            .sheet(isPresented: $scanning) {
                QRScannerView { value in
                    scanning = false
                    guard let url = URL(string: value), state.pair(from: url) else {
                        failed = "That QR code isn't an Orbit pairing code."
                        return
                    }
                    failed = nil
                }
            }
            .sheet(isPresented: $manual) { manualSheet }
            .task { await browse() }
        }
    }

    private var header: some View {
        VStack(spacing: 10) {
            Image("OrbitMark")
                .resizable().scaledToFit()
                .frame(width: 84, height: 84)
                .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
            Text("Your Mac holds everything")
                .font(.title3.weight(.semibold))
            Text("Orbit keeps your chats, notes and papers on your Mac. "
                 + "This app is a window onto them, not a copy.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
    }

    private var steps: some View {
        VStack(alignment: .leading, spacing: 12) {
            step(1, "On your Mac, open Orbit → Settings → Phone.")
            step(2, "Choose Tailscale (works anywhere) or Local network (same Wi-Fi), then restart.")
            step(3, "Scan the QR code it shows.")
        }
        .padding(14)
        .background(.quaternary.opacity(0.35), in: .rect(cornerRadius: 14))
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(n)").font(.caption.weight(.bold))
                .frame(width: 20, height: 20)
                .background(.tint, in: .circle)
                .foregroundStyle(.white)
            Text(text).font(.footnote)
            Spacer(minLength: 0)
        }
    }

    private var manualSheet: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://100.x.y.z:8899", text: $host)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("pairing token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Address and token")
                } footer: {
                    Text("Both are shown under the QR code on your Mac. "
                         + "Scanning is easier and less error-prone.")
                }
            }
            .navigationTitle("By hand")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { manual = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Connect") {
                        state.pairManually(host: host, token: token)
                        manual = false
                    }
                    .disabled(host.isEmpty || token.isEmpty)
                }
            }
        }
    }

    // Bonjour: shows which Macs are running Orbit here. Discovery only —
    // it never shortcuts the token.
    private func browse() async {
        let browser = NWBrowser(for: .bonjour(type: "_orbit._tcp", domain: nil),
                                using: .tcp)
        browser.browseResultsChangedHandler = { results, _ in
            let macs = results.compactMap { r -> DiscoveredMac? in
                if case let .service(name, _, _, _) = r.endpoint {
                    return DiscoveredMac(id: name, name: name, host: "on this network")
                }
                return nil
            }
            Task { @MainActor in found = macs }
        }
        browser.start(queue: .main)
        try? await Task.sleep(nanoseconds: 6_000_000_000)
        browser.cancel()
    }
}

struct DiscoveredMac: Identifiable {
    let id: String
    let name: String
    let host: String
}

/// A thin wrapper over AVCaptureSession. Reads one QR and hands it back.
struct QRScannerView: UIViewControllerRepresentable {
    var onFound: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let c = ScannerController()
        c.onFound = onFound
        return c
    }
    func updateUIViewController(_ vc: ScannerController, context: Context) {}

    final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onFound: ((String) -> Void)?
        private let session = AVCaptureSession()
        private var handled = false

        override func viewDidLoad() {
            super.viewDidLoad()
            view.backgroundColor = .black
            guard let device = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: device),
                  session.canAddInput(input) else { showNoCamera(); return }
            session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else { showNoCamera(); return }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]

            let preview = AVCaptureVideoPreviewLayer(session: session)
            preview.frame = view.bounds
            preview.videoGravity = .resizeAspectFill
            view.layer.addSublayer(preview)

            let hint = UILabel()
            hint.text = "Point at the QR code on your Mac"
            hint.textColor = .white
            hint.font = .preferredFont(forTextStyle: .footnote)
            hint.textAlignment = .center
            hint.translatesAutoresizingMaskIntoConstraints = false
            view.addSubview(hint)
            NSLayoutConstraint.activate([
                hint.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
                hint.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
                hint.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor,
                                             constant: -28),
            ])
            DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
        }

        private func showNoCamera() {
            let l = UILabel()
            l.text = "No camera available.\nUse “Enter the address by hand”."
            l.numberOfLines = 0
            l.textAlignment = .center
            l.textColor = .white
            l.frame = view.bounds
            view.addSubview(l)
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput,
                            didOutput objects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            guard !handled,
                  let obj = objects.first as? AVMetadataMachineReadableCodeObject,
                  let value = obj.stringValue else { return }
            handled = true
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            session.stopRunning()
            onFound?(value)
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            if session.isRunning { session.stopRunning() }
        }
    }
}
