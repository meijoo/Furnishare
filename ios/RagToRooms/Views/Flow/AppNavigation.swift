import SwiftUI

enum AppScreen: String, Hashable {
    case welcome, login, signUp, livingSituation, joinGroup, groupSetup, floorPlan, roomSelect, spaces, room
}

enum RoomTab: String, CaseIterable, Identifiable {
    case design, items, budget, inspiration
    var id: String { rawValue }

    var title: String {
        switch self {
        case .design: "Design"
        case .items: "Items"
        case .budget: "Budget"
        case .inspiration: "Inspiration"
        }
    }

    var symbol: String {
        switch self {
        case .design: "cube.transparent"
        case .items: "shippingbox"
        case .budget: "chart.pie"
        case .inspiration: "sparkles"
        }
    }
}

enum LivingMode: String, CaseIterable {
    case createGroup, joinGroup, solo

    var title: String {
        switch self {
        case .createGroup: "Create a group"
        case .joinGroup: "Join a group"
        case .solo: "I'm living solo"
        }
    }

    var subtitle: String {
        switch self {
        case .createGroup: "Start a new roommate, suite, or house group"
        case .joinGroup: "Enter a 6-digit code from a housemate"
        case .solo: "Set up your own space without a group"
        }
    }

    var symbol: String {
        switch self {
        case .createGroup: "person.3.fill"
        case .joinGroup: "link"
        case .solo: "person.fill"
        }
    }
}

enum HubSection: String, CaseIterable, Identifiable {
    case rooms, members
    var id: String { rawValue }
    var title: String { self == .rooms ? "Rooms" : "Members" }
    var symbol: String { self == .rooms ? "square.grid.2x2.fill" : "person.2.fill" }
}

enum SuccessKind: Equatable {
    case roomsSaved(Int)
    case itemAdded(String)
    case paymentSent(amount: String, to: String)
    case linkCopied
}

/// Local onboarding + which screen is showing. The household data still lives in `AppModel`.
@Observable
@MainActor
final class AppNavigation {
    static let completedKey = "hasCompletedOnboarding"
    static let profileNameKey = "profileDisplayName"
    static let profileEmailKey = "profileEmail"
    static let groupNameKey = "groupDisplayName"
    static let groupLocationKey = "groupLocation"
    static let selectedRoomsKey = "selectedRoomIDs"

    var screen: AppScreen
    var roomTab: RoomTab = .design
    var hubSection: HubSection = .rooms
    var showSettings = false
    var showRoomSetup = false
    var showAR = false
    var showCatalog = false
    var showAddItem = false
    var showSendMoney = false
    var showShare = false
    var success: SuccessKind?

    var profileName: String
    var profileEmail: String
    var profilePhone = ""
    var profileUsername = ""
    var password = ""
    var livingMode: LivingMode = .createGroup
    var joinCode = ""
    var groupName: String
    var groupLocation: String
    var selectedRoomIDs: Set<String>

    init() {
        profileName = UserDefaults.standard.string(forKey: Self.profileNameKey) ?? ""
        profileEmail = UserDefaults.standard.string(forKey: Self.profileEmailKey) ?? ""
        groupName = UserDefaults.standard.string(forKey: Self.groupNameKey) ?? ""
        groupLocation = UserDefaults.standard.string(forKey: Self.groupLocationKey) ?? ""
        if let stored = UserDefaults.standard.array(forKey: Self.selectedRoomsKey) as? [String] {
            selectedRoomIDs = Set(stored)
        } else {
            selectedRoomIDs = []
        }
        if let raw = UserDefaults.standard.string(forKey: "RTRScreen"), let forced = AppScreen(rawValue: raw) {
            screen = forced
            roomTab = Self.debugTab ?? .design
        } else if Self.shouldOpenWorkspace {
            screen = .room
            roomTab = Self.debugTab ?? .design
        } else if UserDefaults.standard.bool(forKey: Self.completedKey) {
            screen = .spaces
        } else {
            screen = .welcome
        }
    }

    var greetingName: String {
        let trimmed = profileName.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? "there" : trimmed.split(separator: " ").first.map(String.init) ?? trimmed
    }

    func persistProfile() {
        UserDefaults.standard.set(profileName, forKey: Self.profileNameKey)
        UserDefaults.standard.set(profileEmail, forKey: Self.profileEmailKey)
        UserDefaults.standard.set(groupName, forKey: Self.groupNameKey)
        UserDefaults.standard.set(groupLocation, forKey: Self.groupLocationKey)
        UserDefaults.standard.set(Array(selectedRoomIDs), forKey: Self.selectedRoomsKey)
    }

    func skipToDemo(apartment: Apartment?, actingName: String = "") {
        if profileName.isEmpty { profileName = actingName }
        if groupName.isEmpty { groupName = apartment?.name ?? "Our apartment" }
        if groupLocation.isEmpty { groupLocation = "Chapel Hill, NC" }
        if selectedRoomIDs.isEmpty {
            selectedRoomIDs = Set(apartment?.furnishableRooms.map(\.id) ?? [])
        }
        finishOnboarding()
    }

    func finishOnboarding() {
        persistProfile()
        UserDefaults.standard.set(true, forKey: Self.completedKey)
        hubSection = .rooms
        screen = .spaces
    }

    func replayIntro() {
        UserDefaults.standard.set(false, forKey: Self.completedKey)
        screen = .welcome
        roomTab = .design
        hubSection = .rooms
    }

    func enterRoom(_ room: ApartmentRoom, model: AppModel) {
        model.selectRoom(room.id)
        roomTab = .design
        screen = .room
    }

    func showSuccess(_ kind: SuccessKind) {
        success = kind
    }

    func dismissSuccess(continueAdding: Bool = false) {
        success = nil
        if continueAdding { showAddItem = true }
    }

    static var shouldOpenWorkspace: Bool {
        let defaults = UserDefaults.standard
        return ["RTRScrollTo", "RTRSelect", "RTRSwitchTo"].contains { defaults.string(forKey: $0) != nil }
            || defaults.bool(forKey: "RTRSkipOnboarding")
    }

    static var debugTab: RoomTab? {
        switch UserDefaults.standard.string(forKey: "RTRScrollTo") {
        case "floorplan": .design
        case "proposal", "product": .items
        case "contributions", "finance": .budget
        case "chat", "activity": .inspiration
        default: nil
        }
    }
}
