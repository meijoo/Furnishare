import SwiftUI

struct RoomWorkspaceView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        GeometryReader { proxy in
            let landscape = proxy.size.width > proxy.size.height && proxy.size.width >= 900
            VStack(spacing: 12) {
                roomHeader
                tabPicker
                if let message = model.errorMessage { ErrorBanner(message: message) { model.errorMessage = nil } }
                if let notice = model.scopeNotice {
                    Label(notice, systemImage: "info.circle")
                        .font(.subheadline).foregroundStyle(Color.aeroInk)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassPanel(cornerRadius: 18, padding: 10)
                }
                if nav.roomTab == .design && landscape {
                    HStack(alignment: .top, spacing: 16) {
                        RoomPanel()
                            .frame(width: proxy.size.width * 0.55)
                            .frame(maxHeight: .infinity)
                        ScrollViewReader { reader in
                            ScrollView { ItemsPanel() }
                                .scrollIndicators(.hidden)
                                .task { await debugScroll(reader) }
                        }
                    }
                } else if nav.roomTab == .members {
                    MembersView()
                } else {
                    ScrollViewReader { reader in
                        ScrollView {
                            VStack(spacing: 16) {
                                tabBody(height: proxy.size.height)
                            }
                        }
                        .scrollIndicators(.hidden)
                        .task { await debugScroll(reader) }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
    }

    private var roomHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                title
                Spacer(minLength: SettingsGearButton.reservedWidth)
            }
            RoomSwitcher()
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.white))
        .shadow(color: .black.opacity(0.05), radius: 12, y: 4)
    }

    private var title: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(model.currentRoomName).font(.title3.bold()).foregroundStyle(Color.aeroInk)
                Text(sizeLine).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var sizeLine: String {
        let room = model.state.room
        return feetLabel(widthM: room.widthM, depthM: room.depthM)
    }

    private var tabPicker: some View {
        Picker("Room section", selection: Binding(get: { nav.roomTab }, set: { nav.roomTab = $0 })) {
            ForEach(RoomTab.allCases) { tab in
                Label(tab.title, systemImage: tab.symbol).tag(tab)
            }
        }
        .pickerStyle(.segmented)
        .padding(6)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.white))
    }

    @ViewBuilder
    private func tabBody(height: CGFloat) -> some View {
        switch nav.roomTab {
        case .design:
            RoomPanel().frame(height: min(620, height * 0.55))
            ItemsPanel()
        case .items:
            ItemsPanel()
        case .budget:
            BudgetPanel()
            ContributionsPanel().id("contributions")
            FinancePanel().id("finance")
        case .inspiration:
            InspirationPanel()
            GroupSuggestionsPanel()
            ChatPanel().id("chat")
        case .members:
            MembersView()
        }
    }

    private func debugScroll(_ reader: ScrollViewProxy) async {
        #if DEBUG
        let defaults = UserDefaults.standard
        guard ["RTRScrollTo", "RTRSelect", "RTRSwitchTo"].contains(where: { defaults.string(forKey: $0) != nil }) else { return }
        try? await Task.sleep(for: .seconds(2))
        if let roomID = defaults.string(forKey: "RTRSwitchTo") {
            model.selectRoom(roomID)
            try? await Task.sleep(for: .seconds(2))
        }
        if let objectID = defaults.string(forKey: "RTRSelect") { model.select(objectID) }
        guard let target = defaults.string(forKey: "RTRScrollTo") else { return }
        try? await Task.sleep(for: .milliseconds(500))
        withAnimation { reader.scrollTo(target, anchor: .top) }
        #endif
    }
}
