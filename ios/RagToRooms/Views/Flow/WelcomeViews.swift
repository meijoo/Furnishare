import SwiftUI

struct WelcomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        FlowScreen(maxWidth: 1080) {
            VStack(alignment: .leading, spacing: 36) {
                HStack {
                    BrandMark()
                    Spacer()
                    Button("Log in") { nav.screen = .login }.buttonStyle(GlassChipStyle())
                    Button("Sign up") { nav.screen = .signUp }.buttonStyle(AeroButtonStyle(compact: true))
                }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .center, spacing: 36) { hero.frame(maxWidth: 460, alignment: .leading); preview }
                    VStack(alignment: .leading, spacing: 28) { hero; preview }
                }
                featureRow
            }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("LIVE TOGETHER, EASIER.")
                .font(.caption.weight(.heavy)).tracking(1.4).foregroundStyle(Color.figmaMuted)
            VStack(alignment: .leading, spacing: 0) {
                Text("Share your space,")
                    .font(.system(size: 38, weight: .bold))
                    .foregroundStyle(Color.aeroInk)
                Text("brighter days.")
                    .font(.system(size: 38, weight: .bold))
                    .foregroundStyle(Color.aeroSky)
            }
            .fixedSize(horizontal: false, vertical: true)
            Text("FurniShare helps you organize your home, share your space, and live together more easily. Roommates pick a room, approve furniture that fits, and settle up in the Nessie sandbox.")
                .font(.body).foregroundStyle(Color.figmaMuted)
            HStack(spacing: 12) {
                Button { nav.screen = .signUp } label: {
                    Label("Get started", systemImage: "arrow.right")
                }
                .buttonStyle(AeroButtonStyle())
                Button { nav.skipToDemo(apartment: model.apartment, actingName: model.actingMemberName) } label: {
                    Text("Learn more")
                }
                .buttonStyle(GlassChipStyle())
            }
            HStack(spacing: 10) {
                MemberAvatars(names: model.apartment?.members.map(\.name) ?? ["Emily", "Maya", "Alex"])
                Text("Trusted by this demo household")
                    .font(.caption).foregroundStyle(Color.figmaMuted)
            }
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                BrandMark(compact: true)
                Spacer()
                Image(systemName: "bell").foregroundStyle(Color.figmaMuted)
                Circle().fill(Color.figmaWash).frame(width: 28, height: 28)
                    .overlay(Text(String(nav.greetingName.prefix(1))).font(.caption2.bold()).foregroundStyle(Color.aeroSky))
            }
            Text("Hi \(nav.greetingName == "there" ? "there" : nav.greetingName)!")
                .font(.title2.bold()).foregroundStyle(Color.aeroInk)
            Text("Here’s what’s happening in your home.").font(.caption).foregroundStyle(Color.figmaMuted)
            HStack(spacing: 10) {
                stat("5", "Rooms", "house")
                stat("3", "Housemates", "person.2")
                stat("8", "Tasks", "checklist")
            }
            Text("Your rooms").font(.subheadline.weight(.semibold))
            HStack(spacing: 10) {
                miniRoom(.living, "Living room")
                miniRoom(.bedroom, "Bedroom")
                miniRoom(.kitchen, "Kitchen")
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
        .shadow(color: .black.opacity(0.08), radius: 24, y: 12)
        .frame(maxWidth: 520)
    }

    private func stat(_ value: String, _ label: String, _ symbol: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: symbol).foregroundStyle(Color.aeroSky)
            Text(value).font(.headline)
            Text(label).font(.caption2).foregroundStyle(Color.figmaMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.figmaWash))
    }

    private func miniRoom(_ scene: RoomScene, _ title: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            RoomIllustration(scene: scene)
                .frame(height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            Text(title).font(.caption2.weight(.semibold)).foregroundStyle(Color.aeroInk)
        }
        .frame(maxWidth: .infinity)
    }

    private var featureRow: some View {
        HStack(alignment: .top, spacing: 16) {
            feature("house.fill", "Organize shared spaces", "Map your home, manage rooms, and keep everyone on the same page.")
            feature("person.2.fill", "Live better together", "Share access, assign the budget, and simplify everyday living.")
            feature("calendar", "All-in-one home hub", "Rooms, people, and payments — all in one place.")
        }
    }

    private func feature(_ symbol: String, _ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: symbol)
                .font(.title3)
                .foregroundStyle(Color.aeroSky)
                .frame(width: 40, height: 40)
                .background(Circle().fill(Color.figmaWash))
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk)
            Text(detail).font(.caption).foregroundStyle(Color.figmaMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct LoginView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var email = ""
    @State private var password = ""

    var body: some View {
        FlowScreen(maxWidth: 440) {
            VStack(spacing: 20) {
                BrandMark()
                SplitHeadline(lead: "Welcome ", accent: "back")
                Text("This demo household is already set up. Sign in with any email to continue as \(model.actingMemberName).")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color.figmaMuted)
                VStack(alignment: .leading, spacing: 14) {
                    FlowField(title: "Email", symbol: "envelope", prompt: "you@example.com", text: $email, keyboard: .emailAddress)
                    FlowField(title: "Password", symbol: "lock", prompt: "Any password works here", text: $password, secure: true)
                    Button("Log in") { continueIn() }
                        .buttonStyle(AeroWideButtonStyle())
                        .disabled(email.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Create an account") { nav.screen = .signUp }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.aeroSky)
                        .frame(maxWidth: .infinity)
                }
                .padding(22)
                .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
                .shadow(color: .black.opacity(0.06), radius: 20, y: 8)
                Button("Back") { nav.screen = .welcome }.foregroundStyle(Color.figmaMuted)
            }
        }
    }

    private func continueIn() {
        if nav.profileName.isEmpty { nav.profileName = model.actingMemberName }
        nav.profileEmail = email
        if UserDefaults.standard.bool(forKey: AppNavigation.completedKey) {
            nav.screen = .spaces
        } else {
            nav.screen = .livingSituation
        }
        nav.persistProfile()
    }
}

struct SignUpView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?

    var body: some View {
        ZStack {
            signupDecor
            FlowScreen(maxWidth: 480) {
                VStack(spacing: 18) {
                    HStack {
                        BrandMark(compact: true)
                        Spacer()
                        Text("Live together, easier.").font(.caption).foregroundStyle(Color.figmaMuted)
                    }
                    SplitHeadline(lead: "Create your ", accent: "account")
                    Text("Get started with FurniShare to organize your space and share your home with ease.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(Color.figmaMuted)
                    VStack(alignment: .leading, spacing: 12) {
                        FlowField(title: "Full name", symbol: "person", prompt: model.actingMemberName,
                                  text: Binding(get: { nav.profileName }, set: { nav.profileName = $0 }))
                        FlowField(title: "Email", symbol: "envelope", prompt: "you@example.com",
                                  text: Binding(get: { nav.profileEmail }, set: { nav.profileEmail = $0 }),
                                  keyboard: .emailAddress)
                        FlowField(title: "Phone number", symbol: "phone", prompt: "(optional)",
                                  text: Binding(get: { nav.profilePhone }, set: { nav.profilePhone = $0 }),
                                  keyboard: .phonePad)
                        FlowField(title: "Username", symbol: "at", prompt: "optional handle",
                                  text: Binding(get: { nav.profileUsername }, set: { nav.profileUsername = $0 }))
                        FlowField(title: "Password", symbol: "lock", prompt: "At least 8 characters",
                                  text: Binding(get: { nav.password }, set: { nav.password = $0 }),
                                  secure: true)
                        if let error {
                            Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed)
                        }
                        Button { submit() } label: { Label("Create account", systemImage: "arrow.right") }
                            .buttonStyle(AeroWideButtonStyle())
                        Button("Already have an account? Log in") { nav.screen = .login }
                            .font(.subheadline)
                            .foregroundStyle(Color.aeroSky)
                            .frame(maxWidth: .infinity)
                    }
                    .padding(22)
                    .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
                    .shadow(color: .black.opacity(0.06), radius: 20, y: 8)
                    Button("Back") { nav.screen = .welcome }.foregroundStyle(Color.figmaMuted)
                }
            }
        }
    }

    private var signupDecor: some View {
        GeometryReader { proxy in
            HStack {
                VStack {
                    Spacer()
                    RoomIllustration(scene: .createGroup)
                        .frame(width: 220, height: 160)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                        .padding(.leading, 24)
                        .padding(.bottom, 40)
                }
                Spacer()
                VStack {
                    Spacer()
                    RoomIllustration(scene: .solo)
                        .frame(width: 180, height: 140)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                        .padding(.trailing, 24)
                        .padding(.bottom, 80)
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .opacity(0.55)
        .allowsHitTesting(false)
    }

    private func submit() {
        let name = nav.profileName.trimmingCharacters(in: .whitespaces)
        let email = nav.profileEmail.trimmingCharacters(in: .whitespaces)
        if name.isEmpty { error = "Add a name so housemates know who you are."; return }
        if !email.contains("@") { error = "Use an email that includes @."; return }
        if nav.password.count < 8 { error = "Use at least 8 characters for the password field."; return }
        error = nil
        nav.persistProfile()
        nav.screen = .livingSituation
    }
}
