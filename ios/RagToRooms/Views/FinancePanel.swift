import SwiftUI

struct FinancePanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let finance = model.state.finance
        let state = model.state
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                PanelHeader(title: "Purchase & reimbursements", symbol: "banknote")
                if finance.isMock || model.isOfflineDemo {
                    StatusBadge(text: "Simulated (mock)", symbol: "theatermasks", tint: .aeroAmber)
                } else if let simulator = finance.simulator {
                    StatusBadge(text: "Nessie sandbox (\(simulator))", symbol: "building.columns", tint: .aeroInk)
                }
            }
            if finance.settled {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.seal.fill").font(.title)
                    VStack(alignment: .leading) {
                        Text("Settled").font(.title3.bold())
                        Text(model.isPrivateScope ? "The purchase is confirmed. Nobody owes anyone for this room."
                             : "The purchase and every reimbursement are confirmed.").font(.subheadline)
                    }
                }
                .foregroundStyle(.white)
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 16).fill(LinearGradient(colors: [.aeroGrass, Color(red: 0.2, green: 0.6, blue: 0.25)], startPoint: .top, endPoint: .bottom)))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(0.7)))
                .accessibilityElement(children: .combine)
            }
            OperationRow(title: "Purchase",
                         subtitle: "\(state.name(of: finance.payerID)) pays the retailer\(model.isPrivateScope ? " (100%, private room)" : "")",
                         amountCents: finance.purchase?.amountCents ?? state.proposal?.knownTotalCents, operation: finance.purchase)
            if model.isPrivateScope {
                Label("Private room: no reimbursements. The room is settled once the purchase is confirmed.", systemImage: "lock.fill")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(finance.reimbursements, id: \.liabilityID) { r in
                    OperationRow(title: "Reimbursement", subtitle: "\(state.name(of: r.fromMember)) → \(state.name(of: r.toMember))",
                                 amountCents: r.amountCents, operation: r.operation)
                }
                if finance.reimbursements.isEmpty {
                    Text("Reimbursements are created after the purchase is confirmed.").font(.caption).foregroundStyle(.secondary)
                }
            }
            if Self.needsReconcile(finance) && !model.isOfflineDemo {
                Button { Task { await model.reconcile() } } label: {
                    Label("Re-check pending transfers", systemImage: "arrow.clockwise")
                }
                .buttonStyle(GlassChipStyle())
                .disabled(model.busy.contains("reconcile"))
            }
        }
        .glassPanel()
    }

    private static func needsReconcile(_ finance: Finance) -> Bool {
        var operations: [FinancialOperation] = finance.reimbursements.compactMap(\.operation)
        if let purchase = finance.purchase { operations.append(purchase) }
        let open: Set<OperationState> = [.pending, .unknown, .submitting]
        return operations.contains { open.contains($0.state) }
    }
}

private struct OperationRow: View {
    let title: String
    let subtitle: String
    let amountCents: Int?
    let operation: FinancialOperation?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(subtitle).font(.subheadline).foregroundStyle(.secondary)
                if let error = operation?.error, !error.isEmpty {
                    Label(error, systemImage: "exclamationmark.bubble").font(.caption).foregroundStyle(Color.aeroRed)
                }
                if let id = operation?.externalID {
                    Text("Ref \(id)").font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                if let amountCents { Text(dollars(amountCents)).font(.headline.monospacedDigit()) }
                if let operation {
                    StatusBadge(text: operation.state.label, symbol: operation.state.symbol, tint: operation.state.tint)
                    if operation.isMock { StatusBadge(text: "Simulated (mock)", symbol: "theatermasks", tint: .aeroAmber) }
                } else {
                    StatusBadge(text: "Not authorized", symbol: "circle.dashed", tint: .secondary)
                }
            }
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.4)))
        .accessibilityElement(children: .combine)
    }
}
