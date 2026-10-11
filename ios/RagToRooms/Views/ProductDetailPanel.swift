import SwiftUI

struct ProductDetailPanel: View {
    @Environment(AppModel.self) private var model

    var showAlternatives = true
    var optionObjectID: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let product = model.detailProduct {
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
        if let objectID = optionObjectID ?? model.selectedObjectID {
            let options = model.designOptions(for: product, objectID: objectID)
            if !options.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(product.category.categoryLabel).font(.headline).foregroundStyle(Color.aeroInk)
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(options) { alt in alternativeCard(alt, current: product, objectID: objectID) }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
            }
            }
        }
    }

    private func alternativeCard(_ alt: Product, current: Product, objectID: String) -> some View {
        let showing = alt.id == current.id
        return VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .topTrailing) {
                ProductImage(urls: model.imageURLs(for: alt), category: alt.category)
                    .frame(width: 120, height: 88)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                Button {
                    model.removeDesignOption(alt, objectID: objectID, current: current)
                } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.white).shadow(radius: 1)
                }
                .buttonStyle(.plain)
                .padding(4)
                .accessibilityLabel("Remove \(alt.title)")
            }
            Text(alt.title).font(.caption.weight(.semibold)).lineLimit(2).foregroundStyle(Color.aeroInk)
            Text(dollars(alt.priceCents)).font(.caption.monospacedDigit()).foregroundStyle(Color.figmaMuted)
            Text(showing ? "Showing" : "Show")
                .font(.caption.weight(.semibold))
                .foregroundStyle(showing ? Color.aeroSky : Color.aeroInk)
        }
        .frame(width: 120, alignment: .leading)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 14)
            .strokeBorder(showing ? Color.aeroSky : Color.black.opacity(0.06), lineWidth: showing ? 2 : 1))
        .onTapGesture { model.chooseDesignOption(alt, objectID: objectID) }
        .accessibilityLabel("Show \(alt.title)")
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
