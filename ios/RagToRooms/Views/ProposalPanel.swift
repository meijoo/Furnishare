import SwiftUI

struct ProposalPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelHeader(title: "Proposal", symbol: "doc.text.magnifyingglass",
                        trailing: model.state.proposal.map { "v\($0.version)" })
            if let proposal = model.state.proposal {
                HStack {
                    StatusBadge(text: proposal.status.label, symbol: proposal.status.symbol)
                    Spacer()
                    Text(dollars(proposal.knownTotalCents)).font(.title3.bold().monospacedDigit())
                }
                VStack(spacing: 6) {
                    ForEach(proposal.items, id: \.productID) { item in itemRow(item) }
                }
                if !proposal.objections.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(proposal.objections.sorted(by: { $0.key < $1.key }), id: \.key) { member, reason in
                            Label("\(model.state.name(of: member))\(reason.isEmpty ? "" : ": \(reason)")",
                                  systemImage: "hand.raised.fill")
                                .font(.subheadline).foregroundStyle(Color.aeroInk)
                        }
                    }
                }
            }
        }
        .glassPanel()
    }

    private func itemRow(_ item: ProposalItem) -> some View {
        let object = model.displayedObjects.first { $0.category == item.category }
            ?? model.state.scene.objects.first { $0.productID == item.productID }
        let shown = object.flatMap { model.displayedProduct(for: $0) } ?? model.product(item.productID)
        let previewing = object.flatMap { model.previews[$0.objectID] }
        let isFocused = model.detailOriginalProductID == item.productID
            || (object.map { model.selectedObjectID == $0.objectID } ?? false)
        return VStack(alignment: .leading, spacing: 6) {
            Button {
                if let object { model.select(object.objectID) } else { model.select(nil); model.detailProductID = item.productID }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: item.category.categorySymbol).frame(width: 28).foregroundStyle(Color.aeroSky)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(shown?.title ?? item.title ?? item.productID)
                            .font(.subheadline.weight(.semibold)).lineLimit(2)
                        HStack(spacing: 6) {
                            Text(item.category.categoryLabel).font(.caption).foregroundStyle(.secondary)
                            if previewing != nil {
                                Text("Preview").font(.caption.weight(.semibold)).foregroundStyle(Color.aeroAmber)
                            } else if object.flatMap({ model.appliedPreviews[$0.objectID] }) != nil {
                                Text("Chosen").font(.caption.weight(.semibold)).foregroundStyle(Color.aeroGrass)
                            }
                        }
                    }
                    Spacer()
                    if object == nil { Image(systemName: "cube.transparent").foregroundStyle(.secondary).accessibilityLabel("Not placed in the room") }
                    Text((shown?.priceCents).map(dollars) ?? item.priceCents.map(dollars) ?? "Price unknown")
                        .font(.subheadline.monospacedDigit().weight(.semibold))
                }
                .foregroundStyle(Color.aeroInk)
                .padding(.vertical, 6).padding(.horizontal, 8)
                .background(RoundedRectangle(cornerRadius: 12).fill(isFocused ? Color.aeroSky.opacity(0.18) : .white.opacity(0.35)))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if let object, previewing != nil {
                HStack {
                    Button("Use this in the room") { model.applyPreview(objectID: object.objectID) }
                        .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
                    Button("Clear preview") { model.clearPreview(objectID: object.objectID) }
                        .buttonStyle(GlassChipStyle())
                }
                .padding(.leading, 38)
            }
        }
    }
}
