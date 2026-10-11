import SwiftUI

struct ItemsPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if isEmpty {
                Text("Add something you own, search on Inspiration, or tap Design this room. Tap a piece for details.")
                    .font(.subheadline)
                    .foregroundStyle(Color.figmaMuted)
            }

            if let proposal = model.state.proposal {
                VStack(spacing: 6) {
                    ForEach(model.designProposalItems, id: \.productID) { item in itemRow(item) }
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
            ForEach(model.candidateGroups) { group in
                groupBlock(group)
            }
            ForEach(model.currentOwnedItems) { item in
                ownedRow(item)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassPanel()
        .id("proposal")
    }

    private var isEmpty: Bool {
        model.currentOwnedItems.isEmpty && model.designProposalItems.isEmpty && model.candidateGroups.isEmpty
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "In this room", symbol: "square.stack.3d.up")
            HStack {
                if let proposal = model.state.proposal {
                    StatusBadge(text: proposal.status.label, symbol: proposal.status.symbol)
                }
                Spacer()
                if !isEmpty {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(dollars(bundleTotal)).font(.title3.bold().monospacedDigit())
                        Text(hasUnknownPrices ? "To buy · some prices unknown" : "To buy · owned items excluded").font(.caption).foregroundStyle(Color.figmaMuted)
                    }
                }
            }
            HStack {
                Button { nav.showAddItem = true } label: { Label("Add", systemImage: "plus") }
                    .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
                Button { nav.showCatalog = true } label: { Label("Catalog", systemImage: "square.grid.2x2") }
                    .buttonStyle(AeroButtonStyle(compact: true))
            }
        }
    }

    private var bundleTotal: Int {
        let proposed = model.designProposalItems.reduce(0) { sum, item in
            guard model.isDesignItemEnabled(model.designItemID(for: item)) else { return sum }
            let object = proposalObject(item)
            let price = object.flatMap { model.displayedProduct(for: $0)?.priceCents }
                ?? model.product(item.productID)?.priceCents ?? item.priceCents
            return sum + (price ?? 0)
        }
        let extras = model.candidateGroups.reduce(0) { sum, group in
            guard model.isDesignItemEnabled(group.objectID) else { return sum }
            let id = group.showingProductID ?? group.productIDs.first
            return sum + (id.flatMap { model.product($0)?.priceCents } ?? 0)
        }
        return proposed + extras
    }

    private var hasUnknownPrices: Bool {
        let proposedUnknown = model.designProposalItems.contains { item in
            model.isDesignItemEnabled(model.designItemID(for: item)) &&
            (proposalObject(item).flatMap { model.displayedProduct(for: $0)?.priceCents }
                ?? model.product(item.productID)?.priceCents ?? item.priceCents) == nil
        }
        return proposedUnknown || model.candidateGroups.contains { group in
            model.isDesignItemEnabled(group.objectID) &&
            model.product(group.showingProductID ?? group.productIDs.first)?.priceCents == nil
        }
    }

    private func ownedRow(_ item: OwnedItem) -> some View {
        let productID = "owned-\(item.id.uuidString)"
        let objectID = "local-\(productID)"
        let open = model.selectedObjectID == objectID || model.detailProductID == productID
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Button {
                    if open {
                        model.select(nil)
                        model.detailProductID = nil
                    } else if model.isDesignItemEnabled(objectID) {
                        model.select(objectID)
                    } else {
                        model.select(nil)
                        model.detailProductID = productID
                    }
                } label: {
                    HStack(spacing: 12) {
                        ownedThumb(item)
                            .frame(width: 64, height: 64)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.name).font(.headline).foregroundStyle(Color.aeroInk)
                            Text(sizeLine(item)).font(.subheadline).foregroundStyle(Color.figmaMuted)
                            Text("Owned").font(.caption.weight(.semibold)).foregroundStyle(Color.aeroGrass)
                        }
                        Spacer()
                        Image(systemName: open ? "chevron.up" : "chevron.down")
                            .foregroundStyle(Color.figmaMuted)
                            .accessibilityHidden(true)
                    }
                }
                .buttonStyle(.plain)

            }
            itemControls(id: objectID, name: item.name) { model.removeOwnedItem(item.id) }
            if open {
                ProductDetailPanel()
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
            .fill(open ? Color.aeroSky.opacity(0.18) : Color.figmaWash.opacity(0.6)))
        .accessibilityLabel(open ? "Hide details for \(item.name)" : "Details for \(item.name)")
    }

    private func itemRow(_ item: ProposalItem) -> some View {
        let object = proposalObject(item)
        let chosen = object.flatMap { model.appliedPreviews[$0.objectID] }
        let shown = model.product(chosen) ?? object.flatMap { model.displayedProduct(for: $0) } ?? model.product(item.productID)
        let open = object.map { model.selectedObjectID == $0.objectID } == true
            || (model.selectedObjectID == nil && model.detailProductID == (shown?.id ?? item.productID))
        return VStack(alignment: .leading, spacing: 6) {
            Button {
                if open {
                    model.select(nil)
                    model.detailProductID = nil
                } else if let object, model.isDesignItemEnabled(model.designItemID(for: item)) {
                    model.select(object.objectID)
                } else {
                    model.select(nil)
                    model.detailProductID = shown?.id ?? item.productID
                }
            } label: {
                HStack(spacing: 10) {
                    ProductImage(urls: shown.map { model.imageURLs(for: $0) } ?? [], category: item.category)
                        .frame(width: 64, height: 64)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(shown?.title ?? item.title ?? item.productID)
                            .font(.headline).lineLimit(2)
                        HStack(spacing: 6) {
                            Text("\(item.category.categoryLabel) · Proposed").font(.caption).foregroundStyle(.secondary)
                            if object.flatMap({ model.appliedPreviews[$0.objectID] }) != nil {
                                Text("Chosen").font(.caption.weight(.semibold)).foregroundStyle(Color.aeroGrass)
                            }
                        }
                    }
                    Spacer()
                    if object == nil { Image(systemName: "cube.transparent").foregroundStyle(.secondary).accessibilityLabel("Not placed in the room") }
                    Text((shown?.priceCents).map(dollars) ?? item.priceCents.map(dollars) ?? "Price unknown")
                        .font(.subheadline.monospacedDigit().weight(.semibold))
                    Image(systemName: open ? "chevron.up" : "chevron.down").foregroundStyle(Color.figmaMuted)
                }
                .foregroundStyle(Color.aeroInk)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            itemControls(id: model.designItemID(for: item), name: shown?.title ?? item.title ?? item.productID) {
                model.removeDesignProposalItem(item)
            }
            if open { ProductDetailPanel(optionObjectID: object?.objectID).padding(.horizontal, 8) }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
            .fill(open ? Color.aeroSky.opacity(0.18) : Color.figmaWash.opacity(0.6)))
    }

    private func proposalObject(_ item: ProposalItem) -> SceneObject? {
        // Resolve the original identity before looking up its displayed replacement.
        guard let original = model.state.scene.objects.first(where: { $0.productID == item.productID }) else { return nil }
        return model.displayedObjects.first { $0.objectID == original.objectID } ?? original
    }

    private func groupBlock(_ group: CandidateGroup) -> some View {
        let productID = group.showingProductID ?? group.productIDs.first
        let object = model.displayedObjects.first { $0.objectID == group.objectID }
        let product = object.flatMap { model.displayedProduct(for: $0) } ?? model.product(productID)
        let open = model.selectedObjectID == group.objectID
            || (object == nil && productID != nil && model.detailProductID == productID)
        return VStack(alignment: .leading, spacing: 10) {
            Button {
                if open {
                    model.select(nil)
                    model.detailProductID = nil
                } else if let object {
                    model.select(object.objectID)
                } else {
                    model.select(nil)
                    model.detailProductID = productID
                }
            } label: {
                HStack(spacing: 10) {
                    ProductImage(urls: product.map { model.imageURLs(for: $0) } ?? [], category: group.category ?? "")
                        .frame(width: 64, height: 64)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(product?.title ?? group.name).font(.headline).lineLimit(2)
                        Text("\(group.category?.categoryLabel ?? "Item") · Selected")
                            .font(.caption).foregroundStyle(Color.figmaMuted)
                    }
                    Spacer()
                    Text(product.map { dollars($0.priceCents) } ?? "Price unknown")
                        .font(.subheadline.monospacedDigit().weight(.semibold))
                    Image(systemName: open ? "chevron.up" : "chevron.down")
                        .foregroundStyle(Color.figmaMuted)
                }
                .foregroundStyle(Color.aeroInk)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            itemControls(id: group.objectID, name: product?.title ?? group.name) {
                model.removeCandidateGroup(group)
            }
            if open {
                ProductDetailPanel(showAlternatives: false)
                Text("Options for \(group.name)").font(.subheadline.weight(.semibold))
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(group.productIDs, id: \.self) { id in
                            if let option = model.product(id) { itemCard(group, option) }
                        }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
            .fill(open ? Color.aeroSky.opacity(0.18) : Color.figmaWash.opacity(0.6)))
    }

    private func itemControls(id: String, name: String, remove: @escaping () -> Void) -> some View {
        HStack(spacing: 12) {
            Spacer()
            Toggle(isOn: Binding(
                get: { model.isDesignItemEnabled(id) },
                set: { model.setDesignItemEnabled(id, enabled: $0) })) {
                    Text("Include \(name) in room")
                }
                .labelsHidden()
                .fixedSize()
                .toggleStyle(.switch)
                .accessibilityLabel("Include \(name) in room")
            Button(role: .destructive, action: remove) {
                Image(systemName: "trash")
                    .frame(minWidth: 24, minHeight: 24)
            }
            .buttonStyle(GlassChipStyle())
            .accessibilityLabel("Remove \(name)")
        }
        .padding(.horizontal, 8)
    }

    private func itemCard(_ group: CandidateGroup, _ product: Product) -> some View {
        let showing = group.showingProductID == product.id
        let open = showing && model.selectedObjectID == group.objectID
        return VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .topTrailing) {
                ProductImage(urls: model.imageURLs(for: product), category: product.category)
                    .frame(width: 120, height: 88)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                Button {
                    model.removeFromGroup(group.id, productID: product.id)
                } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.white).shadow(radius: 1)
                }
                .buttonStyle(.plain)
                .padding(4)
                .accessibilityLabel("Remove \(product.title)")
            }
            Text(product.title).font(.caption.weight(.semibold)).lineLimit(2).foregroundStyle(Color.aeroInk)
            Text(dollars(product.priceCents)).font(.caption.monospacedDigit()).foregroundStyle(Color.figmaMuted)
            Text(open ? "Details" : (showing ? "Showing" : "Show"))
                .font(.caption.weight(.semibold))
                .foregroundStyle(open || showing ? Color.aeroSky : Color.aeroInk)
        }
        .frame(width: 120, alignment: .leading)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
            .strokeBorder(open ? Color.aeroSky : Color.black.opacity(0.06), lineWidth: open ? 2 : 1))
        .onTapGesture {
            if open {
                model.select(nil)
            } else {
                model.showInGroup(group.id, productID: product.id)
            }
        }
        .accessibilityLabel(open ? "Hide details for \(product.title)" : "Show \(product.title)")
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
