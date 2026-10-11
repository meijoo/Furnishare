import SwiftUI

struct RoomPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav

    var body: some View {
        let room = model.state.room
        let objects = model.displayedObjects
        let report = LayoutValidation.validate(objects: objects, room: room, name: model.displayName)
        VStack(alignment: .leading, spacing: 10) {
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
                    if !model.localPoses.isEmpty { StatusBadge(text: "Moved", symbol: "hand.draw", tint: .aeroInk) }
                }
                .padding(10)
            }
            .frame(minHeight: 260, maxHeight: .infinity)

            HStack(spacing: 8) {
                Button { nav.showRoomSetup = true } label: { Label("Room", systemImage: "ruler") }
                    .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
                Button { nav.showAR = true } label: { Label("AR", systemImage: "arkit") }
                    .buttonStyle(AeroButtonStyle(compact: true))
                Spacer()
            }

            selectionBar
            if let object = model.selectedObject, object.category == "rug" {
                ObjectPhotoRow(object: object, name: model.displayName(object))
            }
            hints(report)
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
            }
            Spacer()
            Button { model.cameraResetToken += 1 } label: { Label("Recenter", systemImage: "scope") }
                .buttonStyle(GlassChipStyle())
            if model.hasLocalEdits {
                Button { model.resetLocalEdits() } label: { Label("Reset", systemImage: "arrow.uturn.backward") }
                    .buttonStyle(GlassChipStyle())
            }
        }
    }

    @ViewBuilder private func hints(_ report: LayoutReport) -> some View {
        if !report.hints.isEmpty || (model.state.scene.validation?.ok == false) {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(report.hints) { hint in
                    Label(hint.message, systemImage: hint.symbol)
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroRed)
                }
                if let validation = model.state.scene.validation, !validation.ok {
                    ForEach(validation.issues, id: \.self) { issue in
                        Label(issue.message, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(Color.aeroInk)
                    }
                }
            }
        }
    }
}
