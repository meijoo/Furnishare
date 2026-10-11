import SwiftUI

struct LivingSituationView: View {
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        @Bindable var nav = nav
        GeometryReader { geometry in
            let wideLandscape = geometry.size.width >= 800 && geometry.size.width > geometry.size.height
            FlowScreen(maxWidth: 1200) {
                VStack(spacing: 28) {
                    header
                    VStack(spacing: 8) {
                        Text("How are you living?")
                            .font(.largeTitle.bold())
                            .foregroundStyle(.black)
                            .multilineTextAlignment(.center)
                    }
                    LazyVGrid(columns: wideLandscape
                              ? Array(repeating: GridItem(.flexible(), spacing: 18), count: 3)
                              : [GridItem(.adaptive(minimum: 260), spacing: 18)], spacing: 18) {
                        cards(illustrationHeight: wideLandscape ? max(240, geometry.size.height - 280) : 160)
                    }
                }
                .frame(minHeight: max(0, geometry.size.height - 40), alignment: .top)
            }
        }
    }

    private var header: some View {
        HStack {
            BrandMark(compact: true)
            Spacer()
            FlowStepBar(current: 1, total: 4)
            Spacer()
            OnboardingBackButton { nav.screen = .welcome }
            Color.clear.frame(width: SettingsGearButton.reservedWidth, height: 1)
        }
    }

    @ViewBuilder private func cards(illustrationHeight: CGFloat) -> some View {
        ForEach(LivingMode.allCases, id: \.self) { mode in
            Button {
                nav.livingMode = mode
                switch mode {
                case .createGroup: nav.screen = .groupSetup
                case .joinGroup: nav.screen = .joinGroup
                case .solo: nav.screen = .groupSetup
                }
            } label: {
                VStack(alignment: .leading, spacing: 0) {
                    RoomIllustration(scene: RoomScene(mode: mode))
                        .frame(height: illustrationHeight)
                    HStack(spacing: 10) {
                        Image(systemName: mode.symbol)
                            .font(.body.weight(.semibold))
                            .foregroundStyle(mode == .joinGroup ? Color.aeroGrass : Color.aeroSky)
                            .frame(width: 32, height: 32)
                            .background(Circle().fill(mode == .joinGroup ? Color.aeroGrass.opacity(0.15) : Color.figmaWash))
                        Text(mode.title).font(.headline).foregroundStyle(Color.aeroInk)
                        Spacer()
                        Image(systemName: "arrow.right")
                            .foregroundStyle(Color.figmaMuted)
                    }
                    .padding(16)
                }
                .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Color.white))
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .shadow(color: .black.opacity(0.06), radius: 16, y: 8)
            }
            .buttonStyle(.plain)
        }
    }
}

struct JoinGroupView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?
    @State private var joining = false

    var body: some View {
        @Bindable var nav = nav
        OnboardingPage(step: 1, back: .livingSituation, maxWidth: 520) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Join a group")
                    .font(.largeTitle.bold())
                    .foregroundStyle(.black)
                Text("Enter the six-digit code sent to you.")
                    .foregroundStyle(Color.figmaMuted)
                FlowField(title: "Group code", symbol: "number", prompt: "123456",
                          text: $nav.joinCode, keyboard: .numberPad)
                if let error { Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed) }
                Button(joining ? "Joining…" : "Continue") { Task { await submit() } }.buttonStyle(AeroWideButtonStyle())
                    .disabled(joining || nav.joinCode.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .glassPanel()
        }
    }

    private func submit() async {
        let code = nav.joinCode.filter(\.isNumber)
        guard code.count == 6 else { error = "Enter six digits."; return }
        if let client = model.client {
            joining = true
            error = nil
            defer { joining = false }
            do {
                let group = try await client.joinGroup(code: code)
                if let gid = group.group_id {
                    await model.useGroup(id: gid, householdID: group.household_id, code: group.group_code)
                } else {
                    model.switchScope(to: group.household_id)
                    model.adoptInviteCode(group.group_code)
                }
                nav.groupName = group.group_name
                nav.joinCode = group.group_code
                nav.finishOnboarding()
                nav.enterSelectedRoom(model: model)
            } catch { self.error = error.localizedDescription }
            return
        }
        error = "Connect to the backend to check your group code."
    }
}

struct GroupSetupView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?
    @State private var saving = false
    @State private var requestID = UUID().uuidString

    var body: some View {
        @Bindable var nav = nav
        OnboardingPage(step: 1, back: .livingSituation, maxWidth: 520) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Group setup")
                    .font(.largeTitle.bold())
                    .foregroundStyle(.black)
                    .multilineTextAlignment(.center)
                FlowField(title: "Group name", symbol: "person.3", prompt: model.apartment?.name ?? "Chapel Hill apt",
                          text: $nav.groupName)
                FlowField(title: "Location", symbol: "mappin.and.ellipse", prompt: "Chapel Hill, NC",
                          text: $nav.groupLocation)
                if let error { Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed) }
                Button(saving ? "Creating group…" : "Continue") { Task { await submit() } }.buttonStyle(AeroWideButtonStyle()).disabled(saving)
            }
            .glassPanel()
        }
    }

    private func submit() async {
        if nav.groupName.trimmingCharacters(in: .whitespaces).isEmpty {
            nav.groupName = model.apartment?.name ?? "Our apartment"
        }
        if nav.groupLocation.trimmingCharacters(in: .whitespaces).isEmpty {
            nav.groupLocation = "Chapel Hill, NC"
        }
        guard model.account != nil, let client = model.client else {
            error = "Sign in before creating a group. Use Try demo on the welcome screen for the demo."; return
        }
        saving = true; error = nil
        defer { saving = false }
        do {
            let group = try await client.createGroup(name: nav.groupName, location: nav.groupLocation, requestID: requestID)
            await model.useGroup(id: group.id, householdID: group.household_id, code: group.group_code)
            nav.selectedRoomIDs = []
            nav.persistProfile()
            nav.screen = .floorPlan
        } catch { self.error = error.localizedDescription }
    }
}

struct FloorPlanUploadView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var showImage = true

    var body: some View {
        OnboardingPage(step: 2, back: nav.livingMode == .createGroup ? .groupSetup : nav.livingMode == .joinGroup ? .joinGroup : .livingSituation, maxWidth: 640) {
            VStack(alignment: .leading, spacing: 22) {
                VStack(spacing: 8) {
                    Text("Upload your floor plan").font(.largeTitle.bold()).foregroundStyle(Color.aeroInk)
                }
                .frame(maxWidth: .infinity)
                if let apartment = model.apartment {
                    FloorPlanImportControls(apartment: apartment, showImage: $showImage, prominent: true)
                } else {
                    Label("The floor plan is still loading. You can continue with the current room.", systemImage: "info.circle")
                        .font(.caption).foregroundStyle(Color.figmaMuted)
                }
                HStack(spacing: 16) {
                    tip("photo", "Photo or Files", "PNG, JPEG, or the Camera")
                    tip("square.split.2x2", "Include all rooms", "The full layout should be visible")
                    tip("internaldrive", "Max file size", "Up to 10 MB")
                }
                HStack {
                    Spacer()
                    Button(action: goNext) { continueLabel("Continue") }
                        .buttonStyle(AeroButtonStyle())
                }
            }
        }
        .task {
            if nav.selectedRoomIDs.isEmpty, let rooms = model.apartment?.furnishableRooms {
                nav.selectedRoomIDs = Set(rooms.map(\.id))
            }
        }
    }

    private func tip(_ symbol: String, _ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: symbol).font(.caption.weight(.semibold)).foregroundStyle(Color.aeroInk)
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func goNext() {
        if nav.selectedRoomIDs.isEmpty, let rooms = model.apartment?.furnishableRooms {
            nav.selectedRoomIDs = Set(rooms.map(\.id))
        }
        nav.screen = .roomSelect
    }
}

struct RoomSelectView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        @Bindable var nav = nav
        OnboardingPage(step: 3, back: .floorPlan, maxWidth: 1280) {
            VStack(alignment: .leading, spacing: 18) {
                groupBanner
                Text("Select your rooms").font(.largeTitle.bold()).foregroundStyle(Color.aeroInk)
                RoomSelectionContent(selection: $nav.selectedRoomIDs)
                HStack {
                    Spacer()
                    Button { nav.persistProfile(); nav.screen = .budgetInspiration } label: { continueLabel("Continue") }
                        .buttonStyle(AeroButtonStyle())
                        .disabled(nav.selectedRoomIDs.isEmpty)
                }
            }
        }
        .task { seedSelection() }
    }

    private var groupBanner: some View {
        HStack(spacing: 16) {
            Label(nav.groupName.isEmpty ? (model.apartment?.name ?? "Apartment") : nav.groupName, systemImage: "person.3.fill")
            Label(nav.groupLocation.isEmpty ? "Location not set" : nav.groupLocation, systemImage: "mappin.and.ellipse")
            Spacer()
        }
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(Color.aeroInk)
        .glassPanel(cornerRadius: 18, padding: 12)
    }

    private func seedSelection() {
        guard nav.selectedRoomIDs.isEmpty, let rooms = model.apartment?.furnishableRooms else { return }
        nav.selectedRoomIDs = Set(rooms.map(\.id))
    }


}

private func continueLabel(_ title: String) -> some View {
    HStack(spacing: 8) {
        Text(title)
        Image(systemName: "arrow.right")
    }
}

@ViewBuilder
func onboardingChrome(step: Int, back: AppScreen) -> some View {
    OnboardingChrome(step: step, back: back)
}

struct OnboardingPage<Content: View>: View {
    let step: Int
    let back: AppScreen
    var maxWidth: CGFloat = 720
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) {
            OnboardingChrome(step: step, back: back)
                .padding(.horizontal, 24)
                .padding(.top, 20)
            FlowScreen(maxWidth: maxWidth) {
                content
            }
        }
    }
}

private struct OnboardingChrome: View {
    @Environment(AppNavigation.self) private var nav
    let step: Int
    let back: AppScreen

    var body: some View {
        HStack {
            BrandMark(compact: true)
            Spacer()
            FlowStepBar(current: step, total: 4)
            Spacer()
            OnboardingBackButton { nav.screen = back }
            Color.clear.frame(width: SettingsGearButton.reservedWidth, height: 1)
        }
    }
}

private struct OnboardingBackButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("Back", systemImage: "chevron.left")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.black)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.white, in: RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }
}
