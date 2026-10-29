import SwiftUI

/// The first time Orbit opens: what it is, how to connect it to your Mac, what you can do
/// from the phone, and the way into the full guide. Shown once; Settings → User guide has
/// everything it points to.
struct WelcomeView: View {
    var onDone: () -> Void
    @State private var page = 0
    @State private var showGuide = false

    private let pages = 4

    var body: some View {
        ZStack(alignment: .top) {
            OrbitTheme.paper.ignoresSafeArea()
            // a wash of the icon's colour behind the top of every page
            OrbitTheme.gradient.opacity(0.16)
                .frame(height: 360)
                .mask(LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom))
                .ignoresSafeArea()

            VStack(spacing: 0) {
                HStack {
                    Spacer()
                    if page < pages - 1 {
                        Button("Skip") { onDone() }
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                .frame(height: 30)
                .padding(.horizontal, 22).padding(.top, 8)

                TabView(selection: $page) {
                    hello.tag(0)
                    connect.tag(1)
                    whatYouCanDo.tag(2)
                    guide.tag(3)
                }
                .tabViewStyle(.page(indexDisplayMode: .never))

                VStack(spacing: 16) {
                    HStack(spacing: 7) {
                        ForEach(0..<pages, id: \.self) { i in
                            Capsule().fill(i == page ? Color.accentColor : Color.secondary.opacity(0.3))
                                .frame(width: i == page ? 20 : 7, height: 7)
                        }
                    }
                    .animation(.spring(duration: 0.3), value: page)
                    .accessibilityHidden(true)
                    Button(page < pages - 1 ? "Continue" : "Get started") {
                        if page < pages - 1 { withAnimation { page += 1 } } else { onDone() }
                    }
                    .buttonStyle(.orbitPrimary)
                }
                .padding(.horizontal, 26).padding(.bottom, 18)
            }
        }
        .sheet(isPresented: $showGuide) {
            NavigationStack {
                GuideView()
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showGuide = false } } }
            }
        }
    }

    // ---- the pages

    private var hello: some View {
        page(art: AnyView(Image("OrbitMark").resizable().scaledToFit().frame(width: 120, height: 120)
                            .shadow(color: Color(light: 0x2C5BF0, dark: 0x000000).opacity(0.3), radius: 22, y: 10)
                            .accessibilityHidden(true)),
             title: "Welcome to Orbit",
             text: "Your research assistant runs on your Mac — your chats, files and models stay there. "
                 + "This app is a window onto it: the same conversations, live, wherever you are.")
    }

    private var connect: some View {
        VStack(alignment: .leading, spacing: 18) {
            symbol("laptopcomputer.and.iphone")
            Text("Connect it to your Mac").font(.title.weight(.bold))
            Text("Once, and then it just works — at home over Wi-Fi, or anywhere through Tailscale.")
                .font(.body).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 14) {
                step(1, "On your Mac, open Orbit and go to Settings → Phone.")
                step(2, "Choose Internet (works anywhere, no VPN), Tailscale or Local network (same Wi-Fi).")
                step(3, "Scan the QR code it shows with this app.")
            }
            .padding(16)
            .background(OrbitTheme.surface, in: .rect(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(OrbitTheme.line.opacity(0.7), lineWidth: 0.75))
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 26).padding(.top, 24)
    }

    private var whatYouCanDo: some View {
        VStack(alignment: .leading, spacing: 18) {
            symbol("sparkles")
            Text("What you can do here").font(.title.weight(.bold))
            VStack(alignment: .leading, spacing: 16) {
                feature("bubble.left.and.bubble.right", "Ask with any model",
                        "Orbit's own agent, Claude Code or Codex — local, hosted or your subscription.")
                feature("hand.raised", "Approve from the Lock Screen",
                        "When a step needs your yes, answer on the notification itself.")
                feature("scope", "Keep going until done",
                        "Give a chat a goal and it carries on, answer after answer, until the work is finished.")
                feature("folder", "Files, schedules, your Library",
                        "Everything Orbit made, what runs on its own, and your papers and prompts.")
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 26).padding(.top, 24)
    }

    private var guide: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            symbol("book")
            Text("The full guide is always here").font(.title.weight(.bold)).multilineTextAlignment(.center)
            Text("Every feature, step by step — chats, goals, files, the Mac app, keyboard shortcuts and what "
                 + "to do when something goes wrong. Find it again in Settings → User guide.")
                .font(.body).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button {
                showGuide = true
            } label: {
                Label("Read the user guide", systemImage: "book.pages")
                    .font(.body.weight(.semibold))
                    .padding(.horizontal, 20).padding(.vertical, 12)
                    .background(OrbitTheme.surface, in: .capsule)
                    .overlay(Capsule().strokeBorder(OrbitTheme.line, lineWidth: 0.75))
            }
            .buttonStyle(.plain).foregroundStyle(.tint)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 30)
    }

    // ---- pieces

    private func page(art: AnyView, title: String, text: String) -> some View {
        VStack(spacing: 22) {
            Spacer(minLength: 0)
            art.padding(.bottom, 10)
            Text(title).font(.largeTitle.weight(.bold)).multilineTextAlignment(.center)
            Text(text).font(.body).foregroundStyle(.secondary).multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 30)
    }

    private func symbol(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 26, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 56, height: 56)
            .background(OrbitTheme.gradient, in: .rect(cornerRadius: 15))
            .accessibilityHidden(true)
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text("\(n)").font(.footnote.weight(.bold)).foregroundStyle(.white)
                .frame(width: 24, height: 24)
                .background(OrbitTheme.gradient, in: .circle)
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 5 }
            Text(text).font(.callout).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func feature(_ icon: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon).font(.title3).foregroundStyle(.tint).frame(width: 30)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
