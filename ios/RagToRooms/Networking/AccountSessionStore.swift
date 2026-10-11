import Foundation
import Security

struct AccountUser: Codable, Sendable {
    let id: String
    let name: String
    let email: String
    let phone: String
    let username: String
}
struct StoredGroupMember: Codable, Sendable { let id: String; let name: String; let role: String }
struct StoredGroup: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let location: String
    let owner_id: String
    let group_code: String
    let household_id: String
    let members: [StoredGroupMember]
}
struct AccountSession: Codable, Sendable { let token: String; let user: AccountUser; let groups: [StoredGroup] }
struct AccountStatus: Decodable, Sendable { let user: AccountUser; let groups: [StoredGroup] }
struct SavedAccountSession: Codable { let backend: String; let session: AccountSession }

/// Credentials are stored in Keychain, scoped to the server that issued them.
enum AccountSessionStore {
    private static let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.furnishare.account",
        kSecAttrAccount as String: "session"
    ]

    static func load() -> SavedAccountSession? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(lookup as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(SavedAccountSession.self, from: data)
    }

    static func token(for backend: URL) -> String? {
        guard let saved = load(), saved.backend == backend.absoluteString else { return nil }
        return saved.session.token
    }

    static func save(_ session: AccountSession, backend: URL) throws {
        let data = try JSONEncoder().encode(SavedAccountSession(backend: backend.absoluteString, session: session))
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let added = SecItemAdd(item as CFDictionary, nil)
            guard added == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(added)) }
        } else if status != errSecSuccess {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }

    static func clear() { SecItemDelete(query as CFDictionary) }
}
