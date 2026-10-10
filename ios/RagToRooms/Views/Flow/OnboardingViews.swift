import SwiftUI

struct LivingSituationView: View {
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        @Bindable var nav = nav
        FlowScreen(maxWidth: 980) {
            VStack(spacing: 28) {
                header
                VStack(spacing: 8) {
                    SplitHeadline(lead: "How are you ", accent: "living?")
                    Text("Choose an option to get started.")
                        .foregroundStyle(Color.figmaMuted)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 18)], spacing: 18) {
                    cards
                }
            }
        }
    }

    private var header: some View {
        HStack {
            BrandMark(compact: true)
            Spacer()
            FlowStepBar(current: 1, total: 3, captions: ["Group setup", "Floor plan", "Select rooms"])
            Spacer()
            Button("Log out") { nav.screen = .welcome }.font(.subheadline).foregroundStyle(Color.figmaMuted)
        }
    }

    @ViewBuilder private var cards: some View {
        ForEach(LivingMode.allCases, id: \.self) { mode in
            Button {
                nav.livingMode = mode
                switch mode {
                case .createGroup: nav.screen = .groupSetup
                case .joinGroup: nav.screen = .joinGroup
                case .solo: nav.screen = .floorPlan
                }
            } label: {
                VStack(alignment: .leading, spacing: 0) {
                    RoomIllustration(scene: RoomScene(mode: mode))
                        .frame(height: 160)
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
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?

    var body: some View {
        @Bindable var nav = nav
        FlowScreen(maxWidth: 480) {
            VStack(alignment: .leading, spacing: 18) {
                onboardingChrome(step: 1, back: .livingSituation)
                SplitHeadline(lead: "Join a ", accent: "group")
                Text("Ask a housemate for the 6-digit code. In this demo any six digits works and lands you in the shared apartment.")
                    .foregroundStyle(Color.figmaMuted)
                FlowField(title: "Group code", symbol: "number", prompt: "123456",
                          text: $nav.joinCode, keyboard: .numberPad)
                if let error { Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed) }
                Button("Continue") { submit() }.buttonStyle(AeroWideButtonStyle())
                    .disabled(nav.joinCode.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .glassPanel()
        }
    }

    private func submit() {
        let code = nav.joinCode.filter(\.isNumber)
        guard code.count == 6 else { error = "Enter six digits."; return }
        error = nil
        if nav.groupName.isEmpty { nav.groupName = "Shared apartment" }
        nav.screen = .floorPlan
    }
}

struct GroupSetupView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var error: String?

    var body: some View {
        @Bindable var nav = nav
        FlowScreen(maxWidth: 520) {
            VStack(alignment: .leading, spacing: 18) {
                onboardingChrome(step: 1, back: .livingSituation)
                SplitHeadline(lead: "Group ", accent: "setup")
                Text("Name the household so everyone sees the same place. You can change this later.")
                    .foregroundStyle(Color.figmaMuted)
                FlowField(title: "Group name", symbol: "person.3", prompt: model.apartment?.name ?? "Chapel Hill apt",
                          text: $nav.groupName)
                FlowField(title: "Location", symbol: "mappin.and.ellipse", prompt: "Chapel Hill, NC",
                          text: $nav.groupLocation)
                if let error { Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(Color.aeroRed) }
                Button("Continue") { submit() }.buttonStyle(AeroWideButtonStyle())
            }
            .glassPanel()
        }
    }

    private func submit() {
        if nav.groupName.trimmingCharacters(in: .whitespaces).isEmpty {
            nav.groupName = model.apartment?.name ?? "Our apartment"
        }
        if nav.groupLocation.trimmingCharacters(in: .whitespaces).isEmpty {
            nav.groupLocation = "Chapel Hill, NC"
        }
        error = nil
        nav.persistProfile()
        nav.screen = .floorPlan
    }
}

struct FloorPlanUploadView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var showImage = true

    var body: some View {
        FlowScreen(maxWidth: 760) {
            VStack(alignment: .leading, spacing: 18) {
                onboardingChrome(step: 2, back: nav.livingMode == .createGroup ? .groupSetup : nav.livingMode == .joinGroup ? .joinGroup : .livingSituation)
                VStack(spacing: 8) {
                    Text("Upload your floor plan").font(.largeTitle.bold()).foregroundStyle(Color.aeroInk)
                    Text("Upload a photo of your apartment or house floor plan to get started.")
                        .foregroundStyle(Color.figmaMuted)
                }
                .frame(maxWidth: .infinity)
                VStack(spacing: 20) {
                    VStack(spacing: 14) {
                        Image(systemName: "doc.fill")
                            .font(.system(size: 40))
                            .foregroundStyle(Color.aeroSky)
                        Text("Drag and drop your floor plan here").font(.headline).foregroundStyle(Color.aeroInk)
                        Text("or").font(.subheadline).foregroundStyle(Color.figmaMuted)
                        if let apartment = model.apartment {
                            FloorPlanImportControls(apartment: apartment, showImage: $showImage)
                        } else {
                            Label("The apartment plan isn’t loaded yet. You can continue with the demo rooms.", systemImage: "info.circle")
                                .font(.caption).foregroundStyle(Color.figmaMuted)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 36)
                    .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.figmaWash.opacity(0.65)))
                    .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.aeroSky.opacity(0.25), style: StrokeStyle(lineWidth: 1.5, dash: [8, 6])))
                    HStack(spacing: 16) {
                        tip("doc", "Photo format", "PNG, JPEG, or a camera photo")
                        tip("square.split.2x2", "Include all rooms", "Make sure the full layout is visible")
                        tip("internaldrive", "Max file size", "Up to 10 MB")
                    }
                }
                HStack {
                    Button("Back") { nav.screen = nav.livingMode == .createGroup ? .groupSetup : .livingSituation }
                        .buttonStyle(GlassChipStyle())
                    Spacer()
                    Button { goNext() } label: { Label("Continue", systemImage: "arrow.right") }
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
        FlowScreen(maxWidth: 1100) {
            VStack(alignment: .leading, spacing: 18) {
                onboardingChrome(step: 3, back: .floorPlan)
                groupBanner
                Text("Select your rooms").font(.largeTitle.bold()).foregroundStyle(Color.aeroInk)
                Text("Choose every room you can furnish. Bathrooms and halls stay on the plan for reference but aren’t selectable.")
                    .foregroundStyle(Color.figmaMuted)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 16) { planCard; roomCards }
                    VStack(alignment: .leading, spacing: 16) { planCard; roomCards }
                }
                HStack {
                    Button("Back") { nav.screen = .floorPlan }.buttonStyle(GlassChipStyle())
                    Spacer()
                    Button { nav.showShare = true } label: { Label("Share", systemImage: "square.and.arrow.up") }
                        .buttonStyle(GlassChipStyle())
                    Button { finish() } label: { Label("Submit", systemImage: "arrow.right") }
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

    @ViewBuilder private var planCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Floor plan preview").font(.headline)
            Text("Tap a furnishable room to include or leave it out.").font(.caption).foregroundStyle(.secondary)
            if let apartment = model.apartment {
                ApartmentPlanView(apartment: apartment, showImage: true,
                                 selection: Binding(get: { nav.selectedRoomIDs }, set: { nav.selectedRoomIDs = $0 }))
            } else {
                Text("Plan unavailable.").foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .glassPanel()
    }

    private var roomCards: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Choose the rooms you have access to").font(.headline)
            if let apartment = model.apartment {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 10)], spacing: 10) {
                    ForEach(apartment.rooms.filter { $0.kind != .hall && $0.kind != .closet && $0.kind != .other }) { room in
                        roomCard(room, apartment: apartment)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
        .glassPanel()
    }

    private func roomCard(_ room: ApartmentRoom, apartment: Apartment) -> some View {
        let selected = nav.selectedRoomIDs.contains(room.id)
        let enabled = room.isFurnishable
        return Button {
            guard enabled else { return }
            if selected { nav.selectedRoomIDs.remove(room.id) } else { nav.selectedRoomIDs.insert(room.id) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                ZStack(alignment: .topTrailing) {
                    RoomIllustration(scene: room.kind.scene)
                        .frame(height: 80)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    Image(systemName: selected ? "checkmark.square.fill" : "square")
                        .foregroundStyle(enabled ? Color.aeroSky : Color.figmaMuted)
                        .padding(6)
                }
                Text(apartment.shortName(room)).font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk).lineLimit(1)
                Text(enabled ? room.sizeLabel : room.kind.label).font(.caption).foregroundStyle(.secondary)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.white.opacity(enabled ? 0.85 : 0.4)))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(selected ? Color.aeroSky : .clear, lineWidth: 2))
            .opacity(enabled ? 1 : 0.55)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func seedSelection() {
        guard nav.selectedRoomIDs.isEmpty, let rooms = model.apartment?.furnishableRooms else { return }
        nav.selectedRoomIDs = Set(rooms.map(\.id))
    }

    private func finish() {
        nav.persistProfile()
        nav.finishOnboarding()
        nav.showSuccess(.roomsSaved(nav.selectedRoomIDs.count))
    }
}

@ViewBuilder
func onboardingChrome(step: Int, back: AppScreen) -> some View {
    OnboardingChrome(step: step, back: back)
}

private struct OnboardingChrome: View {
    @Environment(AppNavigation.self) private var nav
    let step: Int
    let back: AppScreen

    var body: some View {
        HStack {
            BrandMark(compact: true)
            Spacer()
            FlowStepBar(current: step, total: 3, captions: ["Group setup", "Floor plan", "Select rooms"])
            Spacer()
            Button("Back") { nav.screen = back }.buttonStyle(GlassChipStyle())
        }
    }
}
