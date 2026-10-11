import PhotosUI
import SwiftUI

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
                    Button {
                        if model.currentGroupID != nil {
                            nav.showShare = true
                        } else {
                            showAdd = true
                        }
                    } label: { Label("Add", systemImage: "plus") }
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
