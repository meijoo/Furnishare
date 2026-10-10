import SwiftUI

struct ProductDetailPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelHeader(title: "Product evidence", symbol: "checkmark.rectangle.stack")
            if let product = model.detailProduct {
                if let objectID = model.selectedObjectID, model.previews[objectID] != nil {
                    HStack {
                        Label("Preview: local only, not proposed or saved", systemImage: "eye")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk)
                        Spacer()
                        Button("Clear preview") { model.clearPreview(objectID: objectID) }.buttonStyle(GlassChipStyle())
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.aeroAmber.opacity(0.2)))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.aeroAmber.opacity(0.6)))
                }
                details(product)
                alternatives(for: product)
            } else if let object = model.selectedObject {
                Label("No catalog entry for \(object.productID). Showing scene dimensions only: \(format(object.dimensionsM)).",
                      systemImage: "questionmark.square.dashed").foregroundStyle(.secondary)
            } else {
                Label("Tap furniture in the room or an item in the proposal to see its photo, dimensions and evidence.",
                      systemImage: "hand.tap").foregroundStyle(.secondary)
            }
        }
        .glassPanel()
    }

    private func details(_ product: Product) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 14) {
                ProductImage(urls: model.imageURLs(for: product), category: product.category)
                    .frame(width: 150, height: 150)
                VStack(alignment: .leading, spacing: 4) {
                    Text(product.retailer.uppercased()).font(.caption.weight(.heavy)).tracking(1.5).foregroundStyle(Color.aeroSky)
                    Text(product.title).font(.title3.bold())
                    if let variant = product.variant { Text(variant).font(.subheadline).foregroundStyle(.secondary) }
                    Text(dollars(product.priceCents)).font(.title2.bold().monospacedDigit())
                    sourceBadge(product.sourceType)
                }
                .foregroundStyle(Color.aeroInk)
            }
            if let d = product.placeableDimensions {
                Label("Assembled: \(format(d))", systemImage: "ruler").font(.subheadline.weight(.medium))
            } else {
                Label("Assembled dimensions not confirmed (\(product.dimensionKind ?? "unknown")); not used in the layout",
                      systemImage: "exclamationmark.triangle").font(.subheadline.weight(.medium)).foregroundStyle(Color.aeroAmber)
            }
            if let unknown = product.additionalCosts?.unknownNames, !unknown.isEmpty {
                Label("Unknown extra costs: \(unknown.joined(separator: ", "))", systemImage: "questionmark.circle").font(.caption)
            }
            if let evidence = product.evidence, !evidence.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Evidence").font(.caption.weight(.bold)).foregroundStyle(.secondary)
                    ForEach(evidence, id: \.self) { item in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("“\(item.quote)”").font(.subheadline.italic())
                            HStack {
                                Text(item.field).font(.caption2.monospaced()).foregroundStyle(.secondary)
                                if let url = item.sourceURL.flatMap(URL.init(string:)) {
                                    Link("source", destination: url).font(.caption2)
                                }
                            }
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 10).fill(.white.opacity(0.5)))
                    }
                }
            }
            HStack {
                if let url = product.sourceURL.flatMap(URL.init(string:)) {
                    Link(destination: url) { Label("Open product page", systemImage: "safari") }
                        .buttonStyle(AeroButtonStyle(compact: true))
                }
                Spacer()
            }
            Label("3D appearance is approximate. Footprint and height use the dimensions above.", systemImage: "cube.transparent")
                .font(.caption).foregroundStyle(.secondary)
        }
        .foregroundStyle(Color.aeroInk)
    }

    @ViewBuilder private func alternatives(for product: Product) -> some View {
        let options = model.alternatives(for: product)
        let originalID = model.detailOriginalProductID
        if !options.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Alternatives: \(product.category.categoryLabel)").font(.caption.weight(.bold)).foregroundStyle(.secondary)
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(options) { alt in alternativeCard(alt, originalID: originalID) }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
                Text("Preview swaps are local only; nothing is proposed or purchased.").font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private func alternativeCard(_ alt: Product, originalID: String?) -> some View {
        let objectID = model.selectedObjectID
        let placeable = alt.placeableDimensions != nil
        return VStack(alignment: .leading, spacing: 6) {
            ProductImage(urls: model.imageURLs(for: alt), category: alt.category)
                .frame(height: 80)
            Text(alt.title).font(.subheadline.weight(.semibold)).lineLimit(1)
            Text(dollars(alt.priceCents)).font(.caption.monospacedDigit())
            Text(alt.placeableDimensions.map(format) ?? "No assembled size").font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            if let objectID, placeable {
                if alt.id == originalID {
                    Button("Back to proposed") { model.clearPreview(objectID: objectID) }.buttonStyle(GlassChipStyle())
                } else {
                    Button { model.setPreview(objectID: objectID, productID: alt.id) } label: { Label("Preview", systemImage: "eye") }
                        .buttonStyle(AeroButtonStyle(tint: .aeroAmber, compact: true))
                }
            } else {
                Text(placeable ? "Select it in the room to preview" : "Can't place").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .frame(width: 170)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.45)))
    }

    private func sourceBadge(_ type: String?) -> some View {
        switch type {
        case "verified": StatusBadge(text: "Verified catalog", symbol: "checkmark.shield")
        case "live": StatusBadge(text: "Live search result", symbol: "globe")
        default: StatusBadge(text: "Demo fixture (fictional)", symbol: "shippingbox", tint: .aeroAmber)
        }
    }

    private func format(_ d: Dimensions) -> String {
        String(format: "%.2f W × %.2f D × %.2f H m", d.width, d.depth, d.height)
    }
}

struct ProductImage: View {
    let urls: [URL]
    let category: String
    @State private var attempt = 0

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12).fill(.white.opacity(0.7))
            if attempt < urls.count {
                AsyncImage(url: urls[attempt]) { phase in
                    switch phase {
                    case .success(let image): image.resizable().scaledToFit().padding(4)
                    case .failure: ProgressView().onAppear { attempt += 1 }
                    default: ProgressView()
                    }
                }
                .id(urls[attempt])
            } else {
                fallback
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .onChange(of: urls) { attempt = 0 }
    }

    private var fallback: some View {
        Image(systemName: category.categorySymbol).font(.system(size: 36)).foregroundStyle(Color.aeroSky.opacity(0.7))
            .accessibilityLabel("No product photo")
    }
}
