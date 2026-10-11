import SwiftUI

struct ProductDetailPanel: View {
    @Environment(AppModel.self) private var model

    var showAlternatives = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let product = model.detailProduct {
                if let objectID = model.selectedObjectID, model.previews[objectID] != nil {
                    HStack {
                        Label("Preview", systemImage: "eye")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk)
                        Spacer()
                        Button("Clear") { model.clearPreview(objectID: objectID) }.buttonStyle(GlassChipStyle())
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.aeroAmber.opacity(0.2)))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.aeroAmber.opacity(0.6)))
                }
                details(product)
                if showAlternatives && product.sourceType != "owned" { alternatives(for: product) }
            } else if let object = model.selectedObject {
                Text(format(object.dimensionsM)).foregroundStyle(Color.figmaMuted)
            }
        }
        .id("product")
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
                    if product.sourceType == "owned" {
                        Text("Owned").font(.title3.weight(.semibold))
                    } else {
                        Text(dollars(product.priceCents)).font(.title2.bold().monospacedDigit())
                    }
                }
                .foregroundStyle(Color.aeroInk)
            }
            if let d = product.placeableDimensions {
                Label(format(d), systemImage: "ruler").font(.subheadline.weight(.medium))
            }
            if let url = product.sourceURL.flatMap(URL.init(string:)) {
                Link(destination: url) { Label("Open", systemImage: "safari") }
                    .buttonStyle(AeroButtonStyle(compact: true))
            }
        }
        .foregroundStyle(Color.aeroInk)
    }

    @ViewBuilder private func alternatives(for product: Product) -> some View {
        let options = model.alternatives(for: product)
        let originalID = model.detailOriginalProductID
        if !options.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(product.category.categoryLabel).font(.headline).foregroundStyle(Color.aeroInk)
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(options) { alt in alternativeCard(alt, originalID: originalID) }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
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
            if let objectID, placeable {
                if alt.id == originalID {
                    Button("Original") { model.clearPreview(objectID: objectID) }.buttonStyle(GlassChipStyle())
                } else {
                    Button { model.setPreview(objectID: objectID, productID: alt.id) } label: { Label("Preview", systemImage: "eye") }
                        .buttonStyle(AeroButtonStyle(tint: .aeroAmber, compact: true))
                }
            }
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .frame(width: 170)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.45)))
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
