import Foundation

// `GET /apartments/{aid}` from docs/API.md ("Apartment (multi-room)"). Plan coordinates are meters,
// top-down: x grows to the right, z toward the front door, origin at the apartment's back-left corner.

enum RoomKind: String, Codable, Sendable {
    case living, kitchen, bedroom, bathroom, hall, dining, closet, patio, laundry, other, unknown

    init(from decoder: Decoder) throws {
        self = RoomKind(rawValue: (try? decoder.singleValueContainer().decode(String.self)) ?? "") ?? .unknown
    }

    var label: String {
        switch self {
        case .living: "Living room"
        case .kitchen: "Kitchen"
        case .bedroom: "Bedroom"
        case .bathroom: "Bathroom"
        case .hall: "Hall"
        case .dining: "Dining"
        case .closet: "Closet"
        case .patio: "Patio"
        case .laundry: "Laundry"
        case .other, .unknown: "Room"
        }
    }

    var symbol: String {
        switch self {
        case .living: "sofa.fill"
        case .kitchen: "refrigerator.fill"
        case .bedroom: "bed.double.fill"
        case .bathroom: "shower.fill"
        case .hall: "door.left.hand.open"
        case .dining: "fork.knife"
        case .closet: "hanger"
        case .patio: "sun.max.fill"
        case .laundry: "washer.fill"
        case .other, .unknown: "square.dashed"
        }
    }
}

/// `{width_m, depth_m}` in plan meters (`room_m`, `interior_m`).
struct PlanSize: Codable, Hashable, Sendable {
    var widthM: Double
    var depthM: Double

    enum CodingKeys: String, CodingKey {
        case widthM = "width_m"
        case depthM = "depth_m"
    }
}

/// `image_frame_m`: where the whole uploaded plan image sits in plan coordinates.
struct PlanFrame: Codable, Hashable, Sendable {
    var xM: Double
    var zM: Double
    var widthM: Double
    var depthM: Double

    enum CodingKeys: String, CodingKey {
        case xM = "x_m"
        case zM = "z_m"
        case widthM = "width_m"
        case depthM = "depth_m"
    }
}

/// Plan warnings are strings; objects with a `message` are accepted too.
struct PlanWarning: Decodable, Hashable, Sendable {
    var text: String

    private enum CodingKeys: String, CodingKey { case message, detail }

    init(from decoder: Decoder) throws {
        if let text = try? decoder.singleValueContainer().decode(String.self) { self.text = text; return }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = (try? c.decode(String.self, forKey: .message)) ?? (try? c.decode(String.self, forKey: .detail)) ?? "Warning"
    }
}

struct ApartmentMember: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var name: String

    init(id: String, name: String) { self.id = id; self.name = name }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? id
    }
}

/// Per-scope rollup of the current proposal. `{}` (no proposal yet) decodes with every field empty.
struct RoomSummary: Codable, Hashable, Sendable {
    var proposalVersion: Int?
    var status: ProposalStatus?
    var knownTotalCents: Int?
    var shares: [String: Int]
    var itemCount: Int?
    var approvalsDone: Int?
    var approvalsNeeded: Int?
    var settled: Bool

    var hasProposal: Bool { proposalVersion != nil || status != nil }

    enum CodingKeys: String, CodingKey {
        case status, shares, settled
        case proposalVersion = "proposal_version"
        case knownTotalCents = "known_total_cents"
        case itemCount = "item_count"
        case approvalsDone = "approvals_done"
        case approvalsNeeded = "approvals_needed"
    }

    init(proposalVersion: Int? = nil, status: ProposalStatus? = nil, knownTotalCents: Int? = nil, shares: [String: Int] = [:],
         itemCount: Int? = nil, approvalsDone: Int? = nil, approvalsNeeded: Int? = nil, settled: Bool = false) {
        self.proposalVersion = proposalVersion; self.status = status; self.knownTotalCents = knownTotalCents
        self.shares = shares; self.itemCount = itemCount; self.approvalsDone = approvalsDone
        self.approvalsNeeded = approvalsNeeded; self.settled = settled
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        proposalVersion = try? c.decode(Int.self, forKey: .proposalVersion)
        status = try? c.decode(ProposalStatus.self, forKey: .status)
        knownTotalCents = try? c.decode(Int.self, forKey: .knownTotalCents)
        shares = (try? c.decode([String: Int].self, forKey: .shares)) ?? [:]
        itemCount = try? c.decode(Int.self, forKey: .itemCount)
        approvalsDone = try? c.decode(Int.self, forKey: .approvalsDone)
        approvalsNeeded = try? c.decode(Int.self, forKey: .approvalsNeeded)
        settled = (try? c.decode(Bool.self, forKey: .settled)) ?? false
    }

    /// The same rollup computed from a household snapshot (used for fixture plans and offline scopes).
    init(_ state: HouseholdState) {
        guard let proposal = state.proposal else { self.init(settled: state.finance.settled); return }
        let voters = proposal.shares.isEmpty ? Set(state.members.map(\.id)) : Set(proposal.shares.keys)
        self.init(proposalVersion: proposal.version, status: proposal.status, knownTotalCents: proposal.knownTotalCents,
                  shares: proposal.shares, itemCount: proposal.items.count,
                  approvalsDone: voters.filter { proposal.approvals[$0] == true }.count, approvalsNeeded: voters.count,
                  settled: state.finance.settled || proposal.status == .settled)
    }
}

struct ApartmentRoom: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var name: String
    var kind: RoomKind
    var shared: Bool
    var ownerID: String?
    /// Room scope (an ordinary household). `nil` for bathrooms, halls and not-yet-furnishable rooms.
    var householdID: String?
    var xM: Double
    var zM: Double
    var widthM: Double
    var depthM: Double
    var summary: RoomSummary?
    /// Text printed on an imported plan, e.g. "BEDROOM 2".
    var label: String?
    /// Printed interior size on an imported plan, oriented to the plan.
    var interiorM: PlanSize?
    /// The scope's actual 3D room; can differ from the plan rectangle.
    var roomM: PlanSize?

    var isFurnishable: Bool { householdID != nil }

    var sizeLabel: String {
        let size = interiorM ?? PlanSize(widthM: widthM, depthM: depthM)
        return feetLabel(widthM: size.widthM, depthM: size.depthM)
    }

    /// The printed label, when it says something the name doesn't.
    var distinctLabel: String? {
        guard let label = label?.trimmingCharacters(in: .whitespacesAndNewlines), !label.isEmpty,
              label.caseInsensitiveCompare(name) != .orderedSame else { return nil }
        return label
    }

    enum CodingKeys: String, CodingKey {
        case id, name, kind, shared, summary, label
        case interiorM = "interior_m"
        case roomM = "room_m"
        case ownerID = "owner_id"
        case householdID = "household_id"
        case xM = "x_m"
        case zM = "z_m"
        case widthM = "width_m"
        case depthM = "depth_m"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = (try? c.decode(RoomKind.self, forKey: .kind)) ?? .unknown
        name = (try? c.decode(String.self, forKey: .name)) ?? kind.label
        shared = (try? c.decode(Bool.self, forKey: .shared)) ?? false
        ownerID = try? c.decode(String.self, forKey: .ownerID)
        householdID = try? c.decode(String.self, forKey: .householdID)
        xM = try c.decode(Double.self, forKey: .xM)
        zM = try c.decode(Double.self, forKey: .zM)
        widthM = try c.decode(Double.self, forKey: .widthM)
        depthM = try c.decode(Double.self, forKey: .depthM)
        summary = try? c.decode(RoomSummary.self, forKey: .summary)
        label = try? c.decode(String.self, forKey: .label)
        interiorM = (try? c.decode(PlanSize.self, forKey: .interiorM)).flatMap { $0.widthM > 0 && $0.depthM > 0 ? $0 : nil }
        roomM = (try? c.decode(PlanSize.self, forKey: .roomM)).flatMap { $0.widthM > 0 && $0.depthM > 0 ? $0 : nil }
    }
}

/// `POST /apartments/{aid}/floorplan` response.
struct FloorplanImportResponse: Decodable, Sendable {
    var apartment: Apartment?
    var warnings: [String]

    private enum CodingKeys: String, CodingKey { case apartment, warnings }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        apartment = try? c.decode(Apartment.self, forKey: .apartment)
        warnings = (try? c.decode([LossyElement<PlanWarning>].self, forKey: .warnings))?.compactMap(\.value?.text)
            ?? apartment?.warnings ?? []
    }
}

struct ApartmentTotals: Codable, Hashable, Sendable {
    var knownTotalCents: Int
    var byMemberCents: [String: Int]

    enum CodingKeys: String, CodingKey {
        case knownTotalCents = "known_total_cents"
        case byMemberCents = "by_member_cents"
    }

    init(knownTotalCents: Int, byMemberCents: [String: Int]) {
        self.knownTotalCents = knownTotalCents; self.byMemberCents = byMemberCents
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        knownTotalCents = (try? c.decode(Int.self, forKey: .knownTotalCents)) ?? 0
        byMemberCents = (try? c.decode([String: Int].self, forKey: .byMemberCents)) ?? [:]
    }
}

struct Apartment: Decodable, Hashable, Sendable {
    var id: String
    var name: String
    var widthM: Double
    var depthM: Double
    var members: [ApartmentMember]
    var rooms: [ApartmentRoom]
    var totals: ApartmentTotals
    /// `built_in` or `imported`.
    var source: String
    var imageURL: String?
    var imageFrameM: PlanFrame?
    var warnings: [String]

    var isImported: Bool { source == "imported" }

    enum CodingKeys: String, CodingKey {
        case id, name, members, rooms, totals, source, warnings
        case widthM = "width_m"
        case depthM = "depth_m"
        case imageURL = "image_url"
        case imageFrameM = "image_frame_m"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? "demo"
        name = (try? c.decode(String.self, forKey: .name)) ?? "Apartment"
        rooms = (try? c.decode([LossyElement<ApartmentRoom>].self, forKey: .rooms))?.compactMap(\.value) ?? []
        members = (try? c.decode([LossyElement<ApartmentMember>].self, forKey: .members))?.compactMap(\.value) ?? []
        // Fall back to the rooms' bounding box when the outline is missing.
        widthM = (try? c.decode(Double.self, forKey: .widthM)) ?? rooms.map { $0.xM + $0.widthM }.max() ?? 1
        depthM = (try? c.decode(Double.self, forKey: .depthM)) ?? rooms.map { $0.zM + $0.depthM }.max() ?? 1
        totals = (try? c.decode(ApartmentTotals.self, forKey: .totals)) ?? ApartmentTotals(knownTotalCents: 0, byMemberCents: [:])
        source = (try? c.decode(String.self, forKey: .source)) ?? "built_in"
        imageURL = try? c.decode(String.self, forKey: .imageURL)
        imageFrameM = (try? c.decode(PlanFrame.self, forKey: .imageFrameM)).flatMap { $0.widthM > 0 && $0.depthM > 0 ? $0 : nil }
        warnings = (try? c.decode([LossyElement<PlanWarning>].self, forKey: .warnings))?.compactMap(\.value?.text) ?? []
    }

    /// Plan bounds, grown to include the uploaded image when it is drawn underneath.
    func drawingBounds(includingImage: Bool) -> PlanFrame {
        var minX = 0.0, minZ = 0.0, maxX = widthM, maxZ = depthM
        if includingImage, imageURL != nil, let frame = imageFrameM {
            minX = min(minX, frame.xM); minZ = min(minZ, frame.zM)
            maxX = max(maxX, frame.xM + frame.widthM); maxZ = max(maxZ, frame.zM + frame.depthM)
        }
        return PlanFrame(xM: minX, zM: minZ, widthM: max(maxX - minX, 0.1), depthM: max(maxZ - minZ, 0.1))
    }

    func room(forHousehold householdID: String?) -> ApartmentRoom? {
        rooms.first { $0.householdID != nil && $0.householdID == householdID }
    }

    func name(of memberID: String?) -> String { members.first { $0.id == memberID }?.name ?? memberID ?? "—" }

    /// Short label used by the room switcher and the plan: "Living room", "Emily's room".
    func shortName(_ room: ApartmentRoom) -> String {
        if room.kind == .bedroom, let owner = room.ownerID { return "\(name(of: owner))'s room" }
        return room.name
    }

    var furnishableRooms: [ApartmentRoom] {
        rooms.filter(\.isFurnishable).sorted { lhs, rhs in
            // Shared rooms first, then bedrooms in member order.
            let order = members.map(\.id)
            if lhs.shared != rhs.shared { return lhs.shared }
            return (order.firstIndex(of: lhs.ownerID ?? "") ?? .max) < (order.firstIndex(of: rhs.ownerID ?? "") ?? .max)
        }
    }

    /// Replaces summaries with ones computed from locally known snapshots and recomputes the totals.
    func overlaying(_ summaries: [String: RoomSummary]) -> Apartment {
        var copy = self
        for index in copy.rooms.indices {
            if let hid = copy.rooms[index].householdID, let summary = summaries[hid] { copy.rooms[index].summary = summary }
        }
        var byMember = Dictionary(members.map { ($0.id, 0) }, uniquingKeysWith: { a, _ in a })
        var total = 0
        for summary in copy.rooms.compactMap(\.summary) {
            total += summary.knownTotalCents ?? 0
            for (member, cents) in summary.shares { byMember[member, default: 0] += cents }
        }
        copy.totals = ApartmentTotals(knownTotalCents: total, byMemberCents: byMember)
        return copy
    }
}
