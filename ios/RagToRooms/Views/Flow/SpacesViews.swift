import SwiftUI

struct SpacesHubView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        @Bindable var nav = nav
        GeometryReader { proxy in
            let wide = proxy.size.width >= 760
            VStack(spacing: 0) {
                hubHeader
                if let message = model.errorMessage { ErrorBanner(message: message) { model.errorMessage = nil } }
                if wide {
                    HStack(alignment: .top, spacing: 0) {
                        sidebar.frame(width: 200)
                        content.frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                } else {
                    Picker("Section", selection: $nav.hubSection) {
                        ForEach(HubSection.allCases) { section in
                            Label(section.title, systemImage: section.symbol).tag(section)
                        }
                    }
                    .pickerStyle(.segmented)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    content
                }
            }
        }
        .task {
            while !Task.isCancelled {
                await model.refreshApartment()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    private var hubHeader: some View {
        HStack(spacing: 12) {
            BrandMark(compact: true)
            HStack(spacing: 10) {
                if !nav.groupName.isEmpty {
                    Label(nav.groupName, systemImage: "person.3")
                }
                if !nav.groupLocation.isEmpty {
                    Text("|").foregroundStyle(Color.black.opacity(0.12))
                    Label(nav.groupLocation, systemImage: "mappin.and.ellipse")
                }
            }
            .font(.subheadline)
            .foregroundStyle(Color.aeroInk)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Capsule().fill(Color.white))
            .overlay(Capsule().strokeBorder(Color.black.opacity(0.05), lineWidth: 1))
            Spacer()
            ConnectionIndicator(status: model.connection, offlineDemo: model.isOfflineDemo)
            Button { nav.showShare = true } label: {
                Label("Share", systemImage: "square.and.arrow.up")
            }
            .buttonStyle(AeroButtonStyle(compact: true))
            Button { nav.showSettings = true } label: { Image(systemName: "gearshape").accessibilityLabel("Settings") }
                .buttonStyle(GlassChipStyle())
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(Color.white.opacity(0.92))
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button { nav.hubSection = .rooms } label: {
                SidebarRow(title: "Rooms", symbol: "house", selected: nav.hubSection == .rooms)
            }
            .buttonStyle(.plain)
            SidebarRow(title: "Tasks", symbol: "checkmark.circle", disabled: true)
            Button { nav.hubSection = .members } label: {
                SidebarRow(title: "Members", symbol: "person.2", selected: nav.hubSection == .members)
            }
            .buttonStyle(.plain)
            SidebarRow(title: "Calendar", symbol: "calendar", disabled: true)
            Spacer()
            Button { nav.showSettings = true } label: {
                SidebarRow(title: "Settings", symbol: "gearshape")
            }
            .buttonStyle(.plain)
        }
        .padding(16)
    }

    @ViewBuilder private var content: some View {
        switch nav.hubSection {
        case .rooms: SpacesGridView()
        case .members: MembersView()
        }
    }
}

struct SpacesGridView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Your Spaces").font(.system(size: 34, weight: .bold)).foregroundStyle(Color.aeroInk)
                    Text("Select a space to start designing.")
                        .foregroundStyle(Color.figmaMuted)
                }
                if let notice = model.scopeNotice {
                    Label(notice, systemImage: "info.circle").font(.subheadline).foregroundStyle(Color.aeroInk)
                }
                if let apartment = model.apartment {
                    let selected = nav.selectedRoomIDs
                    let rooms = apartment.furnishableRooms.filter { selected.isEmpty || selected.contains($0.id) }
                    let soon = apartment.rooms.filter { !$0.isFurnishable && ($0.kind == .kitchen || $0.kind == .dining) }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 18)], spacing: 18) {
                        ForEach(rooms) { room in
                            SpaceCard(room: room, apartment: apartment)
                        }
                        ForEach(soon) { room in
                            SpaceCard(room: room, apartment: apartment, comingSoon: true)
                        }
                    }
                    if rooms.isEmpty {
                        Label("No rooms selected yet. Replay the intro from Settings to pick rooms.", systemImage: "square.dashed")
                            .foregroundStyle(Color.figmaMuted)
                    }
                } else {
                    Text("The apartment plan isn’t available.").foregroundStyle(Color.figmaMuted)
                }
            }
            .padding(24)
        }
        .scrollIndicators(.hidden)
    }
}

private struct SpaceCard: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    let room: ApartmentRoom
    let apartment: Apartment
    var comingSoon = false

    var body: some View {
        Button { if !comingSoon { nav.enterRoom(room, model: model) } } label: {
            VStack(alignment: .leading, spacing: 0) {
                ZStack(alignment: .topTrailing) {
                    RoomIllustration(scene: room.kind.scene)
                        .frame(height: 150)
                    Image(systemName: "ellipsis")
                        .padding(10)
                        .foregroundStyle(.white.opacity(0.9))
                        .accessibilityHidden(true)
                }
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(apartment.shortName(room)).font(.headline).foregroundStyle(Color.aeroInk)
                        Text(room.sizeLabel).font(.caption).foregroundStyle(Color.figmaMuted)
                    }
                    Spacer()
                    if room.shared {
                        MemberAvatars(names: apartment.members.map(\.name))
                    } else if let owner = room.ownerID {
                        MemberAvatars(names: [apartment.name(of: owner)])
                    }
                    Image(systemName: comingSoon ? "clock" : "arrow.right")
                        .foregroundStyle(Color.figmaMuted)
                }
                .padding(14)
            }
            .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.white))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 14, y: 6)
        }
        .buttonStyle(.plain)
        .disabled(comingSoon)
        .opacity(comingSoon ? 0.85 : 1)
        .accessibilityHint(comingSoon ? "Coming soon" : "Opens this room")
    }
}

struct MembersView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Members").font(.system(size: 34, weight: .bold)).foregroundStyle(Color.aeroInk)
                Text("Everyone in the apartment. “Acting as” is how this demo switches whose approvals and payments you see.")
                    .foregroundStyle(Color.figmaMuted)
                ForEach(model.actingCandidates, id: \.id) { candidate in
                    let mine = candidate.id == model.actingMemberID
                    HStack(spacing: 12) {
                        Text(String(candidate.name.prefix(1)))
                            .font(.title3.bold())
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(Circle().fill(Color.aeroSky))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(candidate.name).font(.headline)
                            if mine { Text("You’re acting as this person").font(.caption).foregroundStyle(Color.figmaMuted) }
                            else { Text("Tap to act as \(candidate.name)").font(.caption).foregroundStyle(Color.figmaMuted) }
                        }
                        Spacer()
                        if mine { StatusBadge(text: "You", symbol: "checkmark", tint: .aeroSky) }
                    }
                    .foregroundStyle(Color.aeroInk)
                    .padding(14)
                    .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color.white))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(mine ? Color.aeroSky : Color.clear, lineWidth: 1.5))
                    .onTapGesture { model.setActingMember(candidate.id) }
                }
            }
            .padding(24)
        }
    }
}
