import SwiftUI

struct ProposalPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelHeader(title: "Proposal", symbol: "doc.text.magnifyingglass",
                        trailing: model.state.proposal.map { "Version \($0.version)" })
            if let proposal = model.state.proposal {
                HStack {
                    StatusBadge(text: proposal.status.label, symbol: proposal.status.symbol)
                    Spacer()
                    if let budget = model.state.budgetCents {
                        Text("Budget \(dollars(budget))").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                VStack(spacing: 6) {
                    ForEach(proposal.items, id: \.productID) { item in itemRow(item) }
                }
                Divider()
                HStack {
                    Text("Known total").font(.headline)
                    Spacer()
                    Text(dollars(proposal.knownTotalCents)).font(.title3.bold().monospacedDigit())
                }
                .foregroundStyle(Color.aeroInk)
                if let budget = model.state.budgetCents {
                    let remaining = budget - proposal.knownTotalCents
                    Label(remaining >= 0 ? "\(dollars(remaining)) under budget (before unknown costs)" : "\(dollars(-remaining)) over budget",
                          systemImage: remaining >= 0 ? "checkmark.circle" : "exclamationmark.triangle")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(remaining >= 0 ? Color(red: 0.13, green: 0.5, blue: 0.2) : .aeroRed)
                }
                if !proposal.unknownCosts.isEmpty {
                    Label("Not included, unknown: \(proposal.unknownCosts.map { $0.capitalized }.joined(separator: ", "))",
                          systemImage: "questionmark.circle")
                        .font(.subheadline.weight(.medium)).foregroundStyle(Color.aeroInk)
                }
                if !proposal.objections.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(proposal.objections.sorted(by: { $0.key < $1.key }), id: \.key) { member, reason in
                            Label("\(model.state.name(of: member)) objected\(reason.isEmpty ? "" : ": “\(reason)”")",
                                  systemImage: "hand.raised.fill")
                                .font(.subheadline).foregroundStyle(Color.aeroInk)
                        }
                    }
                }
                if let explanation = proposal.explanation, !explanation.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Label("Agent's reasoning", systemImage: "sparkles").font(.caption.weight(.bold)).foregroundStyle(Color.aeroSky)
                        Text(explanation).font(.subheadline).foregroundStyle(Color.aeroInk).fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.55)))
                }
            } else {
                Label("No proposal yet. Ask the agent in the chat below, e.g. “\(model.chatSuggestion)”",
                      systemImage: "text.bubble").foregroundStyle(.secondary)
            }
        }
        .glassPanel()
    }

    private func itemRow(_ item: ProposalItem) -> some View {
        let product = model.product(item.productID)
        let object = model.state.scene.objects.first { $0.productID == item.productID }
        let isFocused = model.detailOriginalProductID == item.productID
        return Button {
            if let object { model.select(object.objectID) } else { model.select(nil); model.detailProductID = item.productID }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: item.category.categorySymbol).frame(width: 28).foregroundStyle(Color.aeroSky)
                VStack(alignment: .leading, spacing: 1) {
                    Text(product?.title ?? item.title ?? item.productID).font(.subheadline.weight(.semibold)).lineLimit(1)
                    Text([item.category.categoryLabel, product?.retailer].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if object == nil { Image(systemName: "cube.transparent").foregroundStyle(.secondary).accessibilityLabel("Not placed in the room") }
                Text(item.priceCents.map(dollars) ?? "Price unknown").font(.subheadline.monospacedDigit().weight(.semibold))
            }
            .foregroundStyle(Color.aeroInk)
            .padding(.vertical, 6).padding(.horizontal, 8)
            .background(RoundedRectangle(cornerRadius: 12).fill(isFocused ? Color.aeroSky.opacity(0.18) : .white.opacity(0.35)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
