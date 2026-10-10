import PhotosUI
import SwiftUI

struct InspirationPanel: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""
    @State private var photoItem: PhotosPickerItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PanelHeader(title: "Inspiration", symbol: "sparkles",
                        trailing: model.inspirationCategory?.categoryLabel)
            photos
            TextField("Search sofas, beds, lamps…", text: $draft, axis: .vertical)
                .lineLimit(1...3)
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color.figmaWash))
                .onSubmit(search)
            HStack {
                Button(action: search) {
                    if model.busy.contains("inspiration-search") {
                        ProgressView().tint(.white)
                    } else {
                        Label("Search", systemImage: "magnifyingglass")
                    }
                }
                .buttonStyle(AeroButtonStyle(compact: true))
                .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty || model.busy.contains("inspiration-search"))
                if !model.inspirationPicks.isEmpty {
                    Text("\(model.inspirationPicks.count)/10")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.aeroInk)
                }
                Spacer()
            }
            if !model.inspirationPicks.isEmpty {
                picks
            }
            results
        }
        .glassPanel()
        .onChange(of: photoItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                    model.addInspirationPhoto(image)
                }
                photoItem = nil
            }
        }
    }

    private var photos: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Photos").font(.headline).foregroundStyle(Color.aeroInk)
            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    PhotosPicker(selection: $photoItem, matching: .images) {
                        VStack(spacing: 6) {
                            Image(systemName: "plus")
                                .font(.title2.weight(.semibold))
                                .foregroundStyle(Color.aeroSky)
                            Text("Add").font(.caption.weight(.semibold)).foregroundStyle(Color.aeroInk)
                        }
                        .frame(width: 88, height: 88)
                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.figmaWash))
                    }
                    .buttonStyle(.plain)
                    ForEach(model.inspirationShots) { shot in
                        ZStack(alignment: .topTrailing) {
                            AsyncImage(url: model.inspirationURL(shot)) { phase in
                                switch phase {
                                case .success(let image): image.resizable().scaledToFill()
                                default: Color.figmaWash
                                }
                            }
                            .frame(width: 88, height: 88)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            Button {
                                model.removeInspirationShot(shot.id)
                            } label: {
                                Image(systemName: "xmark.circle.fill").foregroundStyle(.white)
                            }
                            .padding(4)
                            .accessibilityLabel("Remove photo")
                        }
                    }
                    if let preview = model.inspirationPreview, model.inspirationShots.isEmpty {
                        Image(uiImage: preview).resizable().scaledToFill()
                            .frame(width: 88, height: 88)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    } else if let url = model.client?.resolve(model.state.room.inspirationImageURL), model.inspirationShots.isEmpty {
                        AsyncImage(url: url) { phase in
                            switch phase {
                            case .success(let image): image.resizable().scaledToFill()
                            default: Color.figmaWash
                            }
                        }
                        .frame(width: 88, height: 88)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                }
            }
            .scrollIndicators(.hidden)
        }
    }

    private var picks: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Picks").font(.headline).foregroundStyle(Color.aeroInk)
            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    ForEach(model.inspirationPicks, id: \.self) { id in
                        if let product = model.product(id) {
                            card(product, picked: true)
                        }
                    }
                }
                .padding(2)
            }
            .scrollIndicators(.hidden)
        }
    }

    @ViewBuilder private var results: some View {
        if model.inspirationResults.isEmpty {
            if model.busy.contains("inspiration-search") {
                ProgressView().frame(maxWidth: .infinity).padding(.vertical, 24)
            } else if !model.inspirationQuery.isEmpty {
                Text("No matches").foregroundStyle(Color.figmaMuted)
            }
        } else {
            Text(model.inspirationCategory?.categoryLabel ?? "Results")
                .font(.headline)
                .foregroundStyle(Color.aeroInk)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 168), spacing: 12)], spacing: 12) {
                ForEach(model.inspirationResults) { product in
                    card(product, picked: model.inspirationPicks.contains(product.id))
                }
            }
        }
    }

    private func card(_ product: Product, picked: Bool) -> some View {
        let objectID = model.objectID(forCategory: product.category)
        let canPlace = product.placeableDimensions != nil
        let showing = objectID.map { model.previews[$0] == product.id || model.displayedObjects.contains { $0.productID == product.id } } ?? false
        return VStack(alignment: .leading, spacing: 8) {
            ZStack(alignment: .topTrailing) {
                ProductImage(urls: model.imageURLs(for: product), category: product.category)
                    .frame(height: 110)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Button {
                    model.toggleInspirationPick(product.id)
                } label: {
                    Image(systemName: picked ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(picked ? Color.aeroSky : Color.white)
                        .shadow(radius: 2)
                }
                .buttonStyle(.plain)
                .padding(6)
                .accessibilityLabel(picked ? "Deselect \(product.title)" : "Select \(product.title)")
            }
            Text(product.title).font(.subheadline.weight(.semibold)).lineLimit(2).foregroundStyle(Color.aeroInk)
            if let dims = product.placeableDimensions {
                Text(dims.listingLabel).font(.caption.monospacedDigit()).foregroundStyle(Color.figmaMuted)
            }
            Text(dollars(product.priceCents)).font(.headline.monospacedDigit()).foregroundStyle(Color.aeroInk)
            HStack(spacing: 10) {
                Button {
                    model.toggleInspirationPick(product.id)
                } label: {
                    Text(picked ? "Selected" : "Select")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Color.aeroInk)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Capsule().strokeBorder(Color.black.opacity(0.12), lineWidth: 1))
                }
                .buttonStyle(.plain)
                .disabled(!picked && model.inspirationPicks.count >= 10)
                Spacer(minLength: 0)
                if canPlace {
                    Button {
                        if !picked { model.toggleInspirationPick(product.id) }
                        model.previewInspiration(product.id)
                    } label: {
                        Image(systemName: showing ? "eye.fill" : "eye")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(.white)
                            .frame(width: 40, height: 40)
                            .background(Circle().fill(showing ? Color.aeroGrass : Color.aeroAmber))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(showing ? "Showing \(product.title)" : "Preview \(product.title)")
                }
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(picked ? Color.aeroSky : Color.black.opacity(0.06), lineWidth: picked ? 2 : 1))
    }

    private func search() {
        model.searchInspiration(draft)
    }
}
