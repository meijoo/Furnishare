import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model
    @State private var nav = AppNavigation()

    var body: some View {
        @Bindable var nav = nav
        ZStack {
            AeroBackground()
            screen
            if let success = nav.success {
                SuccessOverlay(kind: success)
            }
        }
        .environment(nav)
        .sheet(isPresented: $nav.showSettings) { SettingsSheet() }
        .sheet(isPresented: $nav.showRoomSetup) { RoomSetupSheet(room: model.state.room) }
        .sheet(isPresented: $nav.showCatalog) { CatalogSheet() }
        .sheet(isPresented: $nav.showAddItem) { AddItemSheet() }
        .sheet(isPresented: $nav.showSendMoney) { SendMoneySheet() }
        .sheet(isPresented: $nav.showShare) { ShareSpaceSheet() }
        .fullScreenCover(isPresented: $nav.showAR) {
            ARPlacementScreen(room: model.state.room, objects: model.displayedObjects,
                              names: Dictionary(model.displayedObjects.map { ($0.objectID, model.displayName($0)) }, uniquingKeysWith: { a, _ in a }),
                              baseURL: model.baseURL, initialObjectID: model.selectedObjectID)
        }
        .onChange(of: nav.showAR) { _, presented in model.arPresented = presented }
        .task { model.start() }
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
        case .spaces: SpacesHubView()
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
    ContentView().environment(AppModel())
}
