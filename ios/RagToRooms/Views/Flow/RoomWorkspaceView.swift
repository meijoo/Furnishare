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
                            ScrollView { designSidePanels }
                                .scrollIndicators(.hidden)
                                .task { await debugScroll(reader) }
                        }
                    }
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
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { title; Spacer(minLength: 8); status; controls }
                VStack(alignment: .leading, spacing: 10) {
                    HStack { title; Spacer(); status }
                    HStack { Spacer(); controls }
                }
            }
            RoomSwitcher()
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.white))
        .shadow(color: .black.opacity(0.05), radius: 12, y: 4)
    }

    private var title: some View {
        HStack(spacing: 10) {
            Button {
                nav.screen = .spaces
            } label: {
                Image(systemName: "chevron.left").accessibilityLabel("Back to rooms")
            }
            .buttonStyle(GlassChipStyle())
            VStack(alignment: .leading, spacing: 2) {
                Text(model.currentRoomName).font(.title3.bold()).foregroundStyle(Color.aeroInk)
                Text(sizeLine).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var sizeLine: String {
        let room = model.state.room
        return "\(feetLabel(widthM: room.widthM, depthM: room.depthM))  ·  \(String(format: "%.1f × %.1f m", room.widthM, room.depthM))"
    }

    private var status: some View {
        HStack(spacing: 8) {
            ConnectionIndicator(status: model.connection, offlineDemo: model.isOfflineDemo)
            if model.isOfflineDemo { StatusBadge(text: "Demo fixtures", symbol: "shippingbox", tint: .aeroAmber) }
        }
        .fixedSize()
    }

    private var controls: some View {
        HStack(spacing: 8) {
            Menu {
                Picker("Acting as", selection: Binding(get: { model.actingMemberID }, set: { model.setActingMember($0) })) {
                    ForEach(model.actingCandidates, id: \.id) { candidate in
                        Text(pickerLabel(candidate.id, name: candidate.name)).tag(candidate.id)
                    }
                }
            } label: {
                Label("Acting as: \(model.actingMemberName)", systemImage: "person.crop.circle")
            }
            .buttonStyle(GlassChipStyle(selected: true))
            Button { nav.showShare = true } label: { Label("Share", systemImage: "square.and.arrow.up") }
                .buttonStyle(GlassChipStyle())
            Button { nav.showRoomSetup = true } label: { Label("Room", systemImage: "ruler") }
                .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
            Button { nav.showAR = true } label: { Label("View in AR", systemImage: "arkit") }
                .buttonStyle(AeroButtonStyle(compact: true))
            Button { nav.showSettings = true } label: { Image(systemName: "gearshape.fill").accessibilityLabel("Settings") }
                .buttonStyle(GlassChipStyle())
        }
        .lineLimit(1)
        .fixedSize()
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
            designSidePanels
        case .items:
            itemsIntro
            ProposalPanel().id("proposal")
            ProductDetailPanel().id("product")
        case .budget:
            budgetIntro
            ContributionsPanel().id("contributions")
            FinancePanel().id("finance")
        case .inspiration:
            ChatPanel().id("chat")
            ActivityPanel().id("activity")
        }
    }

    private var designSidePanels: some View {
        VStack(spacing: 16) {
            FloorPlanPanel().id("floorplan")
            Text("Need a piece that isn’t in the room yet? Browse the catalog or tell the agent in Inspiration.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button { nav.showCatalog = true } label: { Label("Browse catalog", systemImage: "square.grid.2x2") }
                    .buttonStyle(AeroButtonStyle(compact: true))
                Spacer()
            }
        }
        .padding(.bottom, 24)
    }

    private var itemsIntro: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Your items").font(.title2.bold()).foregroundStyle(Color.aeroInk)
            Text("The agent’s proposal is what the group is deciding on. Add something you already own so it doesn’t buy a duplicate.")
                .font(.subheadline).foregroundStyle(.secondary)
            HStack {
                Button { nav.showCatalog = true } label: { Label("Browse catalog", systemImage: "square.grid.2x2") }
                    .buttonStyle(AeroButtonStyle(compact: true))
                Button { nav.showAddItem = true } label: { Label("Add your item", systemImage: "plus") }
                    .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassPanel()
    }

    private var budgetIntro: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Room budget").font(.title2.bold()).foregroundStyle(Color.aeroInk)
                Spacer()
                if let budget = model.state.budgetCents, let spent = model.state.proposal?.knownTotalCents {
                    Text("\(dollars(spent)) / \(dollars(budget))").font(.title3.monospacedDigit().bold())
                }
            }
            Text("Approve the proposal, then the payer buys. Everyone else reimburses their share. Limits stay private.")
                .font(.subheadline).foregroundStyle(.secondary)
            Button { nav.showSendMoney = true } label: { Label("Send money", systemImage: "paperplane.fill") }
                .buttonStyle(AeroButtonStyle(compact: true))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassPanel()
    }

    private func pickerLabel(_ id: String, name: String) -> String {
        guard let member = model.state.member(id) else { return "\(name) (view only here)" }
        return member.isPayer ? "\(name) (payer)" : name
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
