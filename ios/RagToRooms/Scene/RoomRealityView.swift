import SwiftUI
import RealityKit

/// The interactive 3D room: RealityKit `ARView` in non-AR camera mode (iOS 17 compatible).
/// Gestures: tap selects; one-finger drag moves the touched object on the floor or orbits;
/// two-finger drag pans; pinch zooms; two-finger rotate turns the selected object (or orbits).
struct RoomRealityView: UIViewRepresentable {
    var room: Room
    var objects: [SceneObject]
    var selectedID: String?
    var invalidIDs: Set<String>
    var baseURL: URL?
    var cameraResetToken: Int
    var onSelect: (String?) -> Void
    var onMove: (String, Double, Double) -> Void
    var onRotate: (String, Double) -> Void
    var onCommit: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .nonAR, automaticallyConfigureSession: false)
        view.environment.background = .color(UIColor(red: 0.86, green: 0.95, blue: 1.0, alpha: 1))
        context.coordinator.install(in: view)
        return view
    }

    func updateUIView(_ view: ARView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.apply()
    }

    @MainActor
    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var parent: RoomRealityView
        private weak var view: ARView?
        private let worldAnchor = AnchorEntity(world: .zero)
        private let objectsRoot = Entity()
        private let camera = PerspectiveCamera()
        private var shell: Entity?
        private var lastRoom: Room?
        private var nodes: [String: FurnitureNode] = [:]
        private var lastCameraReset = -1

        private var azimuth: Float = 0.5
        private var elevation: Float = 0.75
        private var distance: Float = 7
        private var target: SIMD3<Float> = [0, 0.3, 0]

        private var draggingID: String?
        private var dragOffset: SIMD2<Float> = .zero
        private var rotatingID: String?

        init(parent: RoomRealityView) { self.parent = parent }

        func install(in view: ARView) {
            self.view = view
            camera.camera.fieldOfViewInDegrees = 48
            worldAnchor.addChild(camera)
            worldAnchor.addChild(objectsRoot)

            // No cast shadows: shadowed areas pick up the sky-blue environment light and read as
            // colored patches on the floor.
            let sun = DirectionalLight()
            sun.light.intensity = 2400
            sun.look(at: .zero, from: [2.5, 6, 4], relativeTo: nil)
            worldAnchor.addChild(sun)
            let fill = DirectionalLight()
            fill.light.intensity = 1100
            fill.look(at: .zero, from: [-4, 3, -2], relativeTo: nil)
            worldAnchor.addChild(fill)
            view.scene.addAnchor(worldAnchor)

            let tap = UITapGestureRecognizer(target: self, action: #selector(handleTap(_:)))
            let pan = UIPanGestureRecognizer(target: self, action: #selector(handlePan(_:)))
            pan.maximumNumberOfTouches = 1
            let pan2 = UIPanGestureRecognizer(target: self, action: #selector(handleTwoFingerPan(_:)))
            pan2.minimumNumberOfTouches = 2
            let pinch = UIPinchGestureRecognizer(target: self, action: #selector(handlePinch(_:)))
            let rotate = UIRotationGestureRecognizer(target: self, action: #selector(handleRotation(_:)))
            for gesture in [tap, pan, pan2, pinch, rotate] as [UIGestureRecognizer] {
                gesture.delegate = self
                view.addGestureRecognizer(gesture)
            }
            apply()
        }

        // MARK: Scene diffing

        func apply() {
            guard view != nil else { return }
            if lastRoom != parent.room {
                shell?.removeFromParent()
                let newShell = EntityFactory.roomShell(parent.room)
                worldAnchor.addChild(newShell)
                shell = newShell
                if lastRoom == nil || lastRoom?.widthM != parent.room.widthM || lastRoom?.depthM != parent.room.depthM {
                    fitCamera()
                }
                lastRoom = parent.room
            }
            if lastCameraReset != parent.cameraResetToken {
                lastCameraReset = parent.cameraResetToken
                fitCamera()
            }

            let incoming = Set(parent.objects.map(\.objectID))
            for (id, node) in nodes where !incoming.contains(id) {
                node.disappear()
                nodes[id] = nil
            }
            for object in parent.objects {
                let assetURL = BackendClient.resolve(object.assetURL, base: parent.baseURL)
                if let node = nodes[object.objectID] {
                    node.update(object: object, assetURL: assetURL)
                    let isGesturing = object.objectID == draggingID || object.objectID == rotatingID
                    if !isGesturing, node.needsPoseUpdate(for: object) {
                        node.setPose(x: object.x, z: object.z, angle: object.rotationYRad, animated: true)
                    }
                } else {
                    let node = FurnitureNode(object: object, assetURL: assetURL)
                    objectsRoot.addChild(node.root)
                    node.appear()
                    nodes[object.objectID] = node
                }
            }
            for (id, node) in nodes {
                let selected = id == parent.selectedID, invalid = parent.invalidIDs.contains(id)
                node.setHighlight(selected && invalid ? .selectedInvalid : selected ? .selected : invalid ? .invalid : .none)
            }
        }

        // MARK: Camera

        private func fitCamera() {
            let w = Float(parent.room.widthM), d = Float(parent.room.depthM)
            distance = max(w, d) * 1.45 + 1.2
            azimuth = 0.45
            elevation = 0.78
            target = [0, 0.3, 0]
            updateCamera()
        }

        private func updateCamera() {
            elevation = min(max(elevation, 0.12), 1.48)
            azimuth = min(max(azimuth, -1.9), 1.9)
            distance = min(max(distance, 1.2), 25)
            let offset = SIMD3<Float>(cos(elevation) * sin(azimuth), sin(elevation), cos(elevation) * cos(azimuth)) * distance
            camera.look(at: target, from: target + offset, relativeTo: nil)
        }

        // MARK: Hit testing

        private func objectID(at point: CGPoint) -> String? {
            guard let view, var entity = view.entity(at: point) else { return nil }
            while true {
                if nodes[entity.name] != nil { return entity.name }
                guard let parent = entity.parent else { return nil }
                entity = parent
            }
        }

        private func floorPoint(at point: CGPoint) -> SIMD2<Float>? {
            guard let view, let ray = view.ray(through: point), ray.direction.y < -0.0001 else { return nil }
            let t = -ray.origin.y / ray.direction.y
            let hit = ray.origin + ray.direction * t
            return SIMD2(hit.x, hit.z)
        }

        // MARK: Gestures

        func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            let multi: (UIGestureRecognizer) -> Bool = {
                $0 is UIPinchGestureRecognizer || $0 is UIRotationGestureRecognizer
                    || (($0 as? UIPanGestureRecognizer)?.minimumNumberOfTouches ?? 0) >= 2
            }
            return multi(g) && multi(other)
        }

        @objc private func handleTap(_ gesture: UITapGestureRecognizer) {
            guard let view else { return }
            parent.onSelect(objectID(at: gesture.location(in: view)))
        }

        @objc private func handlePan(_ gesture: UIPanGestureRecognizer) {
            guard let view else { return }
            let location = gesture.location(in: view)
            switch gesture.state {
            case .began:
                if let id = objectID(at: location), let node = nodes[id], let floor = floorPoint(at: location) {
                    draggingID = id
                    dragOffset = SIMD2(Float(node.x), Float(node.z)) - floor
                    parent.onSelect(id)
                }
            case .changed:
                if let id = draggingID, let node = nodes[id] {
                    guard let floor = floorPoint(at: location) else { return }
                    let p = floor + dragOffset
                    node.setPose(x: Double(p.x), z: Double(p.y), angle: node.angle, animated: false)
                    parent.onMove(id, Double(p.x), Double(p.y))
                } else {
                    let t = gesture.translation(in: view)
                    azimuth -= Float(t.x) * 0.008
                    elevation += Float(t.y) * 0.006
                    gesture.setTranslation(.zero, in: view)
                    updateCamera()
                }
            case .ended, .cancelled, .failed:
                if let id = draggingID { parent.onCommit(id) }
                draggingID = nil
            default: break
            }
        }

        @objc private func handleTwoFingerPan(_ gesture: UIPanGestureRecognizer) {
            guard let view, gesture.state == .changed else { return }
            let t = gesture.translation(in: view)
            gesture.setTranslation(.zero, in: view)
            let right = SIMD3<Float>(cos(azimuth), 0, -sin(azimuth))
            let forward = SIMD3<Float>(-sin(azimuth), 0, -cos(azimuth))
            let scale = distance * 0.0016
            target += (-right * Float(t.x) + forward * Float(t.y)) * scale
            target.x = min(max(target.x, -6), 6)
            target.z = min(max(target.z, -6), 6)
            updateCamera()
        }

        @objc private func handlePinch(_ gesture: UIPinchGestureRecognizer) {
            guard gesture.state == .changed, gesture.scale > 0 else { return }
            distance /= Float(gesture.scale)
            gesture.scale = 1
            updateCamera()
        }

        @objc private func handleRotation(_ gesture: UIRotationGestureRecognizer) {
            switch gesture.state {
            case .began:
                rotatingID = parent.selectedID.flatMap { nodes[$0] != nil ? $0 : nil }
            case .changed:
                if let id = rotatingID, let node = nodes[id] {
                    let angle = node.angle - Double(gesture.rotation)
                    node.setPose(x: node.x, z: node.z, angle: angle, animated: false)
                    parent.onRotate(id, angle)
                } else {
                    azimuth -= Float(gesture.rotation)
                    updateCamera()
                }
                gesture.rotation = 0
            case .ended, .cancelled, .failed:
                if let id = rotatingID { parent.onCommit(id) }
                rotatingID = nil
            default: break
            }
        }
    }
}
