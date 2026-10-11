import SwiftUI

/// Top-down, to-scale apartment plan. Tapping a furnishable room switches every other panel to that room scope.
struct FloorPlanPanel: View {
    @Environment(AppModel.self) private var model
    @AppStorage("floorPlanExpanded") private var expanded = true
    @AppStorage("floorPlanShowImage") private var showImage = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                PanelHeader(title: "Apartment", symbol: "square.split.bottomrightquarter", trailing: model.apartment?.name)
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() }
                } label: {
                    Label(expanded ? "Hide plan" : "Show plan", systemImage: expanded ? "chevron.up" : "chevron.down")
                }
                .buttonStyle(GlassChipStyle())
            }
            if let apartment = model.apartment {
                if model.apartmentIsFixture {
                    StatusBadge(text: model.isOfflineDemo ? "Demo plan" : "Bundled plan (backend has no /apartments yet)",
                                symbol: "shippingbox", tint: .aeroAmber)
                }
                if apartment.isImported {
                    StatusBadge(text: "Imported plan", symbol: "doc.viewfinder", tint: .aeroInk)
                }
                if expanded {
                    FloorPlanImportControls(apartment: apartment, showImage: $showImage)
                    ApartmentPlanView(apartment: apartment, showImage: showImage)
                    if let room = model.currentRoom { currentRoomLine(room, apartment: apartment) }
                    Text("Tap a room to furnish it. Bathrooms, halls, closets and other rooms without a scope are drawn for reference only.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                totals(apartment)
            } else {
                Text("The apartment plan isn't available.").foregroundStyle(.secondary)
            }
        }
        .glassPanel()
        .task {
            while !Task.isCancelled {
                await model.refreshApartment()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    private func currentRoomLine(_ room: ApartmentRoom, apartment: Apartment) -> some View {
        let s = room.summary ?? RoomSummary()
        return HStack(spacing: 8) {
            Label("Viewing \(apartment.shortName(room))", systemImage: "eye.fill").font(.subheadline.weight(.semibold))
            StatusBadge(text: room.shared ? "Shared" : (room.ownerID == nil ? "Unassigned" : "Private"),
                        symbol: room.shared ? "person.3.fill" : (room.ownerID == nil ? "person.crop.circle.badge.questionmark" : "lock.fill"))
            if s.hasProposal {
                let status = s.status ?? .unknown
                StatusBadge(text: status.label, symbol: status.symbol)
                if let done = s.approvalsDone, let needed = s.approvalsNeeded {
                    Label("\(done)/\(needed)", systemImage: "hand.thumbsup").font(.caption.weight(.semibold))
                        .accessibilityLabel("\(done) of \(needed) approvals")
                }
                if s.settled && status != .settled { StatusBadge(text: "Settled", symbol: "checkmark.circle.fill") }
                Spacer(minLength: 4)
                Text([s.knownTotalCents.map(dollars), s.itemCount.map { $0 == 1 ? "1 item" : "\($0) items" }]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.subheadline.monospacedDigit().weight(.semibold))
            } else {
                Label("No proposal yet", systemImage: "circle.dashed").font(.caption).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
        }
        .foregroundStyle(Color.aeroInk)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }

    private func totals(_ apartment: Apartment) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Known total across the apartment", systemImage: "sum").font(.subheadline.weight(.semibold))
                Spacer()
                Text(dollars(apartment.totals.knownTotalCents)).font(.headline.monospacedDigit())
            }
            .foregroundStyle(Color.aeroInk)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { memberTotals(apartment) }
                VStack(spacing: 8) { memberTotals(apartment) }
            }
            Text("Each person's shared-room shares plus their own bedroom. Shipping and tax are not included.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private func memberTotals(_ apartment: Apartment) -> some View {
        ForEach(apartment.members) { member in
            let mine = member.id == model.actingMemberID
            VStack(alignment: .leading, spacing: 2) {
                Label(mine ? "Your total across the apartment" : "\(member.name)'s total",
                      systemImage: mine ? "person.crop.circle.fill" : "person.crop.circle")
                    .font(.caption.weight(mine ? .bold : .regular))
                    .fixedSize(horizontal: false, vertical: true)
                Text(dollars(apartment.totals.byMemberCents[member.id] ?? 0)).font(.headline.monospacedDigit())
                if mine { Text(member.name).font(.caption2).foregroundStyle(.secondary) }
            }
            .foregroundStyle(Color.aeroInk)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 12).fill(.white.opacity(mine ? 0.65 : 0.3)))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(mine ? Color.aeroSky : .clear, lineWidth: 1.5))
            .accessibilityElement(children: .combine)
        }
    }
}

/// Top-down apartment plan. Pass `selection` to toggle rooms instead of switching the live scope.
struct ApartmentPlanView: View {
    @Environment(AppModel.self) private var model
    let apartment: Apartment
    var showImage = true
    var compact = false
    var maxHeight: Double = 520
    var selection: Binding<Set<String>>?

    var body: some View {
        let drawImage = showImage && apartment.isImported
        let bounds = apartment.drawingBounds(includingImage: drawImage)
        PlanSizing(aspect: bounds.widthM / bounds.depthM, maxHeight: maxHeight) {
            GeometryReader { proxy in
                let scale = min(proxy.size.width / bounds.widthM, proxy.size.height / bounds.depthM)
                let size = CGSize(width: bounds.widthM * scale, height: bounds.depthM * scale)
                ZStack(alignment: .topLeading) {
                    if drawImage, let frame = apartment.imageFrameM, let url = model.client?.resolve(apartment.imageURL) {
                        AsyncImage(url: url) { phase in
                            if let image = phase.image { image.resizable() } else { Color.clear }
                        }
                        .frame(width: frame.widthM * scale, height: frame.depthM * scale)
                        .opacity(0.35)
                        .position(x: (frame.xM - bounds.xM + frame.widthM / 2) * scale, y: (frame.zM - bounds.zM + frame.depthM / 2) * scale)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                    }
                    ForEach(apartment.rooms) { room in
                        let isCurrent = selection.map { $0.wrappedValue.contains(room.id) }
                            ?? (room.householdID == model.currentHouseholdID)
                        let showFootprints = selection == nil && isCurrent
                        RoomTile(room: room, title: apartment.shortName(room), scale: scale, isCurrent: isCurrent,
                                 selecting: selection != nil, compact: compact,
                                 footprints: showFootprints ? model.displayedObjects : [],
                                 sceneRoom: room.roomM ?? (showFootprints ? PlanSize(widthM: model.state.room.widthM, depthM: model.state.room.depthM) : nil),
                                 selection: selection)
                            .frame(width: room.widthM * scale, height: room.depthM * scale)
                            .position(x: (room.xM - bounds.xM + room.widthM / 2) * scale, y: (room.zM - bounds.zM + room.depthM / 2) * scale)
                    }
                    RoundedRectangle(cornerRadius: 4).strokeBorder(Color.aeroInk.opacity(0.7), lineWidth: 2.5)
                        .frame(width: apartment.widthM * scale, height: apartment.depthM * scale)
                        .position(x: (apartment.widthM / 2 - bounds.xM) * scale, y: (apartment.depthM / 2 - bounds.zM) * scale)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                .frame(width: size.width, height: size.height)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Floor plan, \(apartment.name)\(apartment.isImported ? ", imported" : "")")
    }
}

/// Takes the offered width and a height that keeps the plan's aspect ratio, capped at `maxHeight`.
private struct PlanSizing: Layout {
    let aspect: Double
    let maxHeight: Double

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let offered = proposal.width.flatMap { $0.isFinite ? $0 : nil } ?? 520
        return CGSize(width: offered, height: min(offered / aspect, maxHeight))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for subview in subviews {
            subview.place(at: CGPoint(x: bounds.midX, y: bounds.midY), anchor: .center, proposal: ProposedViewSize(bounds.size))
        }
    }
}

private struct RoomTile: View {
    @Environment(AppModel.self) private var model
    let room: ApartmentRoom
    let title: String
    let scale: Double
    let isCurrent: Bool
    var selecting = false
    var compact = false
    let footprints: [SceneObject]
    /// The scope's real 3D room (`room_m`); footprints are scaled from it onto the plan rectangle.
    let sceneRoom: PlanSize?
    var selection: Binding<Set<String>>?

    var body: some View {
        if room.isFurnishable {
            Button { tap() } label: { tile }
                .buttonStyle(.plain)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(accessibilityText)
                .accessibilityHint(selecting ? (isCurrent ? "Deselect this room" : "Select this room") : (isCurrent ? "" : "Shows this room in every panel"))
                .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        } else {
            tile
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(title), \(room.kind.label.lowercased()), not furnishable")
        }
    }

    private var tile: some View {
        let shape = RoundedRectangle(cornerRadius: 6, style: .continuous)
        return ZStack(alignment: .topLeading) {
            shape.fill(fill)
            if !footprints.isEmpty { footprintLayer.clipShape(shape) }
            labels
                .padding(.horizontal, compact ? 0 : 5).padding(.vertical, compact ? 0 : 4)
                .background {
                    if !compact, !footprints.isEmpty { RoundedRectangle(cornerRadius: 6).fill(.white.opacity(0.72)) }
                }
                .padding(compact ? 0 : 4)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: compact ? .center : .topLeading)
        }
        .overlay(shape.strokeBorder(isCurrent ? Color.aeroSky : .white.opacity(0.85), lineWidth: isCurrent ? 3 : 1))
        .overlay(alignment: .bottomTrailing) {
            if isCurrent {
                if selecting {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(Color.aeroSky)
                        .padding(6)
                        .accessibilityHidden(true)
                } else {
                    StatusBadge(text: "Viewing", symbol: "eye.fill", tint: Color(red: 0.10, green: 0.42, blue: 0.75))
                        .padding(5)
                }
            }
        }
        .padding(1.5)
        .contentShape(Rectangle())
    }

    private var fill: Color {
        switch room.kind {
        case .living: .aeroSky.opacity(isCurrent ? 0.42 : 0.28)
        case .bedroom: .aeroGrass.opacity(isCurrent ? 0.40 : 0.26)
        case .kitchen, .dining: .aeroAmber.opacity(0.14)
        case .bathroom, .laundry: .white.opacity(0.32)
        case .patio: .aeroGrass.opacity(0.10)
        case .hall, .closet, .other, .unknown: .white.opacity(0.18)
        }
    }

    @ViewBuilder private var labels: some View {
        if compact {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(room.isFurnishable ? Color.aeroInk : .secondary)
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .minimumScaleFactor(0.65)
                .padding(6)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 3) {
                Label(title, systemImage: room.kind.symbol)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(room.isFurnishable ? Color.aeroInk : .secondary)
                    .lineLimit(2)
                if let label = room.distinctLabel {
                    Text(label).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
                if let interior = room.interiorM, footprints.isEmpty {
                    Text(String(format: "%.2f × %.2f m", interior.widthM, interior.depthM))
                        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary).lineLimit(1)
                }
                // With furniture drawn, the summary moves below the plan so it doesn't hide the footprints.
                if room.isFurnishable {
                    if footprints.isEmpty {
                        if room.shared {
                            StatusBadge(text: "Shared", symbol: "person.3.fill", tint: .aeroInk)
                        } else if room.ownerID != nil {
                            StatusBadge(text: "Private", symbol: "lock.fill", tint: .aeroInk)
                        } else {
                            StatusBadge(text: "Unassigned", symbol: "person.crop.circle.badge.questionmark", tint: .aeroInk)
                        }
                        summary
                    }
                } else if room.kind == .kitchen, !room.name.localizedCaseInsensitiveContains("coming soon") {
                    Label("Coming soon", systemImage: "clock").font(.caption2).foregroundStyle(.secondary)
                } else if room.kind == .living || room.kind == .bedroom {
                    Label("Not furnished in the app", systemImage: "minus.circle").font(.caption2).foregroundStyle(.secondary)
                }
            }
            .minimumScaleFactor(0.75)
        }
    }

    @ViewBuilder private var summary: some View {
        let s = room.summary ?? RoomSummary()
        Group {
            if s.hasProposal {
                let status = s.status ?? .unknown
                Label(status.label, systemImage: status.symbol)
                Text([s.knownTotalCents.map(dollars), s.itemCount.map { $0 == 1 ? "1 item" : "\($0) items" }]
                    .compactMap { $0 }.joined(separator: " · "))
                    .monospacedDigit()
                if let done = s.approvalsDone, let needed = s.approvalsNeeded {
                    Label("Approvals \(done)/\(needed)", systemImage: done == needed && needed > 0 ? "checkmark.seal" : "hand.thumbsup")
                }
                if s.settled && status != .settled {
                    Label("Settled", systemImage: "checkmark.circle.fill").foregroundStyle(Color(red: 0.13, green: 0.5, blue: 0.2))
                }
            } else {
                Label("No proposal yet", systemImage: "circle.dashed").foregroundStyle(.secondary)
            }
        }
        .font(.caption2.weight(.medium))
        .foregroundStyle(Color.aeroInk)
        .lineLimit(1)
    }

    /// Current room's furniture, mapped with the contract's scene-to-plan rule (no rotation, centered),
    /// scaled by `width_m / room_m.width_m` and `depth_m / room_m.depth_m` (1:1 without `room_m`).
    private var footprintLayer: some View {
        let sx = sceneRoom.map { room.widthM / $0.widthM } ?? 1
        let sz = sceneRoom.map { room.depthM / $0.depthM } ?? 1
        return ZStack(alignment: .topLeading) {
            ForEach(footprints) { object in
                let color = Color(uiColor: UIColor(hex: object.colorHex) ?? .systemGray3)
                Rectangle()
                    .fill(color.opacity(object.category == "rug" ? 0.25 : 0.6))
                    .overlay(Rectangle().strokeBorder(Color.aeroInk.opacity(0.45), lineWidth: 0.75))
                    .frame(width: max(object.dimensionsM.width * scale, 2), height: max(object.dimensionsM.depth * scale, 2))
                    // Scene rotation is counterclockwise about +Y seen from above; SwiftUI rotates clockwise.
                    .rotationEffect(.radians(-object.rotationYRad))
                    // Scene-to-plan scaling is along the plan axes, so it applies after the rotation.
                    .scaleEffect(x: sx, y: sz)
                    .position(x: (room.widthM / 2 + object.x * sx) * scale, y: (room.depthM / 2 + object.z * sz) * scale)
            }
        }
        .frame(width: room.widthM * scale, height: room.depthM * scale)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private var accessibilityText: String {
        var parts = [title, room.shared ? "shared" : (room.ownerID == nil ? "unassigned" : "private \(room.kind.label.lowercased())")]
        if let s = room.summary, s.hasProposal {
            parts.append((s.status ?? .unknown).label)
            if let total = s.knownTotalCents { parts.append("known total \(dollars(total))") }
            if let count = s.itemCount { parts.append("\(count) items") }
            if let done = s.approvalsDone, let needed = s.approvalsNeeded { parts.append("\(done) of \(needed) approvals") }
            if s.settled { parts.append("settled") }
        } else {
            parts.append("no proposal yet")
        }
        if isCurrent { parts.append(selecting ? "selected" : "currently viewing") }
        return parts.joined(separator: ", ")
    }

    private func tap() {
        if let selection {
            if selection.wrappedValue.contains(room.id) { selection.wrappedValue.remove(room.id) }
            else { selection.wrappedValue.insert(room.id) }
        } else {
            model.selectRoom(room.id)
        }
    }
}

/// Compact chip row for the top bar: Living room · Emily's room · Maya's room · Alex's room.
struct RoomSwitcher: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        if let apartment = model.apartment {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(apartment.furnishableRooms.filter { nav.selectedRoomIDs.isEmpty || nav.selectedRoomIDs.contains($0.id) }) { room in
                        let isCurrent = room.householdID == model.currentHouseholdID
                        Button { model.selectRoom(room.id) } label: {
                            Label(apartment.shortName(room), systemImage: isCurrent ? "checkmark.circle.fill" : room.kind.symbol)
                        }
                        .buttonStyle(GlassChipStyle(selected: isCurrent))
                        .accessibilityAddTraits(isCurrent ? .isSelected : [])
                    }
                    Button { nav.showAddRooms = true } label: {
                        Image(systemName: "plus")
                    }
                    .buttonStyle(GlassChipStyle())
                    .accessibilityLabel("Add rooms")
                }
                .padding(.vertical, 2)
            }
            .scrollIndicators(.hidden)
            .accessibilityLabel("Room")
        }
    }
}
