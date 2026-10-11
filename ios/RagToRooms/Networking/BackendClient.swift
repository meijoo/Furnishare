import Foundation

enum BackendError: LocalizedError {
    case invalidBaseURL(String)
    case http(status: Int, message: String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL(let s): "Invalid backend URL: \(s)"
        case .http(let status, let message): "\(message) (HTTP \(status))"
        case .decoding(let detail): "Unexpected response from backend: \(detail)"
        }
    }
}

/// Thin async/await client for docs/API.md. Stateless apart from the base URL and the room scope.
struct BackendClient: Sendable {
    let baseURL: URL
    /// Room scope that every `/households/{hid}/...` call targets. AppModel switches it with the current room.
    var householdID = "demo"

    static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 8
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    init(baseURL: URL) { self.baseURL = baseURL }

    init(baseURLString: String) throws {
        var trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        while trimmed.hasSuffix("/") { trimmed.removeLast() }
        if !trimmed.contains("://") { trimmed = "http://" + trimmed }
        guard var url = URL(string: trimmed), let host = url.host else { throw BackendError.invalidBaseURL(baseURLString) }
        if url.scheme == "http", url.port == nil, Self.isLocalHost(host),
           var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            parts.port = 8000
            url = parts.url ?? url
        }
        baseURL = url
    }

    /// LAN IPs, localhost and Bonjour names get the backend's default port; tunnels and real domains keep theirs.
    private static func isLocalHost(_ host: String) -> Bool {
        host == "localhost" || host.hasSuffix(".local")
            || host.split(separator: ".").count == 4 && host.allSatisfy { $0.isNumber || $0 == "." }
    }

    /// Resolves server-relative paths (`/assets/x.usdz`, `product_images/x.jpg`) against the base URL.
    func resolve(_ path: String?) -> URL? { Self.resolve(path, base: baseURL) }

    static func resolve(_ path: String?, base: URL?) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        if path.hasPrefix("http://") || path.hasPrefix("https://") { return URL(string: path) }
        guard let base else { return nil }
        let rooted = path.hasPrefix("/") ? path : "/" + path
        return URL(string: rooted, relativeTo: base)?.absoluteURL
    }

    private var household: String { "/households/\(householdID)" }

    // MARK: Endpoints

    var authToken: String? { AccountSessionStore.token(for: baseURL) }

    func signup(name: String, email: String, phone: String, username: String, password: String) async throws -> AccountSession {
        try await send("POST", "/auth/signup", body: SignupRequest(name: name, email: email, phone: phone, username: username, password: password), timeout: 30)
    }

    func login(email: String, password: String) async throws -> AccountSession {
        try await send("POST", "/auth/login", body: LoginRequest(email: email, password: password), timeout: 30)
    }

    func accountStatus() async throws -> AccountStatus { try await send("GET", "/auth/me") }

    func logout() async throws { try await sendIgnoringBody("POST", "/auth/logout") }

    func createGroup(name: String, location: String, requestID: String) async throws -> StoredGroup {
        try await send("POST", "/groups", body: CreateGroupRequest(name: name, location: location, request_id: requestID))
    }

    func invite(members: [InviteMember], requestID: String) async throws -> RoomInvitation {
        try await send("POST", "\(household)/invitations", body: InviteRequest(members: members, request_id: requestID))
    }

    func joinGroup(code: String) async throws -> JoinedGroup {
        try await send("POST", "/groups/join", body: JoinGroupRequest(code: code))
    }

    func invitation(token: String) async throws -> RoomInvitation {
        try await send("GET", "/invitations/\(Self.pathEscaped(token))")
    }

    func suggestions() async throws -> SuggestionList {
        try await send("GET", "\(household)/suggestions")
    }

    func health() async throws -> HealthResponse { try await send("GET", "/health") }

    func products(category: String? = nil) async throws -> [Product] {
        let list: ProductList = try await send("GET", "/products", query: category.map { ["category": $0] } ?? [:])
        return list.products
    }

    func searchProducts(_ query: String) async throws -> [Product] {
        let list: ProductList = try await send("GET", "/products/search", query: ["q": query], timeout: 20)
        return list.products
    }

    func realizeProduct(_ product: Product, image: UploadImage? = nil) async throws -> RealizeStatus {
        guard let dims = product.placeableDimensions else {
            throw BackendError.decoding("product has no placeable dimensions")
        }
        if let image {
            var fields = [
                "id": product.id, "title": product.title, "category": product.category,
                "width": String(dims.width), "depth": String(dims.depth), "height": String(dims.height),
            ]
            if let source = product.sourceURL { fields["source_url"] = source }
            let data = try await upload("/products/realize/upload", file: image, fields: fields, timeout: 30)
            do { return try Self.decoder.decode(RealizeStatus.self, from: data) }
            catch let error as DecodingError { throw BackendError.decoding(Self.describe(error)) }
        }
        return try await send("POST", "/products/realize", body: RealizeRequest(
            id: product.id, title: product.title, category: product.category,
            imageURL: product.imageURL?.hasPrefix("http") == true ? product.imageURL : nil,
            sourceURL: product.sourceURL, retailer: product.retailer, description: product.description,
            priceCents: product.priceCents, dimensionsM: dims), timeout: 20)
    }

    func realizeStatus(_ productID: String) async throws -> RealizeStatus {
        try await send("GET", "/products/realize/\(Self.pathEscaped(productID))", timeout: 12)
    }

    func apartment(id: String) async throws -> Apartment {
        try await send("GET", "/apartments/\(id)")
    }

    func state(memberID: String?) async throws -> HouseholdState {
        try await send("GET", "\(household)/state", query: memberID.map { ["member_id": $0] } ?? [:])
    }

    func putRoom(_ room: Room) async throws {
        try await sendIgnoringBody("PUT", "\(household)/room", body: RoomUpdate(room))
    }

    func chat(memberID: String, text: String, pickIds: [String] = [], mode: String? = nil,
              skipCategories: [String] = []) async throws -> String {
        let reply: ChatReply = try await send("POST", "\(household)/chat",
                                              body: ChatBody(memberID: memberID, text: text, pickIds: pickIds,
                                                             mode: mode, skipCategories: skipCategories), timeout: 90)
        return reply.reply
    }

    func setLimit(memberID: String, cents: Int) async throws {
        try await sendIgnoringBody("PUT", "\(household)/members/\(memberID)/limit", body: LimitBody(limitCents: cents))
    }

    func setBudget(cents: Int) async throws {
        try await sendIgnoringBody("PUT", "\(household)/budget", body: BudgetBody(budgetCents: cents))
    }

    func approve(version: Int, memberID: String) async throws {
        try await sendIgnoringBody("POST", "\(household)/proposals/\(version)/approve", body: MemberBody(memberID: memberID))
    }

    func object(version: Int, memberID: String, reason: String) async throws {
        try await sendIgnoringBody("POST", "\(household)/proposals/\(version)/object", body: ObjectBody(memberID: memberID, reason: reason))
    }

    func patchObject(_ objectID: String, x: Double, z: Double, rotation: Double) async throws {
        try await sendIgnoringBody("PATCH", "\(household)/scene/objects/\(Self.pathEscaped(objectID))",
                                   body: ObjectPoseBody(positionM: [x, 0, z], rotationYRad: rotation))
    }

    func authorizePurchase(memberID: String, version: Int) async throws {
        try await sendIgnoringBody("POST", "\(household)/purchase/authorize",
                                   body: PurchaseAuthorizeBody(memberID: memberID, proposalVersion: version), timeout: 30)
    }

    func authorizeReimbursement(liabilityID: String, memberID: String) async throws {
        try await sendIgnoringBody("POST", "\(household)/reimbursements/\(liabilityID)/authorize",
                                   body: MemberBody(memberID: memberID), timeout: 30)
    }

    func reconcile() async throws {
        try await sendIgnoringBody("POST", "\(household)/finance/reconcile", timeout: 30)
    }

    func resetDemo() async throws {
        try await sendIgnoringBody("POST", "/demo/reset")
    }

    func uploadInspiration(jpegData: Data, filename: String = "inspiration.jpg") async throws {
        _ = try await upload("\(household)/inspiration", file: UploadImage(data: jpegData, mimeType: "image/jpeg", filename: filename),
                             timeout: 60)
    }

    /// Reading the plan with Gemini takes 10-30 s.
    func importFloorplan(apartmentID: String, image: UploadImage, widthM: Double?) async throws -> FloorplanImportResponse {
        let fields = widthM.map { ["width_m": String(format: "%.3f", $0)] } ?? [:]
        let data = try await upload("/apartments/\(apartmentID)/floorplan", file: image, fields: fields, timeout: 60)
        do {
            return try Self.decoder.decode(FloorplanImportResponse.self, from: data)
        } catch let error as DecodingError {
            throw BackendError.decoding(Self.describe(error))
        }
    }

    func restoreFloorplan(apartmentID: String) async throws {
        try await sendIgnoringBody("DELETE", "/apartments/\(apartmentID)/floorplan", timeout: 60)
    }

    /// `mode` is `print` or `tile`; `tileM` only applies to `tile`.
    func putTexture(objectID: String, image: UploadImage, mode: String, tileM: Double?) async throws {
        var fields = ["mode": mode]
        if let tileM { fields["tile_m"] = String(format: "%.2f", tileM) }
        _ = try await upload("\(household)/scene/objects/\(Self.pathEscaped(objectID))/texture", file: image, fields: fields, timeout: 60)
    }

    func deleteTexture(objectID: String) async throws {
        try await sendIgnoringBody("DELETE", "\(household)/scene/objects/\(Self.pathEscaped(objectID))/texture")
    }

    var eventsURL: URL { baseURL.appendingPathComponent("households/\(householdID)/events") }

    // MARK: Plumbing

    private static let encoder = JSONEncoder()
    private static let decoder = JSONDecoder()

    private func makeRequest(_ method: String, _ path: String, query: [String: String], timeout: TimeInterval) -> URLRequest {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.path = (components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path) + path
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        if let token = authToken { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private func send<T: Decodable>(_ method: String, _ path: String, query: [String: String] = [:],
                                    body: (any Encodable)? = nil, timeout: TimeInterval = 8) async throws -> T {
        var request = makeRequest(method, path, query: query, timeout: timeout)
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try Self.encoder.encode(body)
        }
        let data = try await perform(request)
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch let error as DecodingError {
            throw BackendError.decoding(Self.describe(error))
        }
    }

    private func sendIgnoringBody(_ method: String, _ path: String, body: (any Encodable)? = nil, timeout: TimeInterval = 8) async throws {
        var request = makeRequest(method, path, query: [:], timeout: timeout)
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try Self.encoder.encode(body)
        }
        _ = try await perform(request)
    }

    private static func pathEscaped(_ component: String) -> String {
        component.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? component
    }

    /// Multipart POST with one `file` part plus plain form fields.
    private func upload(_ path: String, file: UploadImage, fields: [String: String] = [:], timeout: TimeInterval) async throws -> Data {
        let boundary = "RagToRooms-\(UUID().uuidString)"
        var body = Data()
        for (name, value) in fields.sorted(by: { $0.key < $1.key }) {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(file.filename)\"\r\n".utf8))
        body.append(Data("Content-Type: \(file.mimeType)\r\n\r\n".utf8))
        body.append(file.data)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var request = makeRequest("POST", path, query: [:], timeout: timeout)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        return try await perform(request)
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await Self.session.data(for: request)
        guard let http = response as? HTTPURLResponse else { return data }
        guard (200..<300).contains(http.statusCode) else {
            throw BackendError.http(status: http.statusCode, message: Self.serverMessage(from: data, status: http.statusCode))
        }
        return data
    }

    /// Extracts FastAPI-style `{"detail": "..."}` / `{"detail": [{"msg": ...}]}` or `{"error": "..."}` messages.
    static func serverMessage(from data: Data, status: Int) -> String {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = object["detail"] as? String { return detail }
            if let details = object["detail"] as? [[String: Any]] {
                let messages = details.compactMap { $0["msg"] as? String }
                if !messages.isEmpty { return messages.joined(separator: "; ") }
            }
            if let error = object["error"] as? String { return error }
            if let message = object["message"] as? String { return message }
        }
        if let text = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !text.isEmpty, text.count < 300 { return text }
        return HTTPURLResponse.localizedString(forStatusCode: status).capitalized
    }

    private static func describe(_ error: DecodingError) -> String {
        switch error {
        case .keyNotFound(let key, let ctx): "missing \(path(ctx.codingPath + [key]))"
        case .typeMismatch(_, let ctx), .valueNotFound(_, let ctx): "bad value at \(path(ctx.codingPath))"
        case .dataCorrupted(let ctx): "invalid JSON at \(path(ctx.codingPath))"
        @unknown default: "\(error)"
        }
    }

    private static func path(_ keys: [CodingKey]) -> String {
        keys.map { $0.intValue.map { "[\($0)]" } ?? $0.stringValue }.joined(separator: ".")
    }
}

struct InviteMember: Encodable {
    let member_id: String?
    let phone: String
    let name: String
    init(member_id: String? = nil, phone: String, name: String = "") {
        self.member_id = member_id; self.phone = phone; self.name = name
    }
}
struct InviteRequest: Encodable { let members: [InviteMember]; let request_id: String }
struct InvitationRecipient: Decodable { let member_name: String; let status: String; let error: String? }
struct RoomInvitation: Decodable {
    let recipients: [InvitationRecipient]?
    let token: String
    let household_id: String
    let group_code: String?
    let job_id: Int
    let status: String
    let error: String?
}
struct SuggestionList: Decodable { let suggestions: [FurnitureSuggestion] }
struct FurnitureSuggestion: Decodable, Identifiable {
    let id: String
    let member_name: String
    let text: String
    let links: [String]
    let products: [SuggestedFurniture]
}
struct SuggestedFurniture: Decodable {
    let title: String?
    let source_url: String?
}

struct JoinGroupRequest: Encodable { let code: String }
struct JoinedGroup: Decodable { let household_id: String; let group_name: String; let group_code: String; let group_id: String? }

struct SignupRequest: Encodable { let name: String; let email: String; let phone: String; let username: String; let password: String }
struct LoginRequest: Encodable { let email: String; let password: String }
struct CreateGroupRequest: Encodable { let name: String; let location: String; let request_id: String }
