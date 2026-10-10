import SwiftUI
import PhotosUI

struct CatalogSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @State private var category = "all"

    private var categories: [String] {
        let found = Set(model.products.map(\.category))
        return ["all"] + found.sorted()
    }

    private var filtered: [Product] {
        category == "all" ? model.products : model.products.filter { $0.category == category }
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text("Search furniture and more")
                    .font(.subheadline).foregroundStyle(.secondary)
                    .padding(.horizontal)
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(categories, id: \.self) { item in
                            Button(item == "all" ? "All" : item.categoryLabel) { category = item }
                                .buttonStyle(GlassChipStyle(selected: category == item))
                        }
                    }
                    .padding(.horizontal)
                }
                .scrollIndicators(.hidden)
                if filtered.isEmpty {
                    ContentUnavailableView("No catalog items", systemImage: "shippingbox",
                                           description: Text("Connect to the backend or wait for fixtures to load."))
                } else {
                    ScrollView {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 12)], spacing: 12) {
                            ForEach(filtered) { product in
                                catalogCard(product)
                            }
                        }
                        .padding()
                    }
                }
            }
            .navigationTitle("Catalog")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    private func catalogCard(_ product: Product) -> some View {
        Button {
            model.select(nil)
            model.detailProductID = product.id
            nav.roomTab = .items
            dismiss()
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                ProductImage(urls: model.imageURLs(for: product), category: product.category)
                    .frame(height: 120)
                Text(product.title).font(.subheadline.weight(.semibold)).lineLimit(2).foregroundStyle(Color.aeroInk)
                Text(dollars(product.priceCents)).font(.headline.monospacedDigit()).foregroundStyle(Color.aeroInk)
                Text(product.category.categoryLabel).font(.caption).foregroundStyle(.secondary)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.white.opacity(0.8)))
        }
        .buttonStyle(.plain)
    }
}

struct AddItemSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var category = "desk"
    @State private var notes = ""
    @State private var photoItem: PhotosPickerItem?
    @State private var preview: UIImage?

    private let categories = ["bed", "nightstand", "dresser", "desk", "sofa", "coffee_table", "rug", "tv", "other"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    PhotosPicker(selection: $photoItem, matching: .images) {
                        if let preview {
                            Image(uiImage: preview).resizable().scaledToFill()
                                .frame(height: 160).clipped().clipShape(RoundedRectangle(cornerRadius: 12))
                        } else {
                            Label("Upload a photo", systemImage: "photo.badge.plus")
                        }
                    }
                } header: {
                    Text("Photo")
                } footer: {
                    Text("Optional. Helps the agent match style if you mention this item.")
                }
                Section("Item") {
                    TextField("Item name, e.g. oak desk", text: $name)
                    Picker("Category", selection: $category) {
                        ForEach(categories, id: \.self) { Text($0.categoryLabel).tag($0) }
                    }
                    TextField("Notes (optional)", text: $notes, axis: .vertical).lineLimit(2...4)
                }
            }
            .navigationTitle("Add your item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add item") { submit() }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        preview = UIImage(data: data)
                    }
                }
            }
        }
    }

    private func submit() {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        var text = "I already own a \(trimmed) (\(category.categoryLabel)) in \(model.currentRoomName)."
        if !notes.trimmingCharacters(in: .whitespaces).isEmpty { text += " \(notes)" }
        text += " Don’t buy another one."
        dismiss()
        Task {
            await model.sendChat(text)
            nav.roomTab = .inspiration
            nav.showSuccess(.itemAdded(trimmed))
        }
    }
}

struct SendMoneySheet: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @State private var selectedID: String?
    @State private var amountText = ""
    @State private var note = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Powered by Capital One Nessie (sandbox — no real money)", systemImage: "building.columns")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let purchaseBlocker = model.purchaseBlocker, model.actingMemberID == model.state.finance.payerID {
                    Section("Purchase first") {
                        Text(purchaseBlocker).font(.subheadline)
                        Button("Authorize purchase") { Task { await model.authorizePurchase(); dismiss() } }
                            .disabled(model.purchaseBlocker != nil)
                    }
                }
                Section("Pay to") {
                    if recipients.isEmpty {
                        Text("No one is owed a reimbursement yet. After the payer buys, shares show up here.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(recipients, id: \.liabilityID) { item in
                            Button {
                                selectedID = item.liabilityID
                                amountText = String(format: "%.2f", Double(item.amountCents) / 100)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(model.state.name(of: item.toMember)).foregroundStyle(Color.aeroInk)
                                        Text(dollars(item.amountCents)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if selectedID == item.liabilityID {
                                        Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.aeroSky)
                                    }
                                }
                            }
                        }
                    }
                }
                Section("Amount") {
                    TextField("0.00", text: $amountText).keyboardType(.decimalPad)
                    TextField("Note (optional), e.g. living room couch", text: $note)
                }
                if let error { Section { Text(error).foregroundStyle(Color.aeroRed) } }
            }
            .navigationTitle("Send money")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") { Task { await send() } }.disabled(selectedID == nil)
                }
            }
        }
        .onAppear {
            if let first = recipients.first {
                selectedID = first.liabilityID
                amountText = String(format: "%.2f", Double(first.amountCents) / 100)
            }
        }
    }

    private var recipients: [Reimbursement] {
        model.state.finance.reimbursements.filter { $0.fromMember == model.actingMemberID }
    }

    private func send() async {
        guard let id = selectedID, let item = recipients.first(where: { $0.liabilityID == id }) else { return }
        if let blocker = model.reimbursementBlocker(item) { error = blocker; return }
        await model.authorizeReimbursement(id)
        dismiss()
        nav.showSuccess(.paymentSent(amount: dollars(item.amountCents), to: model.state.name(of: item.toMember)))
    }
}

struct ShareSpaceSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    @State private var phones: [String: String] = [:]
    @State private var invitation: RoomInvitation?
    @State private var requestID = UUID().uuidString
    @State private var sending = false
    @State private var failure: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Invite roommates") {
                    Text("Enter everyone's number, including yours. Furnishare will text each person the same six-digit code to join this room. Reply to your individual conversation with furniture preferences and links.")
                    ForEach(model.state.members, id: \.id) { member in
                        TextField("\(member.name): +15551234567", text: Binding(
                            get: { phones[member.id] ?? "" },
                            set: { phones[member.id] = $0; requestID = UUID().uuidString; invitation = nil }
                        ))
                        .keyboardType(.phonePad)
                    }
                    Button(sending ? "Queuing…" : "Text invitations") {
                        Task { await invite() }
                    }
                    .disabled(sending || model.isOfflineDemo || (invitation != nil && invitation?.status != "failed" && invitation?.status != "partial"))
                    if model.isOfflineDemo { Text("Connect to the backend to invite roommates.").foregroundStyle(.secondary) }
                    if let failure { Text(failure).foregroundStyle(.red) }
                }
                if let invitation {
                    Section("Invitation") {
                        Text(invitation.status == "sent" ? "Invitations sent to every roommate." : "Delivery: \(invitation.status)")
                        if let recipients = invitation.recipients {
                            ForEach(Array(recipients.enumerated()), id: \.offset) { _, recipient in
                                Text("\(recipient.member_name): \(recipient.status)")
                            }
                        }
                        if let error = invitation.error { Text(error).foregroundStyle(.red) }
                        if let code = invitation.group_code {
                            Text(code).font(.largeTitle.monospaced().bold()).textSelection(.enabled)
                            Text("Enter this code in Join a group.")
                            Button("Copy group code") { UIPasteboard.general.string = code }
                        } else { Text("Create a new invitation to get a group code.") }
                        Button("Check delivery") {
                            Task {
                                do { self.invitation = try await model.client?.invitation(token: invitation.token) }
                                catch { failure = error.localizedDescription }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Share this space")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.large])
    }

    private func invite() async {
        guard let client = model.client else { return }
        if invitation?.status == "failed" || invitation?.status == "partial" { requestID = UUID().uuidString }
        sending = true; failure = nil
        defer { sending = false }
        let members = model.state.members.compactMap { member -> InviteMember? in
            let phone = (phones[member.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return phone.isEmpty ? nil : InviteMember(member_id: member.id, phone: phone)
        }
        do { invitation = try await client.invite(members: members, requestID: requestID) }
        catch { failure = error.localizedDescription }
    }
}

struct GroupSuggestionsPanel: View {
    @Environment(AppModel.self) private var model
    @State private var suggestions: [FurnitureSuggestion] = []
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Roommate furniture ideas").font(.headline)
            if let failure { Text(failure).foregroundStyle(.secondary) }
            if suggestions.isEmpty { Text("Share preferences or furniture links in your individual Photon conversation to see suggestions here.").foregroundStyle(.secondary) }
            ForEach(suggestions.reversed()) { suggestion in
                VStack(alignment: .leading, spacing: 6) {
                    Text(suggestion.member_name).font(.subheadline.bold())
                    Text(suggestion.text)
                    ForEach(suggestion.links, id: \.self) { link in
                        if let url = URL(string: link) { Link("Shared furniture link", destination: url) }
                    }
                    ForEach(Array(suggestion.products.enumerated()), id: \.offset) { _, product in
                        if let link = product.source_url, let url = URL(string: link) {
                            Link(product.title ?? "Furniture suggestion", destination: url)
                        } else { Text(product.title ?? "Furniture suggestion").font(.subheadline) }
                    }
                }
                Divider()
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 16).fill(Color.white))
        .task(id: "\(model.currentHouseholdID):\(model.state.stateVersion)") {
            suggestions = []
            guard let client = model.client else { return }
            do { suggestions = try await client.suggestions().suggestions; failure = nil }
            catch { failure = error.localizedDescription }
        }
    }
}

struct SuccessOverlay: View {
    @Environment(AppNavigation.self) private var nav
    let kind: SuccessKind

    var body: some View {
        ZStack {
            Color.black.opacity(0.35).ignoresSafeArea().onTapGesture { nav.dismissSuccess() }
            VStack(spacing: 16) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(Color.aeroGrass)
                Text(title).font(.title.bold()).foregroundStyle(Color.aeroInk)
                Text(detail).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                VStack(spacing: 10) {
                    Button(primaryTitle) { nav.dismissSuccess() }
                        .buttonStyle(AeroWideButtonStyle())
                    if case .itemAdded = kind {
                        Button("Keep adding") { nav.dismissSuccess(continueAdding: true) }
                            .buttonStyle(AeroWideButtonStyle(outlined: true))
                    }
                    if case .paymentSent = kind {
                        Button("View room budget") {
                            nav.dismissSuccess()
                            nav.roomTab = .budget
                            nav.screen = .room
                        }
                        .buttonStyle(AeroWideButtonStyle(outlined: true))
                    }
                    if case .roomsSaved = kind {
                        Button("Keep designing") { nav.dismissSuccess() }
                            .buttonStyle(AeroWideButtonStyle(outlined: true))
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: 400)
            .background(RoundedRectangle(cornerRadius: 28, style: .continuous).fill(Color.white))
            .shadow(color: .black.opacity(0.12), radius: 24, y: 10)
            .padding(24)
        }
        .accessibilityAddTraits(.isModal)
    }

    private var title: String {
        switch kind {
        case .roomsSaved: "Rooms saved"
        case .itemAdded: "Item added"
        case .paymentSent: "Payment sent"
        case .linkCopied: "Link copied"
        }
    }

    private var detail: String {
        switch kind {
        case .roomsSaved(let count):
            return "Your design list now includes \(count) room\(count == 1 ? "" : "s"). Open one to start furnishing."
        case .itemAdded(let name):
            return "“\(name)” was sent to the agent as something you already own. It will avoid buying a duplicate."
        case .paymentSent(let amount, let to):
            return "\(amount) to \(to). Nessie is a sandbox, so this is a simulated transfer."
        case .linkCopied:
            return "Paste it in Messages or Notes. Housemates already on the demo can open the same apartment."
        }
    }

    private var primaryTitle: String {
        switch kind {
        case .roomsSaved: "View all rooms"
        case .itemAdded: "View room"
        case .paymentSent: "Done"
        case .linkCopied: "Done"
        }
    }
}
