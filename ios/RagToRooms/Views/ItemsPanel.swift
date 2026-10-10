import SwiftUI

struct ItemsPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        VStack(spacing: 16) {
            owned
            if model.state.proposal != nil { ProposalPanel().id("proposal") }
            if model.detailProduct != nil || model.selectedObject != nil { ProductDetailPanel().id("product") }
        }
    }

    private var owned: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelHeader(title: "Owned", symbol: "photo.on.rectangle")
            HStack {
                Button { nav.showAddItem = true } label: { Label("Add", systemImage: "plus") }
                    .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
                Button { nav.showCatalog = true } label: { Label("Catalog", systemImage: "square.grid.2x2") }
                    .buttonStyle(AeroButtonStyle(compact: true))
            }
            if !model.currentOwnedItems.isEmpty {
                ForEach(model.currentOwnedItems) { item in
                    ownedRow(item)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassPanel()
    }

    private func ownedRow(_ item: OwnedItem) -> some View {
        HStack(spacing: 12) {
            ownedThumb(item)
                .frame(width: 64, height: 64)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(item.name).font(.headline).foregroundStyle(Color.aeroInk)
                Text(sizeLine(item)).font(.subheadline).foregroundStyle(Color.figmaMuted)
                if let link = item.link, let url = URL(string: link) {
                    Link(destination: url) { Text(url.host ?? link).lineLimit(1) }
                }
            }
            Spacer()
            Button {
                model.removeOwnedItem(item.id)
            } label: {
                Image(systemName: "trash").accessibilityLabel("Remove \(item.name)")
            }
            .buttonStyle(GlassChipStyle())
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.figmaWash.opacity(0.6)))
    }

    private func sizeLine(_ item: OwnedItem) -> String {
        guard let w = item.widthM, let d = item.depthM, let h = item.heightM else {
            return item.category.categoryLabel
        }
        let inches: (Double) -> String = { String(format: "%.0f\"", $0 / 0.0254) }
        return "\(item.category.categoryLabel) · \(inches(w)) × \(inches(d)) × \(inches(h))"
    }

    @ViewBuilder private func ownedThumb(_ item: OwnedItem) -> some View {
        if let url = model.ownedImageURL(item) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image): image.resizable().scaledToFill()
                default:
                    Image(systemName: item.category.categorySymbol)
                        .foregroundStyle(Color.aeroSky)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.white)
                }
            }
        } else {
            Image(systemName: item.category.categorySymbol)
                .foregroundStyle(Color.aeroSky)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.white)
        }
    }
}
