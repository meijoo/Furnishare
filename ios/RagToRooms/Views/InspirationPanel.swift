import PhotosUI
import SwiftUI

struct InspirationPanel: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""
    @State private var designDraft = ""
    @State private var photoItem: PhotosPickerItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PanelHeader(title: "Inspiration", symbol: "sparkles",
                        trailing: model.inspirationCategory?.categoryLabel)
            photos
            searchBar
            results
            design
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
        .onChange(of: model.pendingInspirationQuery) { _, query in
            guard let query, !query.isEmpty else { return }
            draft = query
            model.pendingInspirationQuery = nil
            model.searchInspiration(query)
        }
    }

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(Color.figmaMuted)
            TextField("Search sofas, beds, lamps…", text: $draft)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onSubmit(search)
            if !draft.isEmpty {
                Button {
                    draft = ""
                    model.searchInspiration("")
                } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(Color.figmaMuted)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
            Button(action: search) {
                if model.busy.contains("inspiration-search") {
                    ProgressView().tint(.white)
                } else {
                    Text("Search")
                }
            }
            .buttonStyle(AeroButtonStyle(compact: true))
            .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty || model.busy.contains("inspiration-search"))
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14).fill(Color.figmaWash))
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

    @ViewBuilder private var results: some View {
        if model.inspirationResults.isEmpty {
            if model.busy.contains("inspiration-search") {
                ProgressView().frame(maxWidth: .infinity).padding(.vertical, 24)
            } else if !model.inspirationQuery.isEmpty {
                Text("No matches").foregroundStyle(Color.figmaMuted)
            } else {
                Text("Search for a piece. Everything you select joins the proposal on Design.")
                    .font(.subheadline)
                    .foregroundStyle(Color.figmaMuted)
            }
        } else {
            HStack {
                Text(model.inspirationCategory?.categoryLabel ?? "Results")
                    .font(.headline)
                    .foregroundStyle(Color.aeroInk)
                if model.busy.contains("inspiration-search") {
                    Text("Checking live listings…")
                        .font(.caption)
                        .foregroundStyle(Color.figmaMuted)
                }
                Spacer()
                let selected = model.inspirationResults.filter { model.inspirationPicks.contains($0.id) }.count
                if selected > 0 {
                    Text("\(selected) selected")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.aeroInk)
                }
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 168), spacing: 12)], spacing: 12) {
                ForEach(model.inspirationResults) { product in
                    card(product, picked: model.inspirationPicks.contains(product.id))
                }
            }
        }
    }

    private func card(_ product: Product, picked: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
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
            Button {
                model.toggleInspirationPick(product.id)
            } label: {
                Text(picked ? "Selected" : "Select")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.aeroInk)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .background(Capsule().strokeBorder(Color.black.opacity(0.12), lineWidth: 1))
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(picked ? Color.aeroSky : Color.black.opacity(0.06), lineWidth: picked ? 2 : 1))
    }

    private var design: some View {
        let designing = model.busy.contains("design")
        return VStack(alignment: .leading, spacing: 8) {
            Text("Design this room").font(.headline).foregroundStyle(Color.aeroInk)
            TextField(model.chatSuggestion, text: $designDraft, axis: .vertical)
                .lineLimit(2...4)
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color.figmaWash))
                .onSubmit(designRoom)
            Button(action: designRoom) {
                if designing {
                    ProgressView().tint(.white)
                } else {
                    Label("Design this room", systemImage: "wand.and.stars")
                }
            }
            .buttonStyle(AeroButtonStyle(compact: true))
            .disabled(designing || model.busy.contains("chat") || !model.actingMemberInScope)
        }
    }

    private func search() {
        model.searchInspiration(draft)
    }

    private func designRoom() {
        let text = designDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        Task { await model.designRoom(text) }
    }
}
