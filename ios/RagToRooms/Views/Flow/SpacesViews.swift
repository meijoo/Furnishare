import PhotosUI
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
            Spacer().frame(minWidth: SettingsGearButton.reservedWidth)
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
            Button { nav.hubSection = .members } label: {
                SidebarRow(title: "Members", symbol: "person.2", selected: nav.hubSection == .members)
            }
            .buttonStyle(.plain)
            Spacer()
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
    @Environment(AppNavigation.self) private var nav
    @State private var showAdd = false
    @State private var newName = ""
    @State private var newPhoto: UIImage?
    @State private var addPhotoItem: PhotosPickerItem?
    @State private var rosterPhotoItem: PhotosPickerItem?
    @State private var photoTarget: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Members").font(.system(size: 34, weight: .bold)).foregroundStyle(Color.aeroInk)
                inviteCard
                HStack {
                    Text("People").font(.title3.bold()).foregroundStyle(Color.aeroInk)
                    Spacer()
                    Button { showAdd = true } label: { Label("Add", systemImage: "plus") }
                        .buttonStyle(AeroButtonStyle(compact: true))
                }
                ForEach(model.groupRoster) { person in
                    personRow(person)
                }
            }
            .padding(24)
        }
        .photosPicker(isPresented: Binding(get: { photoTarget != nil }, set: { if !$0 { photoTarget = nil } }),
                      selection: $rosterPhotoItem, matching: .images)
        .onChange(of: rosterPhotoItem) { _, item in
            guard let item, let id = photoTarget else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                    model.setPersonPhoto(id, image: image)
                }
                photoTarget = nil
                rosterPhotoItem = nil
            }
        }
        .sheet(isPresented: $showAdd) { addSheet }
    }

    private var inviteCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Invite").font(.headline).foregroundStyle(Color.aeroInk)
            Text("Send this code so someone can join the group.")
                .font(.subheadline).foregroundStyle(Color.figmaMuted)
            HStack {
                Text(model.inviteCode)
                    .font(.system(size: 28, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(Color.aeroInk)
                Spacer()
                Button("Copy") {
                    UIPasteboard.general.string = model.inviteCode
                    nav.showSuccess(.linkCopied)
                }
                .buttonStyle(OutlinePillStyle())
            }
            ShareLink(item: model.inviteMessage) {
                Label("Send invite", systemImage: "square.and.arrow.up")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(AeroWideButtonStyle())
            Button { nav.showShare = true } label: {
                Label("Text invitations", systemImage: "bubble.left.and.bubble.right")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(AeroWideButtonStyle(outlined: true))
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color.white))
    }

    private func personRow(_ person: GroupPerson) -> some View {
        HStack(spacing: 12) {
            Button { photoTarget = person.id } label: {
                personThumb(person)
                    .frame(width: 52, height: 52)
                    .clipShape(Circle())
                    .overlay(Circle().strokeBorder(Color.white, lineWidth: 2))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Change photo for \(person.name)")
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(person.name).font(.headline).foregroundStyle(Color.aeroInk)
                    if person.id == model.actingMemberID {
                        Text("you").font(.caption).foregroundStyle(Color.figmaMuted)
                    }
                    if person.invited {
                        StatusBadge(text: "Invited", symbol: "envelope")
                    }
                }
                Text("Tap the photo to add or change it")
                    .font(.caption).foregroundStyle(Color.figmaMuted)
            }
            Spacer()
            if person.invited {
                Button {
                    model.removePerson(person.id)
                } label: {
                    Image(systemName: "trash").accessibilityLabel("Remove \(person.name)")
                }
                .buttonStyle(GlassChipStyle())
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white))
    }

    @ViewBuilder private func personThumb(_ person: GroupPerson) -> some View {
        if let url = model.personPhotoURL(person) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image): image.resizable().scaledToFill()
                default: initials(person)
                }
            }
        } else {
            initials(person)
        }
    }

    private func initials(_ person: GroupPerson) -> some View {
        ZStack {
            Circle().fill(Color.figmaWash)
            Text(String(person.name.prefix(1)))
                .font(.title3.bold())
                .foregroundStyle(Color.aeroInk)
        }
    }

    private var addSheet: some View {
        NavigationStack {
            Form {
                Section("Name") { TextField("Maya", text: $newName) }
                Section("Photo") {
                    PhotosPicker(selection: $addPhotoItem, matching: .images) {
                        if let newPhoto {
                            Image(uiImage: newPhoto).resizable().scaledToFill()
                                .frame(height: 140).clipped().clipShape(RoundedRectangle(cornerRadius: 12))
                        } else {
                            Label("Add a photo", systemImage: "person.crop.circle.badge.plus")
                        }
                    }
                }
            }
            .navigationTitle("Add someone")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { showAdd = false } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        model.addPerson(name: newName, image: newPhoto)
                        newName = ""
                        newPhoto = nil
                        showAdd = false
                    }
                    .disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onChange(of: addPhotoItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        newPhoto = UIImage(data: data)
                    }
                }
            }
        }
        .presentationDetents([.medium])
    }
}
