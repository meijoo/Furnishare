import SwiftUI

/// The same room cards and floor-plan preview for setup and adding rooms later.
struct RoomSelectionContent: View {
    @Environment(AppModel.self) private var model
    @Binding var selection: Set<String>
    var savedRoomIDs: Set<String> = []

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 20) {
                roomCards.frame(width: 340)
                planCard.layoutPriority(1)
            }
            VStack(alignment: .leading, spacing: 16) { roomCards; planCard }
        }
    }

    private var planSelection: Binding<Set<String>> {
        Binding(get: { selection }, set: { selection = $0.intersection(Set(model.accessibleFurnishableRooms.map(\.id))).union(savedRoomIDs) })
    }

    private var planCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Floor plan preview").font(.headline)
            if let apartment = model.apartment {
                ApartmentPlanView(apartment: apartment, showImage: true, compact: true, maxHeight: 780,
                                 selection: planSelection)
            } else {
                Text("Plan unavailable.").foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .glassPanel()
    }

    private var roomCards: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Choose the rooms you have access to").font(.headline)
            if let apartment = model.apartment {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 10)], spacing: 10) {
                    ForEach(apartment.rooms.filter { $0.kind != .hall && $0.kind != .closet && $0.kind != .other }) { room in
                        roomCard(room, apartment: apartment)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
        .glassPanel()
    }

    private func roomCard(_ room: ApartmentRoom, apartment: Apartment) -> some View {
        let selected = selection.contains(room.id)
        let enabled = model.accessibleFurnishableRooms.contains { $0.id == room.id }
        let saved = savedRoomIDs.contains(room.id)
        return Button {
            if selected { selection.remove(room.id) } else { selection.insert(room.id) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                ZStack(alignment: .topTrailing) {
                    RoomIllustration(scene: room.kind.scene)
                        .frame(height: 80)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    Image(systemName: selected ? "checkmark.square.fill" : "square")
                        .foregroundStyle(enabled ? Color.aeroSky : Color.figmaMuted)
                        .padding(6)
                }
                Text(apartment.shortName(room)).font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk).lineLimit(1)
                Text(enabled ? room.sizeLabel : room.kind.label).font(.caption).foregroundStyle(.secondary)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.white.opacity(enabled ? 0.85 : 0.4)))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(selected ? Color.aeroSky : .clear, lineWidth: 2))
            .opacity(enabled ? 1 : 0.55)
        }
        .buttonStyle(.plain)
        .disabled(!enabled || saved)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityHint(saved ? "Already added to your rooms" : "")
    }
}

struct AddRoomsSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @State private var selection: Set<String> = []
    @State private var savedRoomIDs: Set<String> = []
    @State private var budgets: [String: String] = [:]
    @State private var saving = false
    @State private var errorMessage: String?

    private var newRooms: [ApartmentRoom] {
        model.accessibleFurnishableRooms.filter { selection.contains($0.id) && !savedRoomIDs.contains($0.id) }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    RoomSelectionContent(selection: $selection, savedRoomIDs: savedRoomIDs)
                    if model.account != nil {
                        ForEach(newRooms) { room in
                            if let hid = room.householdID {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("Your budget for \(room.name) (USD)").font(.headline)
                                    TextField("0.00", text: Binding(get: { budgets[hid] ?? "" }, set: { budgets[hid] = $0 }))
                                        .keyboardType(.decimalPad).textFieldStyle(.roundedBorder)
                                }
                            }
                        }
                    }
                    if let errorMessage { Text(errorMessage).foregroundStyle(.red) }
                }.padding(24).disabled(saving)
            }
            .navigationTitle("Select more rooms")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Done") { Task { await save() } }.disabled(saving)
                }
            }
        }
        .presentationDetents([.large])
        .onAppear {
            let rooms = Set(model.accessibleFurnishableRooms.map(\.id))
            savedRoomIDs = nav.selectedRoomIDs.isEmpty ? rooms : nav.selectedRoomIDs.intersection(rooms)
            selection = savedRoomIDs
        }
    }

    private func save() async {
        if model.account != nil, !newRooms.isEmpty {
            guard let client = model.client else { errorMessage = "Connect to save your room budgets."; return }
            var preferences: [String: SetupRoomRequest] = [:]
            for room in newRooms {
                guard let hid = room.householdID,
                      let amount = ContributionsPanel.cents(from: budgets[hid] ?? ""), amount <= 50_000_000 else {
                    errorMessage = "Enter your budget for each new room."; return
                }
                preferences[hid] = SetupRoomRequest(budget_cents: amount)
            }
            saving = true
            defer { saving = false }
            do {
                try await client.saveSetup(apartmentID: model.activeApartmentID,
                    body: SetupPreferencesRequest(member_id: model.actingMemberID, rooms: preferences))
                await model.refreshSetupState()
            } catch { errorMessage = "Couldn't save your room budgets. Please try again."; return }
        }
        nav.addRooms(selection.union(savedRoomIDs))
        dismiss()
    }
}
