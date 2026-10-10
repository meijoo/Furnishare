import SwiftUI

struct WelcomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            BrandMark()
            Text("Share your space.")
                .font(.system(size: 40, weight: .bold))
                .foregroundStyle(Color.aeroInk)
            VStack(spacing: 12) {
                Button { nav.screen = .signUp } label: {
                    Text("Get started")
                }
                .buttonStyle(AeroWideButtonStyle())
                Button("Log in") { nav.screen = .login }
                    .buttonStyle(AeroWideButtonStyle(outlined: true))
            }
            .frame(maxWidth: 320)
            Button("Skip") { nav.skipToDemo(apartment: model.apartment, actingName: model.actingMemberName) }
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.figmaMuted)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(32)
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
