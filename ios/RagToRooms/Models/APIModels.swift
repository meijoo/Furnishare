import Foundation

// Wire types for docs/API.md. Keys are spelled out explicitly (no convertFromSnakeCase)
// because that strategy would also rewrite dictionary keys such as member ids.

struct Dimensions: Codable, Hashable, Sendable {
    var width: Double
    var depth: Double
    var height: Double

    var listingLabel: String {
        let inches: (Double) -> String = { String(format: "%.0f\"", $0 / 0.0254) }
        return "\(inches(width)) × \(inches(depth)) × \(inches(height))"
    }
}

struct Evidence: Codable, Hashable, Sendable {
    var field: String
    var quote: String
    var sourceURL: String?

    enum CodingKeys: String, CodingKey {
        case field, quote
        case sourceURL = "source_url"
    }
}

struct AdditionalCosts: Codable, Hashable, Sendable {
    var shippingCents: Int?
    var taxCents: Int?
    var assemblyCents: Int?

    enum CodingKeys: String, CodingKey {
        case shippingCents = "shipping_cents"
        case taxCents = "tax_cents"
        case assemblyCents = "assembly_cents"
    }

    /// Names of costs that are `null` (unknown). Unknown is never treated as zero.
    var unknownNames: [String] {
        [("shipping", shippingCents), ("tax", taxCents), ("assembly", assemblyCents)]
            .filter { $0.1 == nil }.map(\.0)
    }
}

struct ProductStyle: Codable, Hashable, Sendable {
    var colorHex: String?
    var material: String?
    var tags: [String]?

    enum CodingKeys: String, CodingKey {
        case colorHex = "color_hex"
        case material, tags
    }
}

struct Product: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var retailer: String
    var retailerProductID: String?
    var title: String
    var variant: String?
    var category: String
    var description: String?
    var imageURL: String?
    var localImage: String?
    var sourceURL: String?
    var priceCents: Int
    var currency: String
    var dimensionsM: Dimensions?
    var dimensionKind: String?
    var evidence: [Evidence]?
    var retrievedAt: String?
    var additionalCosts: AdditionalCosts?
    var sourceType: String?
    var style: ProductStyle?
    var assetURL: String?

    enum CodingKeys: String, CodingKey {
        case id, retailer, title, variant, category, description, currency, evidence, style
        case retailerProductID = "retailer_product_id"
        case imageURL = "image_url"
        case localImage = "local_image"
        case sourceURL = "source_url"
        case priceCents = "price_cents"
        case dimensionsM = "dimensions_m"
        case dimensionKind = "dimension_kind"
        case retrievedAt = "retrieved_at"
        case additionalCosts = "additional_costs"
        case sourceType = "source_type"
        case assetURL = "asset_url"
    }

    /// Assembled or estimated sizes can be placed; package measurements cannot.
    var placeableDimensions: Dimensions? {
        switch dimensionKind {
        case nil, "assembled", "estimated": dimensionsM
        default: nil
        }
    }

    static func placed(id: String, title: String, category: String, retailer: String = "Owned",
                       imageURL: String? = nil, sourceURL: String? = nil, priceCents: Int = 0,
                       dimensions: Dimensions, sourceType: String = "owned") -> Product {
        Product(id: id, retailer: retailer, retailerProductID: nil, title: title, variant: nil,
                category: category, description: nil, imageURL: imageURL, localImage: nil,
                sourceURL: sourceURL, priceCents: priceCents, currency: "USD",
                dimensionsM: dimensions, dimensionKind: "estimated", evidence: nil,
                retrievedAt: nil, additionalCosts: nil, sourceType: sourceType, style: nil, assetURL: nil)
    }
}

enum TextureStatus: String, Codable, Sendable {
    case building, ready, failed, unavailable, unknown

    init(from decoder: Decoder) throws {
        self = TextureStatus(rawValue: (try? decoder.singleValueContainer().decode(String.self)) ?? "") ?? .unknown
    }
}

/// A photo put on an object (`texture` on a scene object). Decoding never fails, so a malformed
/// texture can't drop its object from the scene.
struct ObjectTexture: Codable, Hashable, Sendable {
    var imageURL: String?
    /// `print` (whole photo) or `tile` (repeating swatch).
    var mode: String?
    var status: TextureStatus

    enum CodingKeys: String, CodingKey {
        case mode, status
        case imageURL = "image_url"
    }

    init(imageURL: String?, mode: String? = "print", status: TextureStatus = .ready) {
        self.imageURL = imageURL
        self.mode = mode
        self.status = status
    }

    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        imageURL = try? c?.decode(String.self, forKey: .imageURL)
        mode = try? c?.decode(String.self, forKey: .mode)
        status = (try? c?.decode(TextureStatus.self, forKey: .status)) ?? .unknown
    }
}

struct SceneObject: Codable, Hashable, Identifiable, Sendable {
    var objectID: String
    var productID: String
    var category: String
    var positionM: [Double]
    var rotationYRad: Double
    var dimensionsM: Dimensions
    var colorHex: String?
    var assetURL: String?
    var proposalVersion: Int?
    var texture: ObjectTexture? = nil

    var id: String { objectID }
    var x: Double { positionM.count > 0 ? positionM[0] : 0 }
    var z: Double { positionM.count > 2 ? positionM[2] : 0 }

    enum CodingKeys: String, CodingKey {
        case category, texture
        case objectID = "object_id"
        case productID = "product_id"
        case positionM = "position_m"
        case rotationYRad = "rotation_y_rad"
        case dimensionsM = "dimensions_m"
        case colorHex = "color_hex"
        case assetURL = "asset_url"
        case proposalVersion = "proposal_version"
    }
}

struct Member: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var name: String
    var isPayer: Bool
    var hasLimit: Bool?
    /// Only present for the requesting member (`?member_id=`).
    var limitCents: Int?
    /// True when the member has a linked messaging handle.
    var connected: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, connected
        case isPayer = "is_payer"
        case hasLimit = "has_limit"
        case limitCents = "limit_cents"
    }

    init(id: String, name: String, isPayer: Bool, hasLimit: Bool? = nil, limitCents: Int? = nil, connected: Bool? = nil) {
        self.id = id; self.name = name; self.isPayer = isPayer
        self.hasLimit = hasLimit; self.limitCents = limitCents; self.connected = connected
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? id
        isPayer = (try? c.decode(Bool.self, forKey: .isPayer)) ?? false
        hasLimit = try? c.decode(Bool.self, forKey: .hasLimit)
        limitCents = try? c.decode(Int.self, forKey: .limitCents)
        connected = try? c.decode(Bool.self, forKey: .connected)
    }
}

struct Opening: Codable, Hashable, Sendable {
    var kind: String      // "door" | "window"
    var wall: String      // "back" | "front" | "left" | "right"
    var offsetM: Double
    var widthM: Double

    enum CodingKeys: String, CodingKey {
        case kind, wall
        case offsetM = "offset_m"
        case widthM = "width_m"
    }
}

struct Clearance: Codable, Hashable, Sendable {
    var label: String
    var xM: Double
    var zM: Double
    var widthM: Double
    var depthM: Double

    enum CodingKeys: String, CodingKey {
        case label
        case xM = "x_m"
        case zM = "z_m"
        case widthM = "width_m"
        case depthM = "depth_m"
    }
}

struct SavedInspirationImage: Codable, Hashable, Sendable, Identifiable {
    let id: String
    let url: String
}

struct Room: Codable, Hashable, Sendable {
    var widthM: Double
    var depthM: Double
    var heightM: Double
    var openings: [Opening]
    var clearances: [Clearance]
    var inspirationImageURL: String?
    var inspirationDescription = ""
    var inspirationImages: [SavedInspirationImage] = []

    enum CodingKeys: String, CodingKey {
        case openings, clearances
        case widthM = "width_m"
        case depthM = "depth_m"
        case heightM = "height_m"
        case inspirationImageURL = "inspiration_image_url"
        case inspirationDescription = "inspiration_description"
        case inspirationImages = "inspiration_images"
    }

    init(widthM: Double, depthM: Double, heightM: Double, openings: [Opening] = [], clearances: [Clearance] = [],
         inspirationImageURL: String? = nil) {
        self.widthM = widthM; self.depthM = depthM; self.heightM = heightM
        self.openings = openings; self.clearances = clearances; self.inspirationImageURL = inspirationImageURL
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        widthM = try c.decode(Double.self, forKey: .widthM)
        depthM = try c.decode(Double.self, forKey: .depthM)
        heightM = (try? c.decode(Double.self, forKey: .heightM)) ?? 2.5
        openings = (try? c.decode([Opening].self, forKey: .openings)) ?? []
        clearances = (try? c.decode([Clearance].self, forKey: .clearances)) ?? []
        inspirationImageURL = try? c.decode(String.self, forKey: .inspirationImageURL)
        inspirationDescription = (try? c.decode(String.self, forKey: .inspirationDescription)) ?? ""
        inspirationImages = (try? c.decode([SavedInspirationImage].self, forKey: .inspirationImages)) ?? []
    }
}

/// Body for `PUT /households/{hid}/room` (room object without the inspiration url).
struct RoomUpdate: Encodable, Sendable {
    var widthM: Double
    var depthM: Double
    var heightM: Double
    var openings: [Opening]
    var clearances: [Clearance]

    init(_ room: Room) {
        widthM = room.widthM; depthM = room.depthM; heightM = room.heightM
        openings = room.openings; clearances = room.clearances
    }

    enum CodingKeys: String, CodingKey {
        case openings, clearances
        case widthM = "width_m"
        case depthM = "depth_m"
        case heightM = "height_m"
    }
}

struct ProposalItem: Codable, Hashable, Sendable {
    var productID: String
    var category: String
    var priceCents: Int?
    var title: String?
    var sourceType: String?

    enum CodingKeys: String, CodingKey {
        case category, title
        case productID = "product_id"
        case priceCents = "price_cents"
        case sourceType = "source_type"
    }
}

enum ProposalStatus: String, Codable, Sendable {
    case draft, awaitingApproval = "awaiting_approval", approved, superseded, purchased, settled, unknown

    init(from decoder: Decoder) throws {
        self = ProposalStatus(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
    }

    var label: String {
        switch self {
        case .draft: "Draft"
        case .awaitingApproval: "Awaiting approval"
        case .approved: "Approved"
        case .superseded: "Superseded"
        case .purchased: "Purchased"
        case .settled: "Settled"
        case .unknown: "Unknown"
        }
    }

    var symbol: String {
        switch self {
        case .draft: "pencil.circle"
        case .awaitingApproval: "hourglass"
        case .approved: "checkmark.seal.fill"
        case .superseded: "arrow.uturn.backward.circle"
        case .purchased: "bag.fill"
        case .settled: "checkmark.circle.fill"
        case .unknown: "questionmark.circle"
        }
    }
}

struct Proposal: Codable, Hashable, Sendable {
    var version: Int
    var status: ProposalStatus
    var items: [ProposalItem]
    var knownTotalCents: Int
    var unknownCosts: [String]
    var shares: [String: Int]
    var approvals: [String: Bool]
    /// member_id -> reason (possibly empty). Not in docs/API.md.
    var objections: [String: String]
    var explanation: String?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case version, status, items, shares, approvals, objections, explanation
        case knownTotalCents = "known_total_cents"
        case unknownCosts = "unknown_costs"
        case createdAt = "created_at"
    }

    init(version: Int, status: ProposalStatus, items: [ProposalItem], knownTotalCents: Int, unknownCosts: [String],
         shares: [String: Int], approvals: [String: Bool], objections: [String: String] = [:],
         explanation: String? = nil, createdAt: String? = nil) {
        self.version = version; self.status = status; self.items = items; self.knownTotalCents = knownTotalCents
        self.unknownCosts = unknownCosts; self.shares = shares; self.approvals = approvals
        self.objections = objections; self.explanation = explanation; self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decode(Int.self, forKey: .version)
        status = (try? c.decode(ProposalStatus.self, forKey: .status)) ?? .unknown
        items = (try? c.decode([ProposalItem].self, forKey: .items)) ?? []
        knownTotalCents = (try? c.decode(Int.self, forKey: .knownTotalCents)) ?? 0
        unknownCosts = (try? c.decode([String].self, forKey: .unknownCosts)) ?? []
        shares = (try? c.decode([String: Int].self, forKey: .shares)) ?? [:]
        approvals = (try? c.decode([String: Bool].self, forKey: .approvals)) ?? [:]
        if let reasons = try? c.decode([String: String?].self, forKey: .objections) {
            objections = reasons.mapValues { $0 ?? "" }
        } else {
            objections = [:]
        }
        explanation = try? c.decode(String.self, forKey: .explanation)
        createdAt = try? c.decode(String.self, forKey: .createdAt)
    }
}

/// Backend shape: `{"kind", "objects": [ids], "message"}`; strings are accepted too.
struct ValidationIssue: Decodable, Hashable, Sendable {
    var message: String
    var objectIDs: [String]

    private enum CodingKeys: String, CodingKey {
        case message, code, detail, objects, kind
        case objectIDs = "object_ids"
        case objectID = "object_id"
    }

    init(from decoder: Decoder) throws {
        if let text = try? decoder.singleValueContainer().decode(String.self) {
            message = text; objectIDs = []; return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        message = (try? c.decode(String.self, forKey: .message))
            ?? (try? c.decode(String.self, forKey: .detail))
            ?? (try? c.decode(String.self, forKey: .code))
            ?? (try? c.decode(String.self, forKey: .kind)) ?? "Layout issue"
        var ids = (try? c.decode([String].self, forKey: .objectIDs)) ?? (try? c.decode([String].self, forKey: .objects)) ?? []
        if let one = try? c.decode(String.self, forKey: .objectID) { ids.append(one) }
        objectIDs = ids
    }

    init(message: String, objectIDs: [String] = []) {
        self.message = message; self.objectIDs = objectIDs
    }
}

struct SceneValidation: Decodable, Hashable, Sendable {
    var ok: Bool
    var issues: [ValidationIssue]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = (try? c.decode(Bool.self, forKey: .ok)) ?? true
        issues = (try? c.decode([ValidationIssue].self, forKey: .issues)) ?? []
    }

    private enum CodingKeys: String, CodingKey { case ok, issues }
}

struct SceneState: Decodable, Hashable, Sendable {
    var objects: [SceneObject]
    var validation: SceneValidation?

    init(objects: [SceneObject], validation: SceneValidation?) {
        self.objects = objects; self.validation = validation
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        objects = (try? c.decode([LossyElement<SceneObject>].self, forKey: .objects))?.compactMap(\.value) ?? []
        validation = try? c.decode(SceneValidation.self, forKey: .validation)
    }

    private enum CodingKeys: String, CodingKey { case objects, validation }
}

/// Decodes an array element without failing the whole array when one element is malformed.
struct LossyElement<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) throws { value = try? T(from: decoder) }
}

enum OperationState: String, Codable, Sendable, CaseIterable {
    case authorized, submitting, pending, confirmed, failed, unknown

    init(from decoder: Decoder) throws {
        self = OperationState(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
    }

    var label: String { rawValue.capitalized }

    var symbol: String {
        switch self {
        case .authorized: "checkmark.shield"
        case .submitting: "arrow.up.circle"
        case .pending: "clock"
        case .confirmed: "checkmark.circle.fill"
        case .failed: "xmark.octagon.fill"
        case .unknown: "questionmark.circle"
        }
    }

    var isTerminal: Bool { self == .confirmed || self == .failed }
}

struct FinancialOperation: Codable, Hashable, Sendable {
    var opKey: String
    var kind: String
    var fromMember: String?
    var toMember: String?
    var amountCents: Int
    var proposalVersion: Int?
    var state: OperationState
    var externalID: String?
    var error: String?
    var updatedAt: String?
    /// "mock" (in-process simulator) or "live" (Nessie sandbox). Not in docs/API.md.
    var simulator: String?

    var isMock: Bool { simulator == "mock" }

    enum CodingKeys: String, CodingKey {
        case kind, state, error, simulator
        case opKey = "op_key"
        case fromMember = "from_member"
        case toMember = "to_member"
        case amountCents = "amount_cents"
        case proposalVersion = "proposal_version"
        case externalID = "external_id"
        case updatedAt = "updated_at"
    }
}

struct Reimbursement: Codable, Hashable, Sendable {
    var liabilityID: String
    var fromMember: String
    var toMember: String
    var amountCents: Int
    var operation: FinancialOperation?

    enum CodingKeys: String, CodingKey {
        case operation
        case liabilityID = "liability_id"
        case fromMember = "from_member"
        case toMember = "to_member"
        case amountCents = "amount_cents"
    }
}

struct Finance: Codable, Hashable, Sendable {
    var payerID: String
    var purchase: FinancialOperation?
    var reimbursements: [Reimbursement]
    var settled: Bool
    /// "mock" or "live". Not in docs/API.md.
    var simulator: String?

    var isMock: Bool { simulator == "mock" }

    enum CodingKeys: String, CodingKey {
        case purchase, reimbursements, settled, simulator
        case payerID = "payer_id"
    }

    init(payerID: String, purchase: FinancialOperation? = nil, reimbursements: [Reimbursement] = [],
         settled: Bool = false, simulator: String? = nil) {
        self.payerID = payerID; self.purchase = purchase; self.reimbursements = reimbursements
        self.settled = settled; self.simulator = simulator
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        payerID = (try? c.decode(String.self, forKey: .payerID)) ?? ""
        purchase = try? c.decode(FinancialOperation.self, forKey: .purchase)
        reimbursements = (try? c.decode([LossyElement<Reimbursement>].self, forKey: .reimbursements))?.compactMap(\.value) ?? []
        settled = (try? c.decode(Bool.self, forKey: .settled)) ?? false
        simulator = try? c.decode(String.self, forKey: .simulator)
    }
}

struct ActivityEntry: Codable, Hashable, Sendable {
    var at: String
    var text: String
}

struct HouseholdState: Decodable, Hashable, Sendable {
    var householdID: String
    var stateVersion: Int
    var members: [Member]
    var room: Room
    var budgetCents: Int?
    var proposal: Proposal?
    var scene: SceneState
    var finance: Finance
    var activity: [ActivityEntry]
    /// e.g. "verified". Not in docs/API.md.
    var catalogMode: String?

    enum CodingKeys: String, CodingKey {
        case members, room, proposal, scene, finance, activity
        case householdID = "household_id"
        case stateVersion = "state_version"
        case budgetCents = "budget_cents"
        case catalogMode = "catalog_mode"
    }

    init(householdID: String, stateVersion: Int, members: [Member], room: Room, budgetCents: Int?, proposal: Proposal?,
         scene: SceneState, finance: Finance, activity: [ActivityEntry], catalogMode: String? = nil) {
        self.householdID = householdID; self.stateVersion = stateVersion; self.members = members; self.room = room
        self.budgetCents = budgetCents; self.proposal = proposal; self.scene = scene; self.finance = finance
        self.activity = activity; self.catalogMode = catalogMode
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        householdID = (try? c.decode(String.self, forKey: .householdID)) ?? "demo"
        stateVersion = (try? c.decode(Int.self, forKey: .stateVersion)) ?? 0
        members = (try? c.decode([LossyElement<Member>].self, forKey: .members))?.compactMap(\.value) ?? []
        room = try c.decode(Room.self, forKey: .room)
        budgetCents = try? c.decode(Int.self, forKey: .budgetCents)
        // A malformed proposal must surface rather than silently look like "no proposal".
        proposal = try c.decodeIfPresent(Proposal.self, forKey: .proposal)
        scene = (try? c.decode(SceneState.self, forKey: .scene)) ?? SceneState(objects: [], validation: nil)
        finance = (try? c.decode(Finance.self, forKey: .finance)) ?? Finance(payerID: "")
        activity = (try? c.decode([LossyElement<ActivityEntry>].self, forKey: .activity))?.compactMap(\.value) ?? []
        catalogMode = try? c.decode(String.self, forKey: .catalogMode)
    }

    func member(_ id: String?) -> Member? { members.first { $0.id == id } }
    func name(of id: String?) -> String { member(id)?.name ?? id ?? "—" }
}

// MARK: - Requests / responses

struct MemberBody: Encodable, Sendable {
    let memberID: String
    enum CodingKeys: String, CodingKey { case memberID = "member_id" }
}

struct ObjectBody: Encodable, Sendable {
    let memberID: String
    let reason: String
    enum CodingKeys: String, CodingKey { case reason; case memberID = "member_id" }
}

struct ChatBody: Encodable, Sendable {
    let memberID: String
    let text: String
    var pickIds: [String] = []
    var mode: String?
    var skipCategories: [String] = []
    enum CodingKeys: String, CodingKey {
        case text
        case memberID = "member_id"
        case pickIds = "pick_ids"
        case mode
        case skipCategories = "skip_categories"
    }
}

struct ChatReply: Decodable, Sendable {
    let reply: String
}

struct LimitBody: Encodable, Sendable {
    let limitCents: Int
    enum CodingKeys: String, CodingKey { case limitCents = "limit_cents" }
}

struct BudgetBody: Encodable, Sendable {
    let budgetCents: Int
    enum CodingKeys: String, CodingKey { case budgetCents = "budget_cents" }
}

struct GroupPerson: Identifiable, Codable, Hashable, Sendable {
    var id: String
    var name: String
    var photoFilename: String?
    /// True when they were invited locally and are not yet on the backend roster.
    var invited: Bool
}

struct InspirationShot: Identifiable, Codable, Hashable, Sendable {
    var id: UUID
    var filename: String
    var addedAt: Date
}

struct CandidateGroup: Identifiable, Codable, Hashable, Sendable {
    var id: UUID
    var name: String
    var category: String?
    var productIDs: [String]
    var showingProductID: String?

    var objectID: String { "local-group-\(id.uuidString)" }
}

struct OwnedItem: Identifiable, Codable, Hashable, Sendable {
    var id: UUID
    var householdID: String
    var name: String
    var category: String
    var link: String?
    var imageFilename: String?
    var widthM: Double?
    var depthM: Double?
    var heightM: Double?
    var addedAt: Date
}

struct PurchaseAuthorizeBody: Encodable, Sendable {
    let memberID: String
    let proposalVersion: Int
    enum CodingKeys: String, CodingKey {
        case memberID = "member_id"
        case proposalVersion = "proposal_version"
    }
}

struct ObjectPoseBody: Encodable, Sendable {
    let positionM: [Double]
    let rotationYRad: Double
    enum CodingKeys: String, CodingKey {
        case positionM = "position_m"
        case rotationYRad = "rotation_y_rad"
    }
}

/// `GET /products` shape is unspecified; accept a bare array or `{"products": [...]}`.
struct ProductList: Decodable, Sendable {
    let products: [Product]
    private enum CodingKeys: String, CodingKey { case products }
    init(from decoder: Decoder) throws {
        if let array = try? decoder.singleValueContainer().decode([LossyElement<Product>].self) {
            products = array.compactMap(\.value)
        } else {
            products = try decoder.container(keyedBy: CodingKeys.self)
                .decode([LossyElement<Product>].self, forKey: .products).compactMap(\.value)
        }
    }
}

/// `{"state_version": n}` payload of the `state` server-sent event.
struct StateEventPayload: Decodable, Sendable {
    let stateVersion: Int?
    enum CodingKeys: String, CodingKey { case stateVersion = "state_version" }
}

/// Health response: only `status` is relied upon.
struct HealthResponse: Decodable, Sendable {
    let status: String?
}

struct RealizeRequest: Encodable, Sendable {
    var id: String
    var title: String
    var category: String
    var imageURL: String?
    var sourceURL: String?
    var retailer: String?
    var description: String?
    var priceCents: Int
    var dimensionsM: Dimensions

    enum CodingKeys: String, CodingKey {
        case id, title, category, retailer, description
        case imageURL = "image_url"
        case sourceURL = "source_url"
        case priceCents = "price_cents"
        case dimensionsM = "dimensions_m"
    }
}

struct RealizeStatus: Decodable, Sendable {
    var id: String
    var status: String
    var assetURL: String?
    var colorHex: String?
    var dimensionsM: Dimensions?
    var dimensionKind: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case assetURL = "asset_url"
        case colorHex = "color_hex"
        case dimensionsM = "dimensions_m"
        case dimensionKind = "dimension_kind"
    }
}

extension String {
    var categoryLabel: String {
        switch self {
        case "coffee_table": "Coffee table"
        case "tv": "TV"
        default: replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    var categorySymbol: String {
        switch self {
        case "sofa": "sofa.fill"
        case "coffee_table", "table": "table.furniture.fill"
        case "tv": "tv.fill"
        case "rug": "square.dashed"
        case "bed": "bed.double.fill"
        case "nightstand": "lamp.table.fill"
        case "dresser": "cabinet.fill"
        case "desk": "studentdesk"
        case "chair": "chair.fill"
        case "lamp": "lamp.table.fill"
        default: "shippingbox.fill"
        }
    }
}
