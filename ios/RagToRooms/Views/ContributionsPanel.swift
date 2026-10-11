import SwiftUI

struct ContributionsPanel: View {
    @Environment(AppModel.self) private var model
    @State private var showObjection = false
    @State private var objectionReason = ""

    var body: some View {
        let state = model.state
        VStack(alignment: .leading, spacing: 12) {
            PanelHeader(title: "Contributions", symbol: model.isPrivateScope ? "person.fill" : "person.3.fill")
            ForEach(state.members) { member in memberRow(member, proposal: state.proposal) }

            Divider()
            if let note = model.notInScopeNote {
                readOnlyNote(note)
            } else {
                actions
            }
        }
        .glassPanel()
        .alert("Object to this proposal", isPresented: $showObjection) {
            TextField("Reason (e.g. sofa is too big)", text: $objectionReason)
            Button("Cancel", role: .cancel) {}
            Button("Send objection") { Task { await model.object(reason: objectionReason) } }
        } message: {
            Text("The agent will revise the proposal with your reason.")
        }
    }

    /// Acting as someone outside this scope: explain instead of offering buttons that would 4xx.
    private func readOnlyNote(_ note: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(note, systemImage: "eye").font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk)
            if let owner = model.state.members.first {
                Button { model.setActingMember(owner.id) } label: { Label("Act as \(owner.name)", systemImage: "person.crop.circle") }
                    .buttonStyle(GlassChipStyle())
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.45)))
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder private var actions: some View {
        let state = model.state
        let me = model.actingMemberID
        VStack(alignment: .leading, spacing: 12) {
            FlowButtons {
                action("Approve", symbol: "hand.thumbsup.fill", tint: .aeroGrass, key: "approve", blocker: model.approvalBlocker) {
                    Task { await model.approve() }
                }
                action("Object", symbol: "hand.raised.fill", tint: .aeroAmber, key: "object", blocker: model.objectionBlocker) {
                    objectionReason = ""; showObjection = true
                }

            }
            blockerText(model.approvalBlocker.map { "Approve: \($0)" })

            FlowButtons {
                action("Buy", symbol: "creditcard.fill", tint: .aeroSky, key: "purchase", blocker: model.purchaseBlocker) {
                    Task { await model.authorizePurchase() }
                }
            }
            blockerText(model.purchaseBlocker)

            let mine = state.finance.reimbursements.filter { $0.fromMember == me }
            ForEach(mine, id: \.liabilityID) { r in
                let blocker = model.reimbursementBlocker(r)
                FlowButtons {
                    action("Pay \(dollars(r.amountCents))",
                           symbol: "arrow.uturn.left.circle.fill", tint: .aeroGrass, key: "reimb-\(r.liabilityID)", blocker: blocker) {
                        Task { await model.authorizeReimbursement(r.liabilityID) }
                    }
                }
                blockerText(blocker)
            }
        }
    }

    static func cents(from text: String) -> Int? {
        let cleaned = text.replacingOccurrences(of: "$", with: "").replacingOccurrences(of: ",", with: "")
            .trimmingCharacters(in: .whitespaces)
        guard let value = Decimal(string: cleaned), value >= 0 else { return nil }
        var scaled = value * 100, rounded = Decimal()
        NSDecimalRound(&rounded, &scaled, 0, .plain)
        return NSDecimalNumber(decimal: rounded).intValue
    }

    private func memberRow(_ member: Member, proposal: Proposal?) -> some View {
        let approved = proposal?.approvals[member.id] == true
        let objection = proposal?.objections[member.id]
        return HStack(spacing: 10) {
            Image(systemName: member.id == model.actingMemberID ? "person.crop.circle.fill" : "person.crop.circle")
                .font(.title2).foregroundStyle(Color.aeroSky)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(member.name).font(.headline)
                    if member.isPayer { StatusBadge(text: "Payer", symbol: "creditcard", tint: .aeroInk) }
                    if member.id == model.actingMemberID { Text("you").font(.caption).foregroundStyle(.secondary) }

                }
                if let cents = member.contributionBudgetCents ?? member.limitCents {
                    Text("Budget: \(dollars(cents))").font(.subheadline).foregroundStyle(Color.figmaMuted)
                } else {
                    Text("Budget not set").font(.subheadline).foregroundStyle(Color.figmaMuted)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(proposal?.shares[member.id].map(dollars) ?? "—").font(.headline.monospacedDigit())
                if approved {
                    StatusBadge(text: "Approved", symbol: "checkmark.seal.fill", tint: Color(red: 0.13, green: 0.5, blue: 0.2))
                } else if objection != nil {
                    StatusBadge(text: "Objected", symbol: "hand.raised.fill", tint: .aeroRed)
                } else if proposal != nil {
                    StatusBadge(text: "Pending", symbol: "hourglass", tint: .aeroInk)
                }
            }
        }
        .foregroundStyle(Color.aeroInk)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(member.id == model.actingMemberID ? 0.6 : 0.3)))
    }

    private func action(_ title: String, symbol: String, tint: Color, key: String, blocker: String?, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            HStack(spacing: 6) {
                if model.busy.contains(key) { ProgressView().tint(.white) } else { Image(systemName: symbol) }
                Text(title)
            }
        }
        .buttonStyle(AeroButtonStyle(tint: tint, compact: true))
        .disabled(blocker != nil || model.busy.contains(key))
    }

    @ViewBuilder private func blockerText(_ text: String?) -> some View {
        if let text { Label(text, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary) }
    }
}

/// Lays out buttons horizontally, wrapping to a vertical stack when space runs out.
struct FlowButtons<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { content }
            VStack(alignment: .leading, spacing: 8) { content }
        }
    }
}
