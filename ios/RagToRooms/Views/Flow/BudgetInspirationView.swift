import SwiftUI
import PhotosUI

struct SetupPhoto: Identifiable {
    let id = UUID()
    let upload: UploadImage
}

struct BudgetInspirationView: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var groupBudget = ""
    @State private var individualBudget = ""
    @State private var descriptions: [String: String] = [:]
    @State private var photos: [String: [SetupPhoto]] = [:]
    @State private var preparing: [String: Bool] = [:]
    @State private var saving = false
    @State private var loading = true
    @State private var errorMessage: String?
    private var solo: Bool { nav.livingMode == .solo }
    private var rooms: [ApartmentRoom] {
        (model.apartment?.furnishableRooms ?? []).filter { nav.selectedRoomIDs.contains($0.id) }
    }

    var body: some View {
        OnboardingPage(step: 4, back: .roomSelect, maxWidth: 900) {
            VStack(alignment: .leading, spacing: 22) {
                Text("Budget and inspiration").font(.largeTitle.bold()).foregroundStyle(.black)
                VStack(alignment: .leading, spacing: 14) {
                    Text("Set your budget").font(.title2.bold())
                    budgetField(solo ? "Your budget (USD)" : "Group budget (USD)", text: $groupBudget)
                    if !solo { budgetField("Your individual budget (USD)", text: $individualBudget) }
                    Text("Your total budget is divided across the rooms you selected.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.glassPanel(cornerRadius: 20, padding: 20)
                Text("Room inspiration").font(.title2.bold())
                Text("Add photos or describe the look you want for each room. You can add more later.")
                    .foregroundStyle(.secondary)
                ForEach(rooms) { room in
                    if let hid = room.householdID {
                        SetupInspirationCard(name: room.name,
                            description: Binding(get: { descriptions[hid] ?? "" }, set: { descriptions[hid] = $0 }),
                            photos: Binding(get: { photos[hid] ?? [] }, set: { photos[hid] = $0 }),
                            preparing: Binding(get: { preparing[hid] ?? false }, set: { preparing[hid] = $0 }))
                    }
                }
                if let errorMessage { Text(errorMessage).foregroundStyle(.red) }
                HStack {
                    Spacer()
                    Button(saving ? "Saving…" : "Submit", action: submit)
                        .buttonStyle(AeroButtonStyle())
                        .disabled(loading || saving || preparing.values.contains(true))
                }
            }.disabled(saving || loading)
        }
        .task { await load() }
    }

    private func budgetField(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            TextField("0.00", text: text).keyboardType(.decimalPad)
                .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 12))
        }
    }

    private func load() async {
        defer { loading = false }
        guard let client = model.client else { errorMessage = "Connect to the backend to save your setup."; return }
        do {
            let saved = try await client.setupPreferences(apartmentID: model.activeApartmentID, memberID: model.actingMemberID)
            if let amount = saved.group_budget_cents { groupBudget = String(format: "%.2f", Double(amount) / 100) }
            if let amount = saved.individual_budget_cents { individualBudget = String(format: "%.2f", Double(amount) / 100) }
            for room in saved.rooms { descriptions[room.household_id] = room.description }
        } catch { errorMessage = "Couldn't load saved preferences. Please try again." }
    }

    private func cents(_ text: String) -> Int? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.range(of: "^[0-9]+(\\.[0-9]{1,2})?$", options: .regularExpression) != nil,
              let decimal = Decimal(string: value), decimal <= 500_000 else { return nil }
        return NSDecimalNumber(decimal: decimal * 100).intValue
    }

    private func submit() {
        guard let group = cents(groupBudget), group > 0,
              let individual = solo ? group : cents(individualBudget), individual <= group else {
            errorMessage = "Enter a positive budget. Your individual budget must fit within the group budget."
            return
        }
        guard let client = model.client, !rooms.isEmpty else {
            errorMessage = "Connect to the backend and select at least one room."; return
        }
        let roomDescriptions = Dictionary(uniqueKeysWithValues: Set(rooms.compactMap(\.householdID)).map {
            ($0, descriptions[$0] ?? "")
        })
        guard roomDescriptions.values.allSatisfy({ $0.count <= 5000 }) else {
            errorMessage = "Keep each room description under 5,000 characters."; return
        }
        saving = true
        errorMessage = nil
        Task {
            defer { saving = false }
            do {
                try await client.saveSetup(apartmentID: model.activeApartmentID, body: SetupPreferencesRequest(
                    member_id: model.actingMemberID, group_budget_cents: group,
                    individual_budget_cents: individual, solo: solo, rooms: roomDescriptions))
                for hid in roomDescriptions.keys.sorted() {
                    for photo in photos[hid] ?? [] {
                        try await client.uploadRoomInspiration(householdID: hid, image: photo.upload)
                        photos[hid]?.removeAll { $0.id == photo.id }
                    }
                }
                await model.refreshSetupState()
                nav.persistProfile()
                nav.finishSetupAfterInvites = true
                nav.showShare = true
            } catch { errorMessage = "Couldn't save all your preferences and photos. Please try again." }
        }
    }
}

private struct SetupInspirationCard: View {
    let name: String
    @Binding var description: String
    @Binding var photos: [SetupPhoto]
    @Binding var preparing: Bool
    @State private var selection: [PhotosPickerItem] = []
    @State private var photoError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(name).font(.headline)
            TextField("Describe your furniture or room's vibe", text: $description, axis: .vertical)
                .lineLimit(3...6).padding(12)
                .background(.white, in: RoundedRectangle(cornerRadius: 12))
            if !photos.isEmpty {
                ScrollView(.horizontal) {
                    HStack {
                        ForEach(photos) { photo in
                            if let image = UIImage(data: photo.upload.data) {
                                VStack {
                                    Image(uiImage: image).resizable().scaledToFill()
                                        .frame(width: 100, height: 100).clipped().clipShape(RoundedRectangle(cornerRadius: 12))
                                    Button("Remove") { photos.removeAll { $0.id == photo.id } }
                                }
                            }
                        }
                    }
                }
            }
            PhotosPicker(selection: $selection, maxSelectionCount: 8, matching: .images) {
                Label(preparing ? "Preparing photos…" : "Add inspiration photos", systemImage: "photo.badge.plus")
            }.disabled(preparing)
            if let photoError { Text(photoError).font(.footnote).foregroundStyle(.red) }
        }
        .glassPanel(cornerRadius: 20, padding: 20)
        .onChange(of: selection) { _, items in
            guard !items.isEmpty else { return }
            preparing = true
            photoError = nil
            Task {
                defer { preparing = false; selection = [] }
                for item in items {
                    if let data = try? await item.loadTransferable(type: Data.self),
                       let upload = await UploadImage.prepare(data, maxLongSide: 1600, keepPNG: false, name: "inspiration") {
                        photos.append(SetupPhoto(upload: upload))
                    } else { photoError = "Couldn't read a photo. Please choose it again." }
                }
            }
        }
    }
}
