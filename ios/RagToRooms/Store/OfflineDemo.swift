import Foundation

/// Offline demo mode: bundled fixtures plus a small local simulation of the server rules,
/// so the app is fully clickable without a backend.
extension AppModel {
    static func loadFixtures() -> (state: HouseholdState, products: [Product]) {
        do {
            let decoder = JSONDecoder()
            let state = try decoder.decode(HouseholdState.self, from: try fixtureData("demo_state"))
            let products = try decoder.decode(ProductList.self, from: try fixtureData("demo_products")).products
            return (state, products)
        } catch {
            assertionFailure("Bundled fixtures failed to decode: \(error)")
            return (minimalFallbackState, [])
        }
    }

    static let fixtureApartment: Apartment? = {
        do {
            return try JSONDecoder().decode(Apartment.self, from: try fixtureData("demo_apartment"))
        } catch {
            assertionFailure("Bundled apartment fixture failed to decode: \(error)")
            return nil
        }
    }()

    /// Offline snapshot for any room scope. Emily's bedroom carries a demo proposal; the other bedrooms start empty.
    static func fixtureState(forScope householdID: String) -> HouseholdState {
        if householdID == defaultHouseholdID { return loadFixtures().state }
        var state = blankState(forScope: householdID, apartment: fixtureApartment)
        guard fixtureApartment?.room(forHousehold: householdID)?.ownerID == "emily" else { return state }
        let pieces: [(id: String, category: String, title: String, cents: Int, x: Double, z: Double, rotation: Double,
                      size: Dimensions, hex: String)] = [
            ("bed-queen", "bed", "Drift queen bed", 49900, 0, -0.7, 0, Dimensions(width: 1.6, depth: 2.1, height: 1.0), "#D8CBB6"),
            ("nightstand", "nightstand", "Pebble nightstand", 7900, -1.075, -1.55, 0, Dimensions(width: 0.45, depth: 0.4, height: 0.55), "#D1B48C"),
            ("dresser", "dresser", "Tide dresser", 19900, -1.5, 0.7, .pi / 2, Dimensions(width: 1.0, depth: 0.5, height: 0.8), "#E6E9EC"),
            ("desk", "desk", "Cirrus desk", 12900, 1.475, -0.2, -.pi / 2, Dimensions(width: 1.0, depth: 0.55, height: 0.75), "#C9B79C")
        ]
        let total = pieces.map(\.cents).reduce(0, +)
        state.budgetCents = 100000
        state.proposal = Proposal(
            version: 1, status: .awaitingApproval,
            items: pieces.map { ProposalItem(productID: $0.id, category: $0.category, priceCents: $0.cents, title: $0.title, sourceType: "demo") },
            knownTotalCents: total, unknownCosts: ["shipping", "tax"], shares: ["emily": total], approvals: ["emily": false],
            explanation: "Offline demo proposal. This is Emily's private room, so Emily pays 100% and approves alone. The bed's headboard is on the back wall, the nightstand is on the side away from the door, and nothing blocks the door swing.",
            createdAt: "2026-10-10T05:00:00Z")
        state.scene = SceneState(objects: pieces.map {
            SceneObject(objectID: "obj-\($0.category)", productID: $0.id, category: $0.category, positionM: [$0.x, 0, $0.z],
                        rotationYRad: $0.rotation, dimensionsM: $0.size, colorHex: $0.hex, assetURL: nil, proposalVersion: 1)
        }, validation: nil)
        state.activity.insert(ActivityEntry(at: "2026-10-10T05:01:00Z", text: "Agent proposed version 1 for \(dollars(total)) (shipping and tax unknown)"), at: 0)
        return state
    }

    /// Empty snapshot for a scope: right size from the plan, a front door, members from the plan. Also the
    /// stand-in shown while a scope that was never visited loads from the backend.
    static func blankState(forScope householdID: String, apartment: Apartment?) -> HouseholdState {
        let planRoom = apartment?.room(forHousehold: householdID)
        let width = planRoom?.widthM ?? 3.5, depth = planRoom?.depthM ?? 3.5
        let members: [Member]
        if let planRoom, !planRoom.shared, let owner = planRoom.ownerID {
            members = [Member(id: owner, name: apartment?.name(of: owner) ?? owner, isPayer: true, hasLimit: false, connected: false)]
        } else {
            members = (apartment?.members ?? []).enumerated().map { Member(id: $1.id, name: $1.name, isPayer: $0 == 0) }
        }
        let doorOffset = width / 2 - 0.75
        let room = Room(widthM: width, depthM: depth, heightM: 2.5,
                        openings: [Opening(kind: "door", wall: "front", offsetM: doorOffset, widthM: 0.9),
                                   Opening(kind: "window", wall: "back", offsetM: 0, widthM: 1.0)],
                        clearances: [Clearance(label: "door swing", xM: doorOffset, zM: depth / 2 - 0.45, widthM: 0.9, depthM: 0.9)])
        return HouseholdState(householdID: householdID, stateVersion: 1, members: members, room: room, budgetCents: nil,
                              proposal: nil, scene: SceneState(objects: [], validation: nil),
                              finance: Finance(payerID: members.first(where: \.isPayer)?.id ?? "", simulator: "mock"),
                              activity: [ActivityEntry(at: "2026-10-10T05:00:00Z", text: "\(planRoom?.name ?? "Room") loaded")],
                              catalogMode: "demo")
    }

    private static func fixtureData(_ name: String) throws -> Data {
        guard let url = Bundle.main.url(forResource: name, withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: "\(name).json"])
        }
        return try Data(contentsOf: url)
    }

    /// Last-resort state built from the original sample furniture.
    private static var minimalFallbackState: HouseholdState {
        let sofa = Furniture.samples[0]
        let object = SceneObject(objectID: "obj-sofa", productID: sofa.id, category: sofa.category, positionM: [0, 0, -1.5],
                                 rotationYRad: 0, dimensionsM: Dimensions(width: Double(sofa.width), depth: Double(sofa.depth), height: Double(sofa.height)),
                                 colorHex: nil, assetURL: nil, proposalVersion: nil)
        return HouseholdState(householdID: "demo", stateVersion: 0,
                              members: [Member(id: "emily", name: "Emily", isPayer: true)],
                              room: Room(widthM: 4.5, depthM: 4, heightM: 2.5),
                              budgetCents: nil, proposal: nil,
                              scene: SceneState(objects: [object], validation: nil),
                              finance: Finance(payerID: "emily", simulator: "mock"),
                              activity: [])
    }

    func appendActivity(_ text: String) {
        state.activity.insert(ActivityEntry(at: ISO8601DateFormatter().string(from: Date()), text: text), at: 0)
        state.stateVersion += 1
    }

    func offlineApprove(_ member: String) {
        guard approvalBlocker == nil, var proposal = state.proposal else { errorMessage = approvalBlocker; return }
        proposal.approvals[member] = true
        proposal.objections[member] = nil
        if proposal.shares.keys.allSatisfy({ proposal.approvals[$0] == true }) { proposal.status = .approved }
        state.proposal = proposal
        appendActivity("\(state.name(of: member)) approved version \(proposal.version)")
        if proposal.status == .approved { appendActivity("Everyone approved version \(proposal.version)") }
    }

    func offlineObject(_ member: String, reason: String) {
        guard objectionBlocker == nil, var proposal = state.proposal else { errorMessage = objectionBlocker; return }
        proposal.approvals[member] = false
        proposal.objections[member] = reason
        proposal.status = .awaitingApproval
        state.proposal = proposal
        appendActivity("\(state.name(of: member)) objected: \(reason.isEmpty ? "no reason given" : reason)")
    }

    func offlineSetLimit(_ member: String, cents: Int) {
        if let index = state.members.firstIndex(where: { $0.id == member }) {
            state.members[index].hasLimit = true
            state.members[index].limitCents = cents
        }
        appendActivity("\(state.name(of: member)) updated their limit")
    }

    func offlineSaveRoom(_ room: Room) {
        var updated = room
        updated.inspirationImageURL = state.room.inspirationImageURL
        state.room = updated
        appendActivity("Room updated to \(String(format: "%.1f × %.1f m", room.widthM, room.depthM)) (offline demo)")
    }

    func offlineAuthorizePurchase() {
        guard purchaseBlocker == nil, let proposal = state.proposal else { errorMessage = purchaseBlocker; return }
        let now = ISO8601DateFormatter().string(from: Date())
        state.finance.purchase = FinancialOperation(opKey: "purchase:\(state.householdID):v\(proposal.version)", kind: "purchase",
                                                    fromMember: state.finance.payerID, toMember: nil,
                                                    amountCents: proposal.knownTotalCents, proposalVersion: proposal.version,
                                                    state: .authorized, externalID: nil, error: nil, updatedAt: now, simulator: "mock")
        appendActivity("\(state.name(of: state.finance.payerID)) authorized the purchase (simulated)")
        simulateProgress { model, step in
            model.state.finance.purchase?.state = step
            if step == .confirmed {
                model.state.finance.purchase?.externalID = "offline-\(UUID().uuidString.prefix(8))"
                model.state.proposal?.status = .purchased
                model.appendActivity("Purchase confirmed (simulated)")
                if model.state.finance.reimbursements.isEmpty {
                    // Private room: nobody owes the payer anything.
                    model.state.finance.settled = true
                    model.state.proposal?.status = .settled
                    model.appendActivity("Room settled")
                }
            }
        }
    }

    func offlineAuthorizeReimbursement(_ liabilityID: String) {
        guard let index = state.finance.reimbursements.firstIndex(where: { $0.liabilityID == liabilityID }) else { return }
        let r = state.finance.reimbursements[index]
        if let blocker = reimbursementBlocker(r) { errorMessage = blocker; return }
        state.finance.reimbursements[index].operation = FinancialOperation(
            opKey: "reimbursement:\(liabilityID)", kind: "reimbursement", fromMember: r.fromMember, toMember: r.toMember,
            amountCents: r.amountCents, proposalVersion: state.proposal?.version, state: .authorized,
            externalID: nil, error: nil, updatedAt: ISO8601DateFormatter().string(from: Date()), simulator: "mock")
        appendActivity("\(state.name(of: r.fromMember)) authorized a reimbursement of \(dollars(r.amountCents)) (simulated)")
        simulateProgress { model, step in
            guard let i = model.state.finance.reimbursements.firstIndex(where: { $0.liabilityID == liabilityID }) else { return }
            model.state.finance.reimbursements[i].operation?.state = step
            guard step == .confirmed else { return }
            model.appendActivity("Reimbursement from \(model.state.name(of: r.fromMember)) confirmed (simulated)")
            if model.state.finance.reimbursements.allSatisfy({ $0.operation?.state == .confirmed }) {
                model.state.finance.settled = true
                model.state.proposal?.status = .settled
                model.appendActivity("Household settled up")
            }
        }
    }

    private func simulateProgress(_ update: @escaping @MainActor (AppModel, OperationState) -> Void) {
        Task { [weak self] in
            for step in [OperationState.submitting, .pending, .confirmed] {
                try? await Task.sleep(for: .milliseconds(900))
                guard let self, self.isOfflineDemo else { return }
                update(self, step)
            }
        }
    }
}
