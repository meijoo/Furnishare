import SwiftUI

struct WelcomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            BrandMark()
            Text("Design your space")
                .font(.system(size: 40, weight: .bold))
                .foregroundStyle(Color.aeroInk)
            VStack(spacing: 12) {
                Button { nav.screen = .signUp } label: {
                    Text("Get started")
                }
                .buttonStyle(AeroWideButtonStyle())
                Button("Log in") { nav.screen = .login }
                    .buttonStyle(AeroWideButtonStyle(outlined: true))
                Button("Try demo") {
                    Task {
                        await model.signOut()
                        nav.profileName = "Emily"; nav.profileEmail = ""
                        nav.groupName = "Demo apartment"; nav.groupLocation = "Chapel Hill, NC"
                        nav.selectedRoomIDs = []
                        nav.skipToDemo(apartment: model.apartment, actingName: "Emily")
                    }
                }
            }
            .frame(maxWidth: 320)
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
    @State private var error: String?
    @State private var signingIn = false

    var body: some View {
        FlowScreen(maxWidth: 440) {
            VStack(spacing: 20) {
                BrandMark()
                Text("Welcome back")
                    .font(.largeTitle.bold())
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color.black)
                VStack(alignment: .leading, spacing: 14) {
                    FlowField(title: "Email", symbol: "envelope", prompt: "you@example.com", text: $email, keyboard: .emailAddress)
                    FlowField(title: "Password", symbol: "lock", prompt: "Enter your password", text: $password, secure: true)
                    if let error { Text(error).font(.caption).foregroundStyle(.red) }
                    Button("Connection settings") { nav.showSettings = true }
                    Button(signingIn ? "Signing in…" : "Log in") { Task { await continueIn() } }
                        .buttonStyle(AeroWideButtonStyle())
                        .disabled(signingIn || email.trimmingCharacters(in: .whitespaces).isEmpty || password.isEmpty)
                }
                .padding(22)
                .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
                .shadow(color: .black.opacity(0.06), radius: 20, y: 8)
                Button("Back") { nav.screen = .welcome }.foregroundStyle(Color.figmaMuted)
            }
        }
    }

    private func continueIn() async {
        guard let client = model.client else { error = "Configure your backend connection first."; return }
        signingIn = true; error = nil
        defer { signingIn = false }
        do {
            let session = try await client.login(email: email, password: password)
            try model.acceptAccount(session)
            nav.profileName = session.user.name; nav.profileEmail = session.user.email
            nav.profilePhone = session.user.phone; nav.profileUsername = session.user.username
            nav.persistProfile()
            if let group = session.groups.first {
                await model.useGroup(id: group.id, householdID: group.household_id, code: group.group_code)
                nav.groupName = group.name; nav.groupLocation = group.location
                nav.selectedRoomIDs = Set(model.apartment?.furnishableRooms.map(\.id) ?? [])
                nav.finishOnboarding()
            } else { nav.screen = .livingSituation }
            password = ""
        } catch { self.error = error.localizedDescription }
    }
}

struct SignUpView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?
    @State private var saving = false

    var body: some View {
        ZStack {
            FlowScreen(maxWidth: 480) {
                VStack(spacing: 18) {
                    HStack {
                        BrandMark(compact: true)
                        Spacer()
                    }
                    Text("Create your account")
                        .font(.largeTitle.bold())
                        .multilineTextAlignment(.center)
                        .foregroundStyle(Color.black)
                    VStack(alignment: .leading, spacing: 12) {
                        FlowField(title: "Full name", symbol: "person", prompt: "Your name",
                                  text: Binding(get: { nav.profileName }, set: { nav.profileName = $0 }))
                        FlowField(title: "Email", symbol: "envelope", prompt: "you@example.com",
                                  text: Binding(get: { nav.profileEmail }, set: { nav.profileEmail = $0 }),
                                  keyboard: .emailAddress)
                        FlowField(title: "Phone number", symbol: "phone", prompt: "Enter your phone number",
                                  text: Binding(get: { nav.profilePhone }, set: { nav.profilePhone = $0 }),
                                  keyboard: .phonePad)
                        FlowField(title: "Username", symbol: "at", prompt: "Enter your username",
                                  text: Binding(get: { nav.profileUsername }, set: { nav.profileUsername = $0 }))
                        FlowField(title: "Password", symbol: "lock", prompt: "At least 8 characters",
                                  text: Binding(get: { nav.password }, set: { nav.password = $0 }),
                                  secure: true)
                        if let error {
                            Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed)
                        }
                        Button { Task { await submit() } } label: {
                            HStack(spacing: 8) {
                                Text(saving ? "Creating…" : "Create account")
                                Image(systemName: "arrow.right")
                                    .accessibilityHidden(true)
                            }
                        }
                            .buttonStyle(AeroWideButtonStyle())
                            .disabled(saving)
                        Button("Connection settings") { nav.showSettings = true }
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

    private func submit() async {
        let name = nav.profileName.trimmingCharacters(in: .whitespacesAndNewlines)
        let email = nav.profileEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        let phone = nav.profilePhone.trimmingCharacters(in: .whitespacesAndNewlines)
        let username = nav.profileUsername.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty { error = "Add a name so housemates know who you are."; return }
        if !email.contains("@") { error = "Use an email that includes @."; return }
        if phone.isEmpty { error = "Enter your phone number."; return }
        if username.isEmpty { error = "Enter your username."; return }
        if nav.password.count < 8 { error = "Use at least 8 characters for the password field."; return }
        guard let client = model.client else { error = "Configure your backend connection first."; return }
        saving = true; error = nil
        defer { saving = false }
        do {
            let session = try await client.signup(name: name, email: email, phone: phone, username: username, password: nav.password)
            try model.acceptAccount(session)
            nav.profilePhone = session.user.phone
            nav.password = ""
            nav.selectedRoomIDs = []
            nav.groupName = ""; nav.groupLocation = ""
            nav.persistProfile()
            nav.screen = .livingSituation
        } catch { self.error = error.localizedDescription }
    }
}
