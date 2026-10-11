import Observation
import SwiftUI
import UIKit

enum ConnectionStatus: Equatable {
    case connecting
    case live            // SSE stream open
    case polling         // SSE failed; polling /state every 2 s
    case offline(String) // backend unreachable

    var label: String {
        switch self {
        case .connecting: "Connecting…"
        case .live: "Live"
        case .polling: "Polling"
        case .offline: "Offline"
        }
    }

    var symbol: String {
        switch self {
        case .connecting: "antenna.radiowaves.left.and.right"
        case .live: "dot.radiowaves.left.and.right"
        case .polling: "arrow.triangle.2.circlepath"
        case .offline: "wifi.slash"
        }
    }
}

enum DataSource { case fixture, live }

struct LocalPose: Equatable {
    var x: Double
    var z: Double
    var rotation: Double
}

private struct LocalSceneExtras: Codable {
    var objects: [SceneObject] = []
    var products: [Product] = []
    var applied: [String: String] = [:]
    var groups: [CandidateGroup] = []

    enum CodingKeys: String, CodingKey { case objects, products, applied, groups }

    init(objects: [SceneObject] = [], products: [Product] = [], applied: [String: String] = [:],
         groups: [CandidateGroup] = []) {
        self.objects = objects; self.products = products; self.applied = applied; self.groups = groups
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        objects = try c.decodeIfPresent([SceneObject].self, forKey: .objects) ?? []
        products = try c.decodeIfPresent([Product].self, forKey: .products) ?? []
        applied = try c.decodeIfPresent([String: String].self, forKey: .applied) ?? [:]
        groups = try c.decodeIfPresent([CandidateGroup].self, forKey: .groups) ?? []
    }
}

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let author: String
    let text: String
    let fromMe: Bool
    var isError = false
}

/// What a room scope looked like when the user switched away from it.
private struct ScopeSnapshot {
    var state: HouseholdState
    var chat: [ChatMessage]
    var source: DataSource
}

@Observable
@MainActor
final class AppModel {
    static let baseURLKey = "backendBaseURL"
    static let patchMovesKey = "patchMovesToBackend"
    static let actingMemberKey = "actingMemberID"
    static let householdKey = "currentHouseholdID"
    static let defaultBaseURL = "http://127.0.0.1:8000"
    static let defaultHouseholdID = "demo"
    static let apartmentID = "demo"
    private(set) var account: AccountUser? = AccountSessionStore.load()?.session.user
    private(set) var currentGroupID: String? = UserDefaults.standard.string(forKey: "backendGroupID")
    var activeApartmentID: String { currentGroupID ?? Self.apartmentID }
    static let ownedItemsKey = "ownedItems"
    static let extrasKey = "localSceneExtras"
    static let rosterKey = "groupRoster"
    static let memberPhotosKey = "memberPhotos"
    static let inviteKey = "groupInviteCode"
    static let inspirationShotsKey = "inspirationShots"

    /// Room scope the panels, 3D room and AR show. Every `/households/{hid}` call targets it.
    private(set) var currentHouseholdID: String
    var state: HouseholdState
    var products: [Product]
    var source: DataSource = .fixture
    var connection: ConnectionStatus = .connecting
    private(set) var actingMemberID: String
    var selectedObjectID: String?
    /// RealityKit misbehaves with a second ARView alive, so the room view is torn down while AR is on screen.
    var arPresented = false
    var detailProductID: String?
    /// Local, unsynced moves keyed by object_id.
    var localPoses: [String: LocalPose] = [:]
    /// Local "Preview" swaps: object_id -> alternative product id. Never sent to the server.
    var previews: [String: String] = [:]
    var errorMessage: String?
    var chat: [ChatMessage] = []
    var busy: Set<String> = []
    var lastUpdated: Date?
    var inspirationPreview: UIImage?
    var cameraResetToken = 0
    var ownedItems: [OwnedItem] = []
    var inspirationQuery = ""
    var inspirationResults: [Product] = []
    var candidateGroups: [CandidateGroup] = []
    var inspirationCategory: String?
    var pendingInspirationQuery: String?
    var inspirationPicks: [String] { candidateGroups.flatMap(\.productIDs) }
    private var inspirationSearchID = 0
    var extraObjects: [SceneObject] = []
    var extraProducts: [Product] = []
    /// Preview the user committed as the item they want in that slot.
    var appliedPreviews: [String: String] = [:]
    var extraPeople: [GroupPerson] = []
    var memberPhotos: [String: String] = [:]
    var inviteCode: String = ""
    var inspirationShots: [InspirationShot] = []

    /// Set when the current scope 404s on a reachable backend and bundled fixtures are shown instead.
    var scopeNotice: String?
    /// `GET /apartments/demo`; `nil` until it succeeds (the bundled plan is used meanwhile).
    private(set) var fetchedApartment: Apartment?
    /// Fallback while `/apartments` is missing: summaries built from other scopes' live `/state`.
    private var liveSummaries: [String: RoomSummary] = [:]

    private(set) var client: BackendClient?
    private var connectionTask: Task<Void, Never>?
    private var scopeCache: [String: ScopeSnapshot] = [:]
    /// The current state is a stand-in shown while a never-visited scope loads.
    private var stateIsPlaceholder = false
    private var reachedBackend = false
    private var productsFromFixture = true
    private var apartmentLoading = false
    @ObservationIgnored private var apartmentGeneration = 0
    private var extrasByHousehold: [String: LocalSceneExtras] = [:]

    init() {
        let fixtures = Self.loadFixtures()
        let householdID = UserDefaults.standard.string(forKey: Self.householdKey) ?? Self.defaultHouseholdID
        currentHouseholdID = householdID
        state = householdID.hasPrefix("grp_") ? Self.blankState(forScope: householdID, apartment: nil) : (householdID == Self.defaultHouseholdID ? fixtures.state : Self.fixtureState(forScope: householdID))
        products = fixtures.products
        actingMemberID = UserDefaults.standard.string(forKey: Self.actingMemberKey) ?? "emily"
        ownedItems = Self.loadOwnedItems()
        extrasByHousehold = Self.loadExtras()
        restoreExtras(for: householdID)
        extraPeople = currentGroupID == nil ? (Self.loadJSON(Self.rosterKey, as: [GroupPerson].self) ?? []) : []
        memberPhotos = Self.loadJSON(Self.memberPhotosKey, as: [String: String].self) ?? [:]
        inspirationShots = Self.loadJSON(Self.inspirationShotsKey, as: [InspirationShot].self) ?? []
        inviteCode = UserDefaults.standard.string(forKey: Self.inviteKey) ?? Self.makeInviteCode()
        if UserDefaults.standard.string(forKey: Self.inviteKey) == nil {
            UserDefaults.standard.set(inviteCode, forKey: Self.inviteKey)
        }
    }

    // MARK: Derived state

    var isOfflineDemo: Bool { source == .fixture }
    var baseURL: URL? { client?.baseURL }
    var actingMember: Member? { state.member(actingMemberID) }
    var actingMemberName: String { actingMember?.name ?? apartment?.name(of: actingMemberID) ?? actingMemberID }

    // MARK: Apartment and room scopes

    var apartmentIsFixture: Bool { fetchedApartment == nil }

    /// The live plan when the backend serves it; otherwise the bundled plan with summaries
    /// recomputed from every scope snapshot this app has seen.
    var apartment: Apartment? {
        if let fetchedApartment { return fetchedApartment }
        guard currentGroupID == nil, let base = Self.fixtureApartment else { return nil }
        var summaries = scopeCache.mapValues { RoomSummary($0.state) }
        summaries.merge(liveSummaries) { _, live in live }
        if !stateIsPlaceholder { summaries[currentHouseholdID] = RoomSummary(state) }
        return base.overlaying(summaries)
    }

    var currentRoom: ApartmentRoom? { apartment?.room(forHousehold: currentHouseholdID) }

    var currentRoomName: String {
        currentRoom?.name ?? (currentHouseholdID == Self.defaultHouseholdID ? "Living room" : "Room")
    }

    /// Bedrooms: one member who pays 100%, approves alone and has no reimbursements.
    var isPrivateScope: Bool { currentRoom.map { !$0.shared } ?? false }

    var scopeOwnerID: String? { isPrivateScope ? (currentRoom?.ownerID ?? state.members.first?.id) : nil }

    /// False when acting as someone who isn't a member of the current scope (their actions would 4xx).
    var actingMemberInScope: Bool { state.members.isEmpty || state.members.contains { $0.id == actingMemberID } }

    var notInScopeNote: String? {
        guard !actingMemberInScope else { return nil }
        if let owner = scopeOwnerID { return "Only \(state.name(of: owner)) approves this bedroom" }
        return "\(actingMemberName) isn't a member of \(currentRoomName.lowercased())"
    }

    var chatSuggestion: String {
        isPrivateScope
            ? "Furnish my bedroom for $1,000: a bed, nightstand, dresser and desk. Keep the door clear."
            : "Furnish our \(currentRoomName.lowercased()) for $1,500. Light, cozy, and keep the door clear."
    }

    /// Everyone you can act as: all roommates, even inside a bedroom whose scope only lists its owner.
    var actingCandidates: [(id: String, name: String)] {
        if let account { return [(account.id, account.name)] }
        if let members = apartment?.members, !members.isEmpty { return members.map { ($0.id, $0.name) } }
        return state.members.map { ($0.id, $0.name) }
    }

    func acceptAccount(_ session: AccountSession) throws {
        guard let client else { throw BackendError.invalidBaseURL("No backend configured") }
        try AccountSessionStore.save(session, backend: client.baseURL)
        account = session.user
        connectionTask?.cancel()
        currentGroupID = nil
        UserDefaults.standard.removeObject(forKey: "backendGroupID")
        currentHouseholdID = Self.defaultHouseholdID
        self.client?.householdID = currentHouseholdID
        UserDefaults.standard.set(currentHouseholdID, forKey: Self.householdKey)
        state = Self.blankState(forScope: currentHouseholdID, apartment: nil)
        source = .fixture
        scopeCache = [:]; fetchedApartment = nil; extraPeople = []
        setActingMember(session.user.id)
    }

    func useGroup(id: String, householdID: String, code: String) async {
        currentGroupID = id
        UserDefaults.standard.set(id, forKey: "backendGroupID")
        fetchedApartment = nil; scopeCache = [:]; extraPeople = []
        if let account { setActingMember(account.id) }
        switchScope(to: householdID)
        adoptInviteCode(code)
        if let client {
            try? await refresh(client)
            if let plan = try? await client.apartment(id: id) { fetchedApartment = plan }
        }
    }

    func signOut() async {
        if let client { try? await client.logout() }
        AccountSessionStore.clear()
        account = nil; currentGroupID = nil; fetchedApartment = nil; scopeCache = [:]
        UserDefaults.standard.removeObject(forKey: "backendGroupID")
        setActingMember("emily")
        switchScope(to: Self.defaultHouseholdID)
        state = Self.loadFixtures().state
        source = .fixture
        restartConnection()
    }

    func selectRoom(_ roomID: String) {
        guard let room = apartment?.rooms.first(where: { $0.id == roomID }), let householdID = room.householdID else { return }
        switchScope(to: householdID)
    }

    func switchScope(to householdID: String) {
        guard householdID != currentHouseholdID else { return }
        if !stateIsPlaceholder {
            scopeCache[currentHouseholdID] = ScopeSnapshot(state: state, chat: chat, source: source)
            liveSummaries[currentHouseholdID] = nil
        }
        persistCurrentExtras()
        currentHouseholdID = householdID
        UserDefaults.standard.set(householdID, forKey: Self.householdKey)
        selectedObjectID = nil
        detailProductID = nil
        localPoses = [:]
        previews = [:]
        errorMessage = nil
        scopeNotice = nil
        stateIsPlaceholder = false
        if let cached = scopeCache[householdID] {
            state = cached.state; chat = cached.chat; source = cached.source
        } else if !reachedBackend && currentGroupID == nil {
            state = Self.fixtureState(forScope: householdID); chat = []; source = .fixture
        } else {
            state = Self.blankState(forScope: householdID, apartment: apartment); chat = []
            stateIsPlaceholder = true
        }
        restoreExtras(for: householdID)
        client?.householdID = householdID
        restartConnection()
    }

    func refreshSetupState() async {
        scopeCache = [:]
        await refreshApartment(force: true)
        if let client { try? await refresh(client) }
    }

    /// `force` skips the in-flight check (after an import); an older fetch that finishes later is discarded.
    func refreshApartment(force: Bool = false) async {
        guard reachedBackend, let client, force || !apartmentLoading else { return }
        apartmentGeneration += 1
        let generation = apartmentGeneration
        apartmentLoading = true
        defer { if generation == apartmentGeneration { apartmentLoading = false } }
        do {
            let fetched = try await client.apartment(id: activeApartmentID)
            guard generation == apartmentGeneration else { return }
            fetchedApartment = fetched.rooms.isEmpty ? nil : fetched
            if fetchedApartment != nil { return }
        } catch BackendError.http(status: 404, _), BackendError.decoding {
            guard generation == apartmentGeneration else { return }
            fetchedApartment = nil
        } catch {
            return // Unreachable: keep the last plan we had.
        }
        // No apartment endpoint: summarize each scope the backend does serve from its own snapshot.
        for hid in (Self.fixtureApartment?.furnishableRooms ?? []).compactMap(\.householdID) where hid != currentHouseholdID {
            var scoped = client
            scoped.householdID = hid
            if let snapshot = try? await scoped.state(memberID: nil) { liveSummaries[hid] = RoomSummary(snapshot) }
        }
    }

    // MARK: Floor-plan import

    enum PlanImportOutcome {
        case imported(warnings: [String])
        /// 422 because no sizes are printed: ask for the overall width and retry.
        case needsWidth(String)
        case failed(String)
    }

    /// Server-side actions that don't depend on the current scope's data (plan import) need a live backend.
    var backendReachable: Bool {
        if case .offline = connection { return false }
        return reachedBackend && client != nil
    }

    func importFloorplan(_ image: UploadImage, widthM: Double?) async -> PlanImportOutcome {
        guard let client, backendReachable else { return .failed("The backend isn't reachable") }
        guard !busy.contains("floorplan") else { return .failed("An import is already running") }
        busy.insert("floorplan")
        defer { busy.remove("floorplan") }
        do {
            let result = try await client.importFloorplan(apartmentID: activeApartmentID, image: image, widthM: widthM)
            if let imported = result.apartment, !imported.rooms.isEmpty { fetchedApartment = imported }
            await afterPlanChange()
            return .imported(warnings: result.warnings)
        } catch BackendError.http(status: 422, let message) where widthM == nil && Self.asksForWidth(message) {
            return .needsWidth(message)
        } catch {
            return .failed(Self.message(error))
        }
    }

    /// `DELETE /apartments/demo/floorplan`. Returns an error message, or nil on success.
    func restoreBuiltInPlan() async -> String? {
        guard let client, backendReachable else { return "The backend isn't reachable" }
        busy.insert("floorplan")
        defer { busy.remove("floorplan") }
        do {
            try await client.restoreFloorplan(apartmentID: activeApartmentID)
            await afterPlanChange()
            return nil
        } catch {
            return Self.message(error)
        }
    }

    private static func asksForWidth(_ message: String) -> Bool {
        message.localizedCaseInsensitiveContains("width_m") || message.localizedCaseInsensitiveContains("no room sizes")
    }

    /// Bedroom scopes are re-seeded with new sizes and proposals, so every snapshot is stale.
    private func afterPlanChange() async {
        scopeCache = [:]
        liveSummaries = [:]
        await refreshApartment(force: true)
        if let fetchedApartment, fetchedApartment.room(forHousehold: currentHouseholdID) == nil {
            switchScope(to: Self.defaultHouseholdID)
        } else if let client {
            localPoses = [:]
            try? await refresh(client)
        }
    }

    // MARK: Object textures

    /// `mode` is `print` or `tile`. Returns true on success.
    func putTexture(objectID: String, image: UploadImage, mode: String, tileM: Double?) async -> Bool {
        await perform("texture-\(objectID)", offline: { errorMessage = "Offline demo: photos on furniture need the backend" }) {
            try await $0.putTexture(objectID: objectID, image: image, mode: mode, tileM: tileM)
        }
    }

    func removeTexture(objectID: String) async {
        await perform("texture-\(objectID)", offline: {}) { try await $0.deleteTexture(objectID: objectID) }
    }

    var displayedObjects: [SceneObject] {
        (state.scene.objects + extraObjects).map { original in
            var object = original
            let swapID = previews[object.objectID] ?? appliedPreviews[object.objectID]
            if let productID = swapID, let alt = product(productID), let dims = alt.placeableDimensions {
                object.productID = alt.id
                object.dimensionsM = dims
                object.colorHex = alt.style?.colorHex ?? object.colorHex
                object.assetURL = alt.assetURL
                if object.category == "rug", let photo = alt.imageURL ?? alt.localImage {
                    object.texture = ObjectTexture(imageURL: photo)
                }
            }
            if let pose = localPoses[object.objectID] {
                object.positionM = [pose.x, 0, pose.z]
                object.rotationYRad = pose.rotation
            }
            return object
        }
    }

    var layoutReport: LayoutReport {
        LayoutValidation.validate(objects: displayedObjects, room: state.room, name: displayName)
    }

    var hasLocalEdits: Bool { !localPoses.isEmpty || !previews.isEmpty }

    func product(_ id: String?) -> Product? {
        products.first { $0.id == id } ?? extraProducts.first { $0.id == id }
    }

    func displayName(_ object: SceneObject) -> String {
        product(object.productID)?.title
            ?? state.proposal?.items.first { $0.productID == object.productID }?.title
            ?? object.category.categoryLabel
    }

    var selectedObject: SceneObject? { displayedObjects.first { $0.objectID == selectedObjectID } }

    /// Product shown in the detail panel: the selected object's (possibly previewed) product,
    /// otherwise whatever was tapped in the proposal list.
    var detailProduct: Product? {
        if let object = selectedObject { return product(object.productID) }
        return product(detailProductID)
    }

    var detailOriginalProductID: String? {
        guard let id = selectedObjectID else { return detailProductID }
        return state.scene.objects.first { $0.objectID == id }?.productID
    }

    /// Backend-served copy first (`/product_images/...`), retailer URL as fallback.
    func imageURLs(for product: Product) -> [URL] {
        if let raw = product.imageURL, raw.hasPrefix("file:"), let url = URL(string: raw) {
            return [url]
        }
        return [client?.resolve(product.localImage), client?.resolve(product.imageURL)].compactMap { $0 }
    }

    func alternatives(for product: Product) -> [Product] {
        products.filter { $0.category == product.category && $0.id != product.id }
    }

    var currentOwnedItems: [OwnedItem] {
        ownedItems.filter { $0.householdID == currentHouseholdID }
    }

    var groupRoster: [GroupPerson] {
        let base = (apartment?.members ?? state.members.map { ApartmentMember(id: $0.id, name: $0.name) })
            .map { GroupPerson(id: $0.id, name: $0.name, photoFilename: memberPhotos[$0.id], invited: false) }
        let seen = Set(base.map(\.id))
        return base + extraPeople.filter { !seen.contains($0.id) }
    }

    func adoptInviteCode(_ code: String) {
        let trimmed = code.filter(\.isNumber)
        guard trimmed.count == 6 else { return }
        inviteCode = trimmed
        UserDefaults.standard.set(trimmed, forKey: Self.inviteKey)
    }

    var inviteMessage: String {
        "Join our group in FurniShare. Code: \(inviteCode)"
    }

    func personPhotoURL(_ person: GroupPerson) -> URL? {
        photoURL(person.photoFilename ?? memberPhotos[person.id])
    }

    func addPerson(name: String, image: UIImage?) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        extraPeople.insert(GroupPerson(id: "local-\(UUID().uuidString)", name: trimmed,
                                       photoFilename: image.flatMap(Self.writeOwnedImage), invited: true), at: 0)
        persistRoster()
    }

    func removePerson(_ id: String) {
        extraPeople.removeAll { $0.id == id }
        persistRoster()
    }

    func setPersonPhoto(_ id: String, image: UIImage) {
        guard let filename = Self.writeOwnedImage(image) else { return }
        if let index = extraPeople.firstIndex(where: { $0.id == id }) {
            extraPeople[index].photoFilename = filename
        } else {
            memberPhotos[id] = filename
        }
        persistRoster()
    }

    func addInspirationPhoto(_ image: UIImage) {
        guard let filename = Self.writeOwnedImage(image) else { return }
        inspirationShots.insert(InspirationShot(id: UUID(), filename: filename, addedAt: Date()), at: 0)
        persistJSON(inspirationShots, key: Self.inspirationShotsKey)
        Task { await uploadInspiration(image) }
    }

    func removeInspirationShot(_ id: UUID) {
        if let shot = inspirationShots.first(where: { $0.id == id }) {
            try? FileManager.default.removeItem(at: Self.ownedImagesDirectory.appendingPathComponent(shot.filename))
        }
        inspirationShots.removeAll { $0.id == id }
        persistJSON(inspirationShots, key: Self.inspirationShotsKey)
    }

    func inspirationURL(_ shot: InspirationShot) -> URL {
        Self.ownedImagesDirectory.appendingPathComponent(shot.filename)
    }

    func ownedImageURL(_ item: OwnedItem) -> URL? {
        guard let name = item.imageFilename else { return nil }
        return Self.ownedImagesDirectory.appendingPathComponent(name)
    }

    func addOwnedItem(name: String, category: String, link: String?, image: UIImage?,
                      widthM: Double, depthM: Double, heightM: Double) {
        let filename = image.flatMap(Self.writeOwnedImage)
        let item = OwnedItem(id: UUID(), householdID: currentHouseholdID, name: name, category: category,
                             link: link, imageFilename: filename, widthM: widthM, depthM: depthM, heightM: heightM,
                             addedAt: Date())
        ownedItems.insert(item, at: 0)
        persistOwnedItems()
        let product = Product.placed(
            id: "owned-\(item.id.uuidString)", title: name, category: category,
            imageURL: ownedImageURL(item)?.absoluteString, sourceURL: link,
            dimensions: Dimensions(width: widthM, depth: depthM, height: heightM))
        remember(product)
        placeInRoom(product, imageURL: ownedImageURL(item)?.absoluteString, photo: image)
    }

    func removeOwnedItem(_ id: UUID) {
        if let item = ownedItems.first(where: { $0.id == id }), let name = item.imageFilename {
            try? FileManager.default.removeItem(at: Self.ownedImagesDirectory.appendingPathComponent(name))
        }
        let productID = "owned-\(id.uuidString)"
        extraObjects.removeAll { $0.productID == productID }
        extraProducts.removeAll { $0.id == productID }
        ownedItems.removeAll { $0.id == id }
        persistOwnedItems()
        persistCurrentExtras()
    }

    func remember(_ product: Product) {
        if products.contains(where: { $0.id == product.id }) { return }
        extraProducts.removeAll { $0.id == product.id }
        extraProducts.insert(product, at: 0)
        if extraProducts.count > 80 { extraProducts = Array(extraProducts.prefix(80)) }
        persistCurrentExtras()
    }

    func placeInRoom(_ product: Product, imageURL: String? = nil, photo: UIImage? = nil) {
        guard let dims = product.placeableDimensions else { return }
        remember(product)
        let objectID = "local-\(product.id)"
        if extraObjects.contains(where: { $0.objectID == objectID }) {
            select(objectID)
            return
        }
        let room = state.room
        let existing = displayedObjects.filter { $0.category == product.category }.count
        let x = Self.clamped(-room.widthM / 2 + dims.width / 2 + 0.25 + Double(existing) * 0.4,
                             lo: -room.widthM / 2 + dims.width / 2, hi: room.widthM / 2 - dims.width / 2)
        let z = Self.clamped(-room.depthM / 2 + dims.depth / 2 + 0.3,
                             lo: -room.depthM / 2 + dims.depth / 2, hi: room.depthM / 2 - dims.depth / 2)
        let photoPath = imageURL ?? product.imageURL ?? product.localImage
        extraObjects.append(SceneObject(
            objectID: objectID, productID: product.id, category: product.category,
            positionM: [x, 0, z], rotationYRad: 0, dimensionsM: dims,
            colorHex: product.style?.colorHex, assetURL: product.assetURL, proposalVersion: nil,
            texture: product.category == "rug" ? photoPath.map { ObjectTexture(imageURL: $0) } : nil))
        select(objectID)
        persistCurrentExtras()
        realizeInBackground(product, image: photo)
    }

    func displayedProduct(for object: SceneObject) -> Product? {
        product(previews[object.objectID] ?? appliedPreviews[object.objectID] ?? object.productID)
    }

    func applyPreview(objectID: String) {
        guard let productID = previews[objectID] else { return }
        appliedPreviews[objectID] = productID
        previews[objectID] = nil
        persistCurrentExtras()
        if let product = product(productID) { realizeInBackground(product) }
    }

    private func realizeInBackground(_ product: Product, image: UIImage? = nil) {
        guard source == .live, client != nil, product.placeableDimensions != nil else { return }
        Task { await realize(product, image: image) }
    }

    private func realize(_ product: Product, image: UIImage? = nil) async {
        guard let client else { return }
        var upload: UploadImage?
        if let image {
            upload = await UploadImage.prepare(image, maxLongSide: 1600, name: "realize")
        } else if let raw = product.imageURL, raw.hasPrefix("file:"), let url = URL(string: raw),
                  let data = try? Data(contentsOf: url) {
            upload = UploadImage(data: data, mimeType: "image/jpeg", filename: "realize.jpg")
        }
        do {
            var status = try await client.realizeProduct(product, image: upload)
            applyRealized(status, productID: product.id)
            var spins = 0
            while status.status == "building", spins < 40 {
                try await Task.sleep(for: .seconds(3))
                status = try await client.realizeStatus(product.id)
                applyRealized(status, productID: product.id)
                spins += 1
            }
        } catch {}
    }

    private func applyRealized(_ status: RealizeStatus, productID: String) {
        if let dims = status.dimensionsM {
            if let index = extraProducts.firstIndex(where: { $0.id == productID }) {
                extraProducts[index].dimensionsM = dims
                extraProducts[index].dimensionKind = status.dimensionKind ?? extraProducts[index].dimensionKind
            }
            for i in extraObjects.indices where extraObjects[i].productID == productID {
                extraObjects[i].dimensionsM = dims
            }
        }
        if let color = status.colorHex {
            if let index = extraProducts.firstIndex(where: { $0.id == productID }) {
                extraProducts[index].style = ProductStyle(colorHex: color, material: extraProducts[index].style?.material,
                                                          tags: extraProducts[index].style?.tags)
            }
            for i in extraObjects.indices where extraObjects[i].productID == productID {
                extraObjects[i].colorHex = color
            }
        }
        if let asset = status.assetURL {
            if let index = extraProducts.firstIndex(where: { $0.id == productID }) {
                extraProducts[index].assetURL = asset
            }
            if let index = products.firstIndex(where: { $0.id == productID }) {
                products[index].assetURL = asset
            }
            for i in extraObjects.indices where extraObjects[i].productID == productID {
                extraObjects[i].assetURL = asset
            }
        }
        persistCurrentExtras()
    }

    private static func clamped(_ value: Double, lo: Double, hi: Double) -> Double {
        guard lo <= hi else { return (lo + hi) / 2 }
        return min(max(value, lo), hi)
    }

    func searchInspiration(_ raw: String) {
        let query = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        inspirationQuery = query
        inspirationSearchID += 1
        let searchID = inspirationSearchID
        guard !query.isEmpty else {
            inspirationResults = []
            return
        }
        inspirationCategory = Self.category(from: query)
        let local = Self.rank(products: products + extraProducts, query: query, category: inspirationCategory)
        inspirationResults = local
        if inspirationCategory == nil {
            inspirationCategory = local.first.flatMap { Self.category(from: $0.title) } ?? local.first?.category
        }
        guard let client, source == .live else { return }
        busy.insert("inspiration-search")
        Task {
            defer { if searchID == inspirationSearchID { busy.remove("inspiration-search") } }
            do {
                let remote = try await client.searchProducts(query)
                guard searchID == inspirationSearchID else { return }
                var seen = Set<String>()
                var merged: [Product] = []
                for product in remote + local {
                    let title = product.title.lowercased()
                    if seen.contains(product.id) || seen.contains(title) { continue }
                    seen.insert(product.id)
                    seen.insert(title)
                    merged.append(product)
                }
                if let inferred = Self.category(from: query) {
                    inspirationCategory = inferred
                    merged = merged.filter { $0.category == inferred || Self.category(from: $0.title) == inferred }
                } else if inspirationCategory == nil {
                    inspirationCategory = merged.first.flatMap { Self.category(from: $0.title) } ?? merged.first?.category
                }
                merged.forEach(remember)
                inspirationResults = merged
            } catch {
                guard searchID == inspirationSearchID else { return }
                errorMessage = Self.message(error)
            }
        }
    }

    func toggleInspirationPick(_ productID: String) {
        let name = groupName(for: inspirationQuery, productID: productID)
        if let index = candidateGroups.firstIndex(where: { $0.productIDs.contains(productID) }) {
            removeFromGroup(candidateGroups[index].id, productID: productID)
            return
        }
        addToGroup(named: name, productID: productID)
    }

    func addToGroup(named raw: String, productID: String) {
        guard let product = product(productID) ?? inspirationResults.first(where: { $0.id == productID }) else { return }
        remember(product)
        let name = Self.normalizedGroupName(raw.isEmpty ? product.title : raw)
        if let other = candidateGroups.firstIndex(where: { $0.productIDs.contains(productID) }) {
            removeFromGroup(candidateGroups[other].id, productID: productID)
        }
        if let index = candidateGroups.firstIndex(where: { Self.normalizedGroupName($0.name) == name }) {
            guard candidateGroups[index].productIDs.count < 20 else { return }
            candidateGroups[index].productIDs.append(productID)
            if candidateGroups[index].showingProductID == nil {
                showInGroup(candidateGroups[index].id, productID: productID)
            }
        } else {
            let group = CandidateGroup(id: UUID(), name: raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                       ? product.title : raw.trimmingCharacters(in: .whitespacesAndNewlines),
                                       category: product.category, productIDs: [productID], showingProductID: productID)
            candidateGroups.append(group)
            placeGroupInRoom(group, product: product)
        }
        persistCurrentExtras()
    }

    func removeFromGroup(_ groupID: UUID, productID: String) {
        guard let index = candidateGroups.firstIndex(where: { $0.id == groupID }) else { return }
        candidateGroups[index].productIDs.removeAll { $0 == productID }
        if candidateGroups[index].showingProductID == productID {
            candidateGroups[index].showingProductID = candidateGroups[index].productIDs.first
        }
        if candidateGroups[index].productIDs.isEmpty {
            extraObjects.removeAll { $0.objectID == candidateGroups[index].objectID }
            appliedPreviews[candidateGroups[index].objectID] = nil
            previews[candidateGroups[index].objectID] = nil
            candidateGroups.remove(at: index)
        } else if let next = candidateGroups[index].showingProductID {
            showInGroup(groupID, productID: next)
        }
        persistCurrentExtras()
    }

    func showInGroup(_ groupID: UUID, productID: String) {
        guard let index = candidateGroups.firstIndex(where: { $0.id == groupID }),
              candidateGroups[index].productIDs.contains(productID),
              let product = product(productID) else { return }
        candidateGroups[index].showingProductID = productID
        remember(product)
        let objectID = candidateGroups[index].objectID
        if extraObjects.contains(where: { $0.objectID == objectID }) {
            appliedPreviews[objectID] = productID
            previews[objectID] = nil
            if let dims = product.placeableDimensions, let i = extraObjects.firstIndex(where: { $0.objectID == objectID }) {
                extraObjects[i].productID = productID
                extraObjects[i].dimensionsM = dims
                extraObjects[i].colorHex = product.style?.colorHex
                extraObjects[i].assetURL = product.assetURL
            }
            select(objectID)
        } else {
            placeGroupInRoom(candidateGroups[index], product: product)
        }
        persistCurrentExtras()
        realizeInBackground(product)
    }

    func editCandidateGroup(_ group: CandidateGroup) {
        pendingInspirationQuery = group.name
    }

    private func groupName(for query: String, productID: String) -> String {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        return product(productID)?.title ?? "Selected"
    }

    private static func normalizedGroupName(_ name: String) -> String {
        name.lowercased().split { $0.isWhitespace }.joined(separator: " ")
    }

    private func placeGroupInRoom(_ group: CandidateGroup, product: Product) {
        guard let dims = product.placeableDimensions else { return }
        remember(product)
        let objectID = group.objectID
        if extraObjects.contains(where: { $0.objectID == objectID }) {
            appliedPreviews[objectID] = product.id
            select(objectID)
            return
        }
        let room = state.room
        let existing = displayedObjects.filter { $0.category == product.category }.count
        let x = Self.clamped(-room.widthM / 2 + dims.width / 2 + 0.25 + Double(existing) * 0.4,
                             lo: -room.widthM / 2 + dims.width / 2, hi: room.widthM / 2 - dims.width / 2)
        let z = Self.clamped(-room.depthM / 2 + dims.depth / 2 + 0.3,
                             lo: -room.depthM / 2 + dims.depth / 2, hi: room.depthM / 2 - dims.depth / 2)
        extraObjects.append(SceneObject(
            objectID: objectID, productID: product.id, category: product.category,
            positionM: [x, 0, z], rotationYRad: 0, dimensionsM: dims,
            colorHex: product.style?.colorHex, assetURL: product.assetURL, proposalVersion: nil,
            texture: product.category == "rug" ? (product.imageURL ?? product.localImage).map { ObjectTexture(imageURL: $0) } : nil))
        appliedPreviews[objectID] = product.id
        select(objectID)
        persistCurrentExtras()
        realizeInBackground(product)
    }

    func previewInspiration(_ productID: String) {
        toggleInspirationPick(productID)
    }

    func objectID(forCategory category: String?) -> String? {
        guard let category else { return nil }
        return displayedObjects.first { $0.category == category }?.objectID
    }

    func objectID(forProductID productID: String) -> String? {
        displayedObjects.first { $0.productID == productID }?.objectID
    }

    static func category(from query: String) -> String? {
        let t = query.lowercased()
        let words: [(String, [String])] = [
            ("bed", ["bed", "beds", "mattress"]),
            ("nightstand", ["nightstand", "nightstands", "night table", "bedside"]),
            ("dresser", ["dresser", "dressers", "chest of drawers"]),
            ("chair", ["chair", "chairs", "armchair", "armchairs"]),
            ("lamp", ["lamp", "lamps", "lighting"]),
            ("desk", ["desk", "desks"]),
            ("sofa", ["sofa", "sofas", "couch", "couches", "sectional"]),
            ("coffee_table", ["coffee table", "coffee tables"]),
            ("rug", ["rug", "rugs", "carpet"]),
            ("tv", ["tv", "television", "televisions"]),
        ]
        return words.first { _, aliases in
            aliases.contains { alias in
                if alias.contains(" ") { return t.contains(alias) }
                return t.range(of: "\\b\(NSRegularExpression.escapedPattern(for: alias))\\b", options: .regularExpression) != nil
            }
        }?.0
    }

    static func rank(products: [Product], query: String, category: String?) -> [Product] {
        let tokens = query.lowercased().split { !$0.isLetter && $0 != "'" }.map(String.init)
            .filter { $0.count > 1 && !["the", "and", "for", "with"].contains($0) }
        let pool: [Product]
        if let cat = category {
            pool = products.filter { $0.category == cat }
        } else {
            pool = products.filter { score($0, tokens: tokens) > 0 }
        }
        return pool.sorted { a, b in
            let sa = score(a, tokens: tokens)
            let sb = score(b, tokens: tokens)
            if sa != sb { return sa > sb }
            return a.priceCents < b.priceCents
        }
    }

    private static func score(_ product: Product, tokens: [String]) -> Int {
        let hay = [product.title, product.variant, product.description, product.style?.tags?.joined(separator: " ")]
            .compactMap { $0 }.joined(separator: " ").lowercased()
        return tokens.reduce(0) { $0 + (hay.contains($1) ? 2 : 0) } + (product.placeableDimensions != nil ? 1 : 0)
    }

    private func persistRoster() {
        persistJSON(extraPeople, key: Self.rosterKey)
        persistJSON(memberPhotos, key: Self.memberPhotosKey)
    }

    private func photoURL(_ filename: String?) -> URL? {
        guard let filename else { return nil }
        return Self.ownedImagesDirectory.appendingPathComponent(filename)
    }

    private func persistJSON<T: Encodable>(_ value: T, key: String) {
        if let data = try? JSONEncoder().encode(value) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }

    private static func loadJSON<T: Decodable>(_ key: String, as: T.Type) -> T? {
        guard let data = UserDefaults.standard.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    private static func makeInviteCode() -> String {
        String(format: "%06d", Int.random(in: 0...999_999))
    }

    private static func loadOwnedItems() -> [OwnedItem] {
        guard let data = UserDefaults.standard.data(forKey: ownedItemsKey) else { return [] }
        return (try? JSONDecoder().decode([OwnedItem].self, from: data)) ?? []
    }

    private func persistOwnedItems() {
        if let data = try? JSONEncoder().encode(ownedItems) {
            UserDefaults.standard.set(data, forKey: Self.ownedItemsKey)
        }
    }

    private func persistCurrentExtras() {
        extrasByHousehold[currentHouseholdID] = LocalSceneExtras(
            objects: extraObjects, products: extraProducts, applied: appliedPreviews, groups: candidateGroups)
        if let data = try? JSONEncoder().encode(extrasByHousehold) {
            UserDefaults.standard.set(data, forKey: Self.extrasKey)
        }
    }

    private func restoreExtras(for householdID: String) {
        let extras = extrasByHousehold[householdID] ?? LocalSceneExtras()
        extraObjects = extras.objects
        extraProducts = extras.products
        appliedPreviews = extras.applied
        candidateGroups = extras.groups
    }

    private static func loadExtras() -> [String: LocalSceneExtras] {
        guard let data = UserDefaults.standard.data(forKey: extrasKey) else { return [:] }
        return (try? JSONDecoder().decode([String: LocalSceneExtras].self, from: data)) ?? [:]
    }

    private static var ownedImagesDirectory: URL {
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("owned-items", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private static func writeOwnedImage(_ image: UIImage) -> String? {
        guard let data = image.jpegData(compressionQuality: 0.85) else { return nil }
        let name = "\(UUID().uuidString).jpg"
        try? data.write(to: ownedImagesDirectory.appendingPathComponent(name), options: .atomic)
        return name
    }

    // MARK: Server rules (mirrored client-side so buttons can be disabled with a reason)

    var approvalBlocker: String? {
        guard let proposal = state.proposal else { return "No proposal yet" }
        guard proposal.shares[actingMemberID] != nil else { return "\(state.name(of: actingMemberID)) is not part of this proposal" }
        guard proposal.status == .awaitingApproval else { return "Proposal is \(proposal.status.label.lowercased())" }
        if proposal.approvals[actingMemberID] == true { return "Already approved" }
        return nil
    }

    var objectionBlocker: String? {
        guard let proposal = state.proposal else { return "No proposal yet" }
        guard proposal.shares[actingMemberID] != nil else { return "Not part of this proposal" }
        guard proposal.status == .awaitingApproval || proposal.status == .draft else { return "Proposal is \(proposal.status.label.lowercased())" }
        return nil
    }

    var purchaseBlocker: String? {
        guard let proposal = state.proposal else { return "No proposal yet" }
        guard actingMemberID == state.finance.payerID else { return "Only the payer (\(state.name(of: state.finance.payerID))) can authorize the purchase" }
        guard proposal.status == .approved else {
            return proposal.status == .awaitingApproval ? "Waiting for every member to approve" : "Proposal is \(proposal.status.label.lowercased())"
        }
        if let purchase = state.finance.purchase, purchase.state != .failed { return "Purchase already \(purchase.state.label.lowercased())" }
        return nil
    }

    func reimbursementBlocker(_ r: Reimbursement) -> String? {
        guard actingMemberID == r.fromMember else { return "Only \(state.name(of: r.fromMember)) can authorize this" }
        guard state.finance.purchase?.state == .confirmed else { return "Purchase must be confirmed first" }
        if let op = r.operation, op.state != .failed { return "Already \(op.state.label.lowercased())" }
        return nil
    }

    // MARK: Connection

    func start() {
        guard connectionTask == nil else { return }
        // `-backendBaseURL <url>` launch arguments (Xcode scheme or devicectl) only last one launch; keep them.
        if let url = UserDefaults.standard.volatileDomain(forName: UserDefaults.argumentDomain)[Self.baseURLKey] as? String {
            UserDefaults.standard.set(url, forKey: Self.baseURLKey)
        }
        reconnect()
    }

    /// `ragtorooms://connect?url=<backend>` from a QR code (backend/scripts/tunnel.sh) or a link.
    func handleOpenURL(_ url: URL) {
        guard url.scheme == "ragtorooms", url.host == "connect",
              let target = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "url" })?.value,
              (try? BackendClient(baseURLString: target)) != nil else { return }
        UserDefaults.standard.set(target, forKey: Self.baseURLKey)
        reconnect()
    }

    func reconnect() {
        connectionTask?.cancel()
        sseBuffered = false
        let urlString = UserDefaults.standard.string(forKey: Self.baseURLKey) ?? Self.defaultBaseURL
        do {
            client = try BackendClient(baseURLString: urlString)
            client?.householdID = currentHouseholdID
        } catch {
            client = nil
            connection = .offline(error.localizedDescription)
            return
        }
        restartConnection()
    }

    @ObservationIgnored private var sseBuffered = false
    @ObservationIgnored private var sseEventSeen = false

    /// Restarts SSE/polling for `client.householdID` (after a base URL or room scope change).
    private func restartConnection() {
        connectionTask?.cancel()
        guard client != nil else { return }
        connection = .connecting
        connectionTask = Task { [weak self] in await self?.runConnection() }
    }

    func setActingMember(_ id: String) {
        guard id != actingMemberID else { return }
        actingMemberID = id
        UserDefaults.standard.set(id, forKey: Self.actingMemberKey)
        if let client, source == .live { Task { try? await refresh(client) } }
    }

    private func runConnection() async {
        guard let client else { return }
        var failures = 0
        while !Task.isCancelled {
            do {
                try await loadAll(client)
                failures = 0
            } catch BackendError.http(status: 404, _) where client.householdID != Self.defaultHouseholdID {
                // Reachable backend without this room scope yet: show bundled fixtures, re-check every 5 s.
                if Task.isCancelled { return }
                fallBackToScopeFixture()
                try? await Task.sleep(for: .seconds(5))
                continue
            } catch {
                if Task.isCancelled { return }
                markUnreachable(error)
                failures += 1
                try? await Task.sleep(for: .seconds(min(10, 2 * failures)))
                continue
            }

            if !sseBuffered {
                // The backend sends the current state as soon as a stream opens. Proxies that buffer event
                // streams (e.g. Cloudflare quick tunnels) deliver nothing, so give up on SSE for this backend.
                sseEventSeen = false
                let stream = Task { [weak self] in
                    do {
                        for try await event in EventStream.events(from: client.eventsURL, token: client.authToken) {
                            guard let self, !Task.isCancelled else { return }
                            if event.event != EventStream.openEvent { self.sseEventSeen = true }
                            await self.handle(event, client: client)
                        }
                    } catch {}
                }
                let watchdog = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(6))
                    if !Task.isCancelled, self?.sseEventSeen == false { stream.cancel() }
                }
                await withTaskCancellationHandler { await stream.value } onCancel: { stream.cancel() }
                watchdog.cancel()
                if Task.isCancelled { return }
                if !sseEventSeen { sseBuffered = true }
            }

            // SSE unavailable, buffered or dropped: poll for ~30 s, then try SSE again unless it is buffered.
            connection = .polling
            for _ in 0..<15 {
                try? await Task.sleep(for: .seconds(2))
                if Task.isCancelled { return }
                do { try await refresh(client) } catch { markUnreachable(error); break }
            }
        }
    }

    private func handle(_ event: ServerSentEvent, client: BackendClient) async {
        if event.event == EventStream.openEvent { connection = .live; return }
        connection = .live
        let payload = try? JSONDecoder().decode(StateEventPayload.self, from: Data(event.data.utf8))
        if let version = payload?.stateVersion, version == state.stateVersion, source == .live { return }
        try? await refresh(client)
    }

    private func loadAll(_ client: BackendClient) async throws {
        try await refresh(client)
        if let list = try? await client.products() { products = list }
    }

    private func refresh(_ client: BackendClient) async throws {
        let newState = try await client.state(memberID: actingMemberID)
        // Drop responses for a scope the user has already switched away from.
        guard client.householdID == currentHouseholdID else { return }
        apply(newState)
    }

    private func fallBackToScopeFixture() {
        if currentGroupID != nil {
            scopeNotice = "This room could not be loaded. Check your account and backend connection."
            connection = .offline("Room unavailable")
            return
        }
        reachedBackend = true
        connection = .polling
        scopeNotice = "\(currentRoomName) isn't on the backend yet. Showing demo fixtures; actions stay on this iPad."
        if source != .fixture || stateIsPlaceholder {
            state = Self.fixtureState(forScope: currentHouseholdID)
            source = .fixture
            stateIsPlaceholder = false
        }
        Task { await refreshApartment() }
    }

    func refreshNow() async {
        guard let client, source == .live else { return }
        do { try await refresh(client) } catch { errorMessage = Self.message(error) }
    }

    private func apply(_ newState: HouseholdState) {
        let oldObjects = Dictionary(state.scene.objects.map { ($0.objectID, $0) }, uniquingKeysWith: { a, _ in a })
        for (id, pose) in localPoses {
            guard let incoming = newState.scene.objects.first(where: { $0.objectID == id }) else { localPoses[id] = nil; continue }
            let caughtUp = abs(incoming.x - pose.x) < 0.01 && abs(incoming.z - pose.z) < 0.01 && abs(incoming.rotationYRad - pose.rotation) < 0.01
            let replaced = oldObjects[id].map { $0.productID != incoming.productID || $0.proposalVersion != incoming.proposalVersion } ?? true
            if caughtUp || (source == .live && replaced) { localPoses[id] = nil }
        }
        let ids = Set(newState.scene.objects.map(\.objectID))
        extraObjects.removeAll { ids.contains($0.objectID) }
        let kept = ids.union(extraObjects.map(\.objectID))
        previews = previews.filter { kept.contains($0.key) }
        appliedPreviews = appliedPreviews.filter { kept.contains($0.key) }
        if let selected = selectedObjectID, !kept.contains(selected) { selectedObjectID = nil }
        if productsFromFixture { products = []; productsFromFixture = false } // fixture products don't exist on the server
        let changed = !reachedBackend || stateIsPlaceholder || newState.stateVersion != state.stateVersion
        state = newState
        source = .live
        reachedBackend = true
        stateIsPlaceholder = false
        scopeNotice = nil
        if connection == .connecting { connection = .polling }
        lastUpdated = Date()
        if changed { Task { await refreshApartment() } }
    }

    private func markUnreachable(_ error: Error) {
        connection = .offline(Self.message(error))
    }

    static func message(_ error: Error) -> String {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .cannotConnectToHost, .cannotFindHost, .timedOut, .networkConnectionLost, .notConnectedToInternet:
                return "Backend unreachable (\(urlError.localizedDescription))"
            case .appTransportSecurityRequiresSecureConnection:
                return "Blocked by App Transport Security; see ios/README.md"
            default: break
            }
        }
        return error.localizedDescription
    }

    // MARK: Local manipulation (never requires the network)

    func select(_ objectID: String?) {
        selectedObjectID = objectID
        if objectID != nil { detailProductID = nil }
    }

    func moveLocally(_ objectID: String, x: Double, z: Double) {
        let current = displayedObjects.first { $0.objectID == objectID }
        localPoses[objectID] = LocalPose(x: x, z: z, rotation: current?.rotationYRad ?? 0)
    }

    func rotateLocally(_ objectID: String, to angle: Double) {
        guard let current = displayedObjects.first(where: { $0.objectID == objectID }) else { return }
        localPoses[objectID] = LocalPose(x: current.x, z: current.z, rotation: angle)
    }

    func rotateSelected(byDegrees degrees: Double) {
        guard let object = selectedObject else { return }
        rotateLocally(object.objectID, to: object.rotationYRad + degrees * .pi / 180)
        commitMove(object.objectID)
    }

    func resetLocalEdits() {
        localPoses = [:]
        previews = [:]
    }

    /// Called at the end of a gesture. Persists the move only if the user enabled it in Settings.
    func commitMove(_ objectID: String) {
        guard UserDefaults.standard.bool(forKey: Self.patchMovesKey), source == .live, let client,
              !objectID.hasPrefix("local-"), let pose = localPoses[objectID] else { return }
        Task {
            do {
                try await client.patchObject(objectID, x: pose.x, z: pose.z, rotation: pose.rotation)
                try? await refresh(client)
            } catch {
                errorMessage = "Move kept locally; server rejected it: \(Self.message(error))"
            }
        }
    }

    func setPreview(objectID: String, productID: String) { previews[objectID] = productID }
    func clearPreview(objectID: String) { previews[objectID] = nil }

    // MARK: Server actions

    @discardableResult
    private func perform(_ key: String, offline: () -> Void, online: (BackendClient) async throws -> Void) async -> Bool {
        guard !busy.contains(key) else { return false }
        if source == .fixture { offline(); return false }
        guard let client else { errorMessage = "No backend configured"; return false }
        busy.insert(key)
        defer { busy.remove(key) }
        do {
            try await online(client)
            errorMessage = nil
            try? await refresh(client)
            return true
        } catch {
            errorMessage = Self.message(error)
            return false
        }
    }

    func approve() async {
        guard let version = state.proposal?.version else { return }
        let member = actingMemberID
        await perform("approve", offline: { offlineApprove(member) }) { try await $0.approve(version: version, memberID: member) }
    }

    func object(reason: String) async {
        guard let version = state.proposal?.version else { return }
        let member = actingMemberID
        await perform("object", offline: { offlineObject(member, reason: reason) }) {
            try await $0.object(version: version, memberID: member, reason: reason)
        }
    }

    func setLimit(cents: Int) async {
        let member = actingMemberID
        await perform("limit", offline: { offlineSetLimit(member, cents: cents) }) { try await $0.setLimit(memberID: member, cents: cents) }
    }

    func setBudget(cents: Int) async {
        await perform("budget", offline: { offlineSetBudget(cents: cents) }) { try await $0.setBudget(cents: cents) }
    }

    func authorizePurchase() async {
        guard let version = state.proposal?.version else { return }
        let member = actingMemberID
        await perform("purchase", offline: { offlineAuthorizePurchase() }) { try await $0.authorizePurchase(memberID: member, version: version) }
    }

    func authorizeReimbursement(_ liabilityID: String) async {
        let member = actingMemberID
        await perform("reimb-\(liabilityID)", offline: { offlineAuthorizeReimbursement(liabilityID) }) {
            try await $0.authorizeReimbursement(liabilityID: liabilityID, memberID: member)
        }
    }

    func reconcile() async {
        await perform("reconcile", offline: {}) { try await $0.reconcile() }
    }

    func saveRoom(_ room: Room) async {
        await perform("room", offline: { offlineSaveRoom(room) }) { try await $0.putRoom(room) }
    }

    func uploadInspiration(_ image: UIImage) async {
        inspirationPreview = image
        guard let jpeg = image.jpegData(compressionQuality: 0.85) else { return }
        await perform("inspiration", offline: { appendActivity("Inspiration photo saved locally (offline demo)") }) {
            try await $0.uploadInspiration(jpegData: jpeg)
        }
    }

    /// Empty every room (no proposals or furniture). Used after a new user finishes setup.
    func startBlankApartment() async {
        resetLocalEdits()
        await perform("blank", offline: {
            state = HouseholdState(
                householdID: state.householdID, stateVersion: state.stateVersion + 1,
                members: state.members, room: state.room, budgetCents: state.budgetCents,
                proposal: nil, scene: SceneState(objects: [], validation: nil),
                finance: Finance(payerID: state.finance.payerID, simulator: state.finance.simulator),
                activity: [], catalogMode: state.catalogMode)
        }) { try await $0.blankApartment() }
        scopeCache = [:]
        liveSummaries = [:]
        await refreshApartment(force: true)
        if let client { try? await refresh(client) }
    }

    func resetDemo() async {
        guard currentGroupID == nil else { errorMessage = "Demo reset is only available in demo mode."; return }
        resetLocalEdits()
        await perform("reset", offline: {
            let fixtures = Self.loadFixtures()
            state = currentHouseholdID == Self.defaultHouseholdID ? fixtures.state : Self.fixtureState(forScope: currentHouseholdID)
            if productsFromFixture { products = fixtures.products }
        }) { try await $0.resetDemo() }
        // `/demo/reset` reseeds every scope, so other rooms' snapshots are stale either way.
        scopeCache = [:]
        await refreshApartment()
    }

    func designRoom(_ text: String) async {
        await sendChat(text.isEmpty ? chatSuggestion : text, mode: "design")
    }

    func sendChat(_ text: String, mode: String? = nil) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let member = actingMemberID
        chat.append(ChatMessage(author: actingMemberName, text: trimmed, fromMe: true))
        guard source == .live, let client else {
            chat.append(ChatMessage(author: "Agent", text: "Offline demo: the backend isn't reachable, so I can't search products right now. Set the backend URL in Settings and try again.", fromMe: false, isError: true))
            return
        }
        let resolved = mode ?? (state.proposal != nil ? "refine" : "design")
        let skip = Array(Set(currentOwnedItems.map(\.category)))
        busy.insert(resolved == "design" ? "design" : "chat")
        defer { busy.remove(resolved == "design" ? "design" : "chat") }
        do {
            let reply = try await client.chat(memberID: member, text: trimmed, pickIds: inspirationPicks,
                                             mode: resolved, skipCategories: skip)
            chat.append(ChatMessage(author: "Agent", text: reply, fromMe: false))
            try? await refresh(client)
        } catch {
            chat.append(ChatMessage(author: "Agent", text: Self.message(error), fromMe: false, isError: true))
        }
    }
}
