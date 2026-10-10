import SwiftUI

@main
struct RagToRoomsApp: App {
    @State private var model = AppModel()
    @State private var nav = AppNavigation()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(model)
                .environment(nav)
                .tint(.aeroSky)
                .onOpenURL { model.handleOpenURL($0) }
        }
    }
}
