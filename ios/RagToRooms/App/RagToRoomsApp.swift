import SwiftUI

@main
struct RagToRoomsApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(model)
                .tint(.aeroSky)
                .onOpenURL { model.handleOpenURL($0) }
        }
    }
}
