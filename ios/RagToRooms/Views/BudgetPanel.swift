import Charts
import SwiftUI

struct BudgetPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @State private var showEdit = false
    @State private var budgetText = ""

    private var budget: Int? { model.state.budgetCents }
    private var spent: Int { model.state.proposal?.knownTotalCents ?? 0 }
    private var remaining: Int { (budget ?? 0) - spent }
    private var progress: Double {
        guard let budget, budget > 0 else { return spent > 0 ? 1 : 0 }
        return min(1, Double(spent) / Double(budget))
    }

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 16) {
                roomCard
                sharedCard
            }
            VStack(spacing: 16) {
                roomCard
                sharedCard
            }
        }
        .alert("Edit room budget", isPresented: $showEdit) {
            TextField("Amount in USD, e.g. 1500", text: $budgetText).keyboardType(.decimalPad)
            Button("Cancel", role: .cancel) {}
            Button("Save") {
                if let cents = ContributionsPanel.cents(from: budgetText) {
                    Task { await model.setBudget(cents: cents) }
                } else {
                    model.errorMessage = "Enter a dollar amount like 1500 or 800.50"
                }
            }
        }
    }

    private var roomCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Room budget").font(.title2.bold()).foregroundStyle(Color.aeroInk)
                Spacer()
                Button {
                    budgetText = budget.map { String(format: "%.2f", Double($0) / 100) } ?? ""
                    showEdit = true
                } label: {
                    Text(budget == nil ? "Set budget" : "Edit budget")
                }
                .buttonStyle(OutlinePillStyle())
                .disabled(model.busy.contains("budget"))
            }
            if let budget {
                Text("\(dollars(spent)) / \(dollars(budget))")
                    .font(.system(size: 34, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(remaining >= 0 ? Color.aeroInk : Color.aeroRed)
            } else {
                Text(dollars(spent))
                    .font(.system(size: 34, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(Color.aeroInk)
            }
            HStack(spacing: 12) {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color.figmaWash)
                        Capsule().fill(remaining >= 0 ? Color.aeroSky : Color.aeroRed)
                            .frame(width: max(8, geo.size.width * progress))
                    }
                }
                .frame(height: 10)
                Text("\(Int((progress * 100).rounded()))%")
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(Color.figmaMuted)
                    .frame(width: 44, alignment: .trailing)
            }
            breakdown
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).strokeBorder(Color.black.opacity(0.04), lineWidth: 1))
    }

    private var breakdown: some View {
        let slices = spendingSlices
        return VStack(alignment: .leading, spacing: 12) {
            Text("Spending breakdown").font(.title3.bold()).foregroundStyle(Color.aeroInk)
            HStack(alignment: .center, spacing: 20) {
                Chart(slices) { slice in
                    SectorMark(angle: .value(slice.label, max(slice.cents, 0)), innerRadius: .ratio(0.62), angularInset: 1.5)
                        .foregroundStyle(slice.color)
                        .cornerRadius(4)
                }
                .frame(width: 120, height: 120)
                .chartLegend(.hidden)
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(slices) { slice in
                        HStack(spacing: 10) {
                            Circle().fill(slice.color).frame(width: 10, height: 10)
                            Text(slice.label).font(.subheadline).foregroundStyle(Color.aeroInk)
                            Spacer()
                            Text(dollars(slice.cents)).font(.subheadline.monospacedDigit().weight(.semibold))
                                .foregroundStyle(Color.aeroInk)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var sharedCard: some View {
        let shares = model.state.proposal?.shares ?? [:]
        VStack(alignment: .leading, spacing: 16) {
            Text("Shared expenses").font(.title2.bold()).foregroundStyle(Color.aeroInk)
            if model.isPrivateScope || shares.isEmpty {
                Text(model.isPrivateScope ? "This room is private." : "Split appears after a proposal.")
                    .font(.subheadline)
                    .foregroundStyle(Color.figmaMuted)
            } else {
                ForEach(model.state.members, id: \.id) { member in
                    sharedRow(member, cents: shares[member.id] ?? 0)
                }
            }
            Button { nav.showSendMoney = true } label: {
                Label("Split expense", systemImage: "person.2")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(AeroWideButtonStyle(outlined: true))
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).strokeBorder(Color.black.opacity(0.04), lineWidth: 1))
    }

    private func sharedRow(_ member: Member, cents: Int) -> some View {
        let mine = member.id == model.actingMemberID
        return HStack(spacing: 12) {
            ZStack {
                Circle().fill(Color.figmaWash)
                Text(String(member.name.prefix(1)))
                    .font(.headline)
                    .foregroundStyle(Color.aeroInk)
            }
            .frame(width: 40, height: 40)
            Text(mine ? "You (\(member.name))" : member.name)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.aeroInk)
            Spacer()
            Text(dollars(cents))
                .font(.subheadline.monospacedDigit().weight(.semibold))
                .foregroundStyle(Color.aeroInk)
            if mine {
                Button("Pay") { nav.showSendMoney = true }
                    .buttonStyle(OutlinePillStyle(tint: .aeroSky))
            } else {
                Button("Request") { nav.showSendMoney = true }
                    .buttonStyle(OutlinePillStyle())
            }
        }
    }

    private var spendingSlices: [SpendSlice] {
        var furniture = 0, decor = 0, lighting = 0
        for item in model.state.proposal?.items ?? [] {
            guard let cents = item.priceCents else { continue }
            switch item.category {
            case "rug": decor += cents
            case "tv", "other": lighting += cents
            default: furniture += cents
            }
        }
        let leftover = max(0, remaining)
        return [
            SpendSlice(id: "furniture", label: "Furniture", cents: furniture, color: Color.aeroSky),
            SpendSlice(id: "decor", label: "Decor", cents: decor, color: Color.aeroAmber),
            SpendSlice(id: "lighting", label: "Lighting", cents: lighting, color: Color.aeroGrass),
            SpendSlice(id: "remaining", label: "Remaining", cents: leftover, color: Color(white: 0.86)),
        ].filter { $0.cents > 0 || $0.id == "remaining" }
    }
}

private struct SpendSlice: Identifiable {
    let id: String
    let label: String
    let cents: Int
    let color: Color
}

struct OutlinePillStyle: ButtonStyle {
    var tint: Color = .aeroSky

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Capsule().strokeBorder(tint, lineWidth: 1.5))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}
