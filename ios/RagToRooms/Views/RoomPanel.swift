import SwiftUI

struct RoomPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let room = model.state.room
        let objects = model.displayedObjects
        let report = LayoutValidation.validate(objects: objects, room: room, name: model.displayName)
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: model.currentRoomName, symbol: "cube.transparent",
                        trailing: String(format: "%.1f × %.1f × %.1f m", room.widthM, room.depthM, room.heightM))
            ZStack(alignment: .topLeading) {
                if model.arPresented {
                    Color.clear
                } else {
                    RoomRealityView(room: room, objects: objects, selectedID: model.selectedObjectID,
                                    invalidIDs: report.invalidIDs, baseURL: model.baseURL,
                                    cameraResetToken: model.cameraResetToken,
                                    onSelect: { model.select($0) },
                                    onMove: { model.moveLocally($0, x: $1, z: $2) },
                                    onRotate: { model.rotateLocally($0, to: $1) },
                                    onCommit: { model.commitMove($0) })
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(.white.opacity(0.8), lineWidth: 1))
                        .accessibilityLabel("3D room with \(objects.count) furniture objects")
                }
                HStack(spacing: 6) {
                    if !model.previews.isEmpty { StatusBadge(text: "Preview (local only)", symbol: "eye", tint: .aeroAmber) }
                    if !model.localPoses.isEmpty { StatusBadge(text: "Moved locally", symbol: "hand.draw", tint: .aeroInk) }
                }
                .padding(10)
            }
            .frame(minHeight: 260, maxHeight: .infinity)

            selectionBar
            if let object = model.selectedObject { ObjectPhotoRow(object: object, name: model.displayName(object)) }
            hints(report)
            Text("Tap to select · drag furniture to move · drag empty space to orbit · pinch to zoom · two fingers to pan or rotate")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .glassPanel()
    }

    @ViewBuilder private var selectionBar: some View {
        HStack(spacing: 8) {
            if let object = model.selectedObject {
                Label(model.displayName(object), systemImage: object.category.categorySymbol)
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk).lineLimit(1)
                Text(String(format: "%.0f°", (object.rotationYRad * 180 / .pi).truncatingRemainder(dividingBy: 360)))
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                Button { model.rotateSelected(byDegrees: 15) } label: { Image(systemName: "rotate.left").accessibilityLabel("Rotate left 15 degrees") }
                    .buttonStyle(GlassChipStyle())
                Button { model.rotateSelected(byDegrees: -15) } label: { Image(systemName: "rotate.right").accessibilityLabel("Rotate right 15 degrees") }
                    .buttonStyle(GlassChipStyle())
                Button { model.select(nil) } label: { Image(systemName: "xmark").accessibilityLabel("Deselect") }
                    .buttonStyle(GlassChipStyle())
            } else {
                Label("Tap a piece of furniture to select it", systemImage: "hand.tap").font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer()
            Button { model.cameraResetToken += 1 } label: { Label("Recenter", systemImage: "scope") }
                .buttonStyle(GlassChipStyle())
            if model.hasLocalEdits {
                Button { model.resetLocalEdits() } label: { Label("Reset local", systemImage: "arrow.uturn.backward") }
                    .buttonStyle(GlassChipStyle())
            }
        }
    }

    @ViewBuilder private func hints(_ report: LayoutReport) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if report.hints.isEmpty {
                Label("Fits: inside the room, no overlaps, clearances free", systemImage: "checkmark.circle")
                    .font(.caption.weight(.semibold)).foregroundStyle(Color(red: 0.13, green: 0.5, blue: 0.2))
            } else {
                ForEach(report.hints) { hint in
                    Label(hint.message, systemImage: hint.symbol)
                        .font(.caption.weight(.semibold)).foregroundStyle(Color.aeroRed)
                }
            }
            if let validation = model.state.scene.validation, !validation.ok {
                ForEach(validation.issues, id: \.self) { issue in
                    Label("Server: \(issue.message)", systemImage: "server.rack").font(.caption).foregroundStyle(Color.aeroInk)
                }
            }
        }
    }
}
