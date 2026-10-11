import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var joinInvitation: RoomInvitation?

    var body: some View {
        @Bindable var nav = nav
        ZStack {
            AquaticBackground()
            screen
            if let success = nav.success {
                SuccessOverlay(kind: success)
            }
        }
        .overlay(alignment: .topTrailing) {
            SettingsGearButton()
                .padding(.top, 14)
                .padding(.trailing, 20)
        }
        .sheet(isPresented: $nav.showSettings) { SettingsSheet().environment(model).environment(self.nav) }
        .sheet(isPresented: $nav.showRoomSetup) { RoomSetupSheet(room: model.state.room).environment(model) }
        .sheet(isPresented: $nav.showCatalog) { CatalogSheet().environment(model).environment(self.nav) }
        .sheet(isPresented: $nav.showAddItem) { AddItemSheet().environment(model).environment(self.nav) }
        .sheet(isPresented: $nav.showSendMoney) { SendMoneySheet().environment(model).environment(self.nav) }
        .sheet(isPresented: $nav.showShare, onDismiss: {
            if nav.finishSetupAfterInvites {
                nav.finishRoomSetup(model: model)
            }
        }) { ShareSpaceSheet().environment(model).environment(self.nav) }
        .sheet(isPresented: $nav.showAddRooms) { AddRoomsSheet().environment(model).environment(self.nav) }
        .fullScreenCover(isPresented: $nav.showAR) {
            ARPlacementScreen(room: model.state.room, objects: model.displayedObjects,
                              names: Dictionary(model.displayedObjects.map { ($0.objectID, model.displayName($0)) }, uniquingKeysWith: { a, _ in a }),
                              baseURL: model.baseURL, initialObjectID: model.selectedObjectID)
                .environment(model)
        }
        .onChange(of: nav.showAR) { _, presented in model.arPresented = presented }
        .task { model.start() }
        .onOpenURL { url in
            guard url.scheme == "ragtorooms", url.host == "join", !url.lastPathComponent.isEmpty else { return }
            Task {
                do { joinInvitation = try await model.client?.invitation(token: url.lastPathComponent) }
                catch { model.errorMessage = error.localizedDescription }
            }
        }
        .alert("Join this room?", isPresented: Binding(get: { joinInvitation != nil }, set: { if !$0 { joinInvitation = nil } })) {
            Button("Join") {
                if let invitation = joinInvitation {
                    model.switchScope(to: invitation.household_id)
                    if let code = invitation.group_code { model.adoptInviteCode(code) }
                    nav.screen = .room
                }
                joinInvitation = nil
            }
            Button("Cancel", role: .cancel) { joinInvitation = nil }
        } message: { Text("Open the room shared by your roommates on your configured backend.") }
        #if DEBUG
        .task { Self.applyDebugOrientation() }
        #endif
    }

    @ViewBuilder
    private var screen: some View {
        switch nav.screen {
        case .welcome: WelcomeView()
        case .login: LoginView()
        case .signUp: SignUpView()
        case .livingSituation: LivingSituationView()
        case .joinGroup: JoinGroupView()
        case .groupSetup: GroupSetupView()
        case .floorPlan: FloorPlanUploadView()
        case .roomSelect: RoomSelectView()
        case .budgetInspiration: BudgetInspirationView()
        case .room: RoomWorkspaceView()
        }
    }

    #if DEBUG
    private static func applyDebugOrientation() {
        guard UserDefaults.standard.string(forKey: "RTROrientation") == "landscape",
              let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene else { return }
        scene.requestGeometryUpdate(.iOS(interfaceOrientations: .landscapeRight))
    }
    #endif
}

struct ErrorBanner: View {
    let message: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Color.aeroRed)
            VStack(alignment: .leading, spacing: 2) {
                Text("Server says").font(.caption.weight(.bold)).foregroundStyle(Color.aeroRed)
                Text(message).font(.subheadline).foregroundStyle(Color.aeroInk)
            }
            Spacer()
            Button("Dismiss", systemImage: "xmark", action: dismiss).labelStyle(.iconOnly).buttonStyle(GlassChipStyle())
        }
        .glassPanel(cornerRadius: 18, padding: 12)
        .accessibilityElement(children: .combine)
    }
}

#Preview(traits: .landscapeLeft) {
    ContentView().environment(AppModel()).environment(AppNavigation())
}
