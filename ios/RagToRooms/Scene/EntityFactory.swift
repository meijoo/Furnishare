import RealityKit
import UIKit

enum FootprintHighlight: Equatable {
    case none, selected, invalid, selectedInvalid
}

/// Everything that changes an object's *appearance* (as opposed to its pose).
struct ContentSignature: Hashable {
    var productID: String
    var category: String
    var dimensions: Dimensions
    var colorHex: String?
    var assetURL: URL?
    var photoURL: String?

    init(_ object: SceneObject, assetURL: URL?) {
        productID = object.productID; category = object.category
        dimensions = object.dimensionsM; colorHex = object.colorHex; self.assetURL = assetURL
        photoURL = object.texture?.imageURL
    }
}

/// One furniture object in a RealityKit scene: a collision-enabled container whose visible
/// content is the procedural placeholder until (and unless) the USDZ asset loads.
@MainActor
final class FurnitureNode {
    let objectID: String
    let root = ModelEntity()
    private(set) var signature: ContentSignature
    private(set) var x: Double = 0
    private(set) var z: Double = 0
    private(set) var angle: Double = 0
    private(set) var showsAsset = false
    private var content: Entity
    private var footprint: ModelEntity
    private var highlight: FootprintHighlight = .none
    private var loadTask: Task<Void, Never>?
    private var photoTask: Task<Void, Never>?

    init(object: SceneObject, assetURL: URL?) {
        objectID = object.objectID
        signature = ContentSignature(object, assetURL: assetURL)
        content = EntityFactory.placeholder(for: object)
        footprint = EntityFactory.footprint(for: object.dimensionsM)
        footprint.isEnabled = false
        root.name = object.objectID
        root.addChild(content)
        root.addChild(footprint)
        updateCollision()
        setPose(x: object.x, z: object.z, angle: object.rotationYRad, animated: false)
        loadAssetIfNeeded()
        applyPhotoIfNeeded()
    }

    var position2D: SIMD2<Double> { SIMD2(x, z) }

    func needsPoseUpdate(for object: SceneObject) -> Bool {
        abs(object.x - x) > 0.0005 || abs(object.z - z) > 0.0005 || abs(object.rotationYRad - angle) > 0.0005
    }

    func setPose(x: Double, z: Double, angle: Double, animated: Bool) {
        self.x = x; self.z = z; self.angle = angle
        let transform = Transform(scale: .one, rotation: simd_quatf(angle: Float(angle), axis: [0, 1, 0]),
                                  translation: [Float(x), 0, Float(z)])
        if animated, root.parent != nil {
            root.move(to: transform, relativeTo: root.parent, duration: 0.3, timingFunction: .easeInOut)
        } else {
            root.transform = transform
        }
    }

    /// Swaps visible content only when the appearance signature changed.
    func update(object: SceneObject, assetURL: URL?) {
        let next = ContentSignature(object, assetURL: assetURL)
        guard next != signature else { return }
        let dimensionsChanged = next.dimensions != signature.dimensions
        var sameModel = signature
        sameModel.assetURL = next.assetURL
        // Only the USDZ changed (a texture finished or was removed): keep the current model on screen
        // until the new file has loaded. The cache is keyed by URL, so the new asset is fetched fresh.
        if showsAsset, next.assetURL != nil, sameModel == next {
            signature = next
            loadAssetIfNeeded()
            return
        }
        signature = next
        showsAsset = false
        swapContent(to: EntityFactory.placeholder(for: object))
        if dimensionsChanged {
            footprint.removeFromParent()
            footprint = EntityFactory.footprint(for: object.dimensionsM)
            footprint.isEnabled = false
            root.addChild(footprint)
            let current = highlight
            highlight = .none
            setHighlight(current)
            updateCollision()
        }
        loadAssetIfNeeded()
        applyPhotoIfNeeded()
    }

    func setHighlight(_ value: FootprintHighlight) {
        guard value != highlight else { return }
        highlight = value
        footprint.isEnabled = value != .none
        let color: UIColor = switch value {
        case .none, .selected: UIColor(red: 0.31, green: 0.70, blue: 1.0, alpha: 1)
        case .invalid: UIColor(red: 0.95, green: 0.30, blue: 0.25, alpha: 1)
        case .selectedInvalid: UIColor(red: 1.0, green: 0.55, blue: 0.15, alpha: 1)
        }
        footprint.model?.materials = [EntityFactory.translucent(color, opacity: 0.45)]
    }

    func appear() {
        content.scale = SIMD3(repeating: 0.01)
        content.move(to: Transform(scale: .one, rotation: content.orientation, translation: content.position),
                     relativeTo: root, duration: 0.35, timingFunction: .easeOut)
    }

    func disappear() {
        loadTask?.cancel()
        photoTask?.cancel()
        content.move(to: Transform(scale: SIMD3(repeating: 0.01), rotation: content.orientation, translation: content.position),
                     relativeTo: root, duration: 0.25, timingFunction: .easeIn)
        let root = self.root
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(280))
            root.removeFromParent()
        }
    }

    private func swapContent(to next: Entity) {
        let old = content
        content = next
        root.addChild(next)
        if root.parent == nil { old.removeFromParent(); return }
        next.scale = SIMD3(repeating: 0.01)
        next.move(to: Transform(scale: .one, rotation: next.orientation, translation: next.position),
                  relativeTo: root, duration: 0.35, timingFunction: .easeOut)
        old.move(to: Transform(scale: SIMD3(repeating: 0.01), rotation: old.orientation, translation: old.position),
                 relativeTo: root, duration: 0.25, timingFunction: .easeIn)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(280))
            old.removeFromParent()
        }
    }

    private func updateCollision() {
        let d = signature.dimensions
        let size = SIMD3<Float>(Float(d.width), Float(max(d.height, 0.05)), Float(d.depth))
        root.components.set(CollisionComponent(shapes: [ShapeResource.generateBox(size: size).offsetBy(translation: [0, size.y / 2, 0])]))
    }

    private func loadAssetIfNeeded() {
        loadTask?.cancel()
        guard let url = signature.assetURL else { return }
        let expected = signature
        loadTask = Task { @MainActor [weak self] in
            do {
                let file = try await AssetCache.shared.localFile(for: url)
                let model = try await EntityFactory.loadModel(at: file)
                guard let self, !Task.isCancelled, self.signature == expected else { return }
                EntityFactory.fit(model, to: expected.dimensions)
                self.swapContent(to: model)
                self.showsAsset = true
            } catch {
                // Keep the dimensioned placeholder; the asset is optional.
            }
        }
    }

    private func applyPhotoIfNeeded() {
        photoTask?.cancel()
        guard let raw = signature.photoURL else { return }
        let url = raw.hasPrefix("file:") || raw.hasPrefix("http")
            ? URL(string: raw)
            : URL(fileURLWithPath: raw)
        guard let url else { return }
        let expected = signature
        photoTask = Task { @MainActor [weak self] in
            do {
                let data = url.isFileURL ? try Data(contentsOf: url) : (try await URLSession.shared.data(from: url)).0
                guard let image = UIImage(data: data), let cg = image.cgImage else { return }
                let resource = try TextureResource.generate(from: cg, options: .init(semantic: .color))
                guard let self, !Task.isCancelled, self.signature == expected else { return }
                var material = UnlitMaterial()
                material.color = .init(tint: .white, texture: .init(resource))
                Self.paint(self.content, with: material)
            } catch {}
        }
    }

    private static func paint(_ entity: Entity, with material: RealityKit.Material) {
        if let model = entity as? ModelEntity {
            model.model?.materials = [material]
        }
        for child in entity.children {
            paint(child, with: material)
        }
    }
}

@MainActor
enum EntityFactory {
    static func color(for object: SceneObject) -> UIColor {
        UIColor(hex: object.colorHex) ?? UIColor(hue: 0.56, saturation: 0.3, brightness: 0.85, alpha: 1)
    }

    static func placeholder(for object: SceneObject) -> Entity {
        let d = object.dimensionsM
        let root = Entity()
        for part in parts(category: object.category, width: Float(d.width), height: Float(d.height),
                          depth: Float(d.depth), color: color(for: object)) {
            let radius = min(part.size.x, min(part.size.y, part.size.z)) * 0.08
            let entity = ModelEntity(mesh: .generateBox(size: part.size, cornerRadius: radius),
                                     materials: [SimpleMaterial(color: part.color, roughness: 0.75, isMetallic: false)])
            entity.position = part.center
            root.addChild(entity)
        }
        return root
    }

    static func footprint(for d: Dimensions) -> ModelEntity {
        let entity = ModelEntity(mesh: .generatePlane(width: Float(d.width) + 0.04, depth: Float(d.depth) + 0.04, cornerRadius: 0.02),
                                 materials: [translucent(.systemBlue, opacity: 0.45)])
        entity.position.y = 0.006
        return entity
    }

    static func translucent(_ color: UIColor, opacity: Float, roughness: Float = 0.6) -> PhysicallyBasedMaterial {
        var material = PhysicallyBasedMaterial()
        material.baseColor = .init(tint: color)
        material.roughness = .init(floatLiteral: roughness)
        material.blending = .transparent(opacity: .init(floatLiteral: opacity))
        return material
    }

    static func loadModel(at file: URL) async throws -> Entity {
        if #available(iOS 18.0, *) {
            return try await Entity(contentsOf: file)
        }
        return try loadModelSync(at: file)
    }

    private static func loadModelSync(at file: URL) throws -> Entity {
        try Entity.load(contentsOf: file)
    }

    /// Assets are authored in meters; only rescale when the asset is clearly in the wrong unit.
    static func fit(_ model: Entity, to d: Dimensions) {
        let extents = model.visualBounds(relativeTo: nil).extents
        guard extents.x > 0.0001 else { return }
        let ratio = Float(d.width) / extents.x
        if ratio < 0.5 || ratio > 2 { model.scale *= SIMD3(repeating: ratio) }
    }

    // MARK: Room shell

    static let doorColor = UIColor(red: 0.31, green: 0.70, blue: 1.0, alpha: 1)
    static let windowColor = UIColor(red: 0.62, green: 0.90, blue: 1.0, alpha: 1)
    static let clearanceColor = UIColor(red: 1.0, green: 0.78, blue: 0.25, alpha: 1)

    /// Full room shell for the 3D view: floor, grid, back + side walls, openings, clearances.
    static func roomShell(_ room: Room) -> Entity {
        let shell = Entity()
        let w = Float(room.widthM), d = Float(room.depthM), h = Float(room.heightM)
        let floor = ModelEntity(mesh: .generateBox(size: [w, 0.04, d], cornerRadius: 0.01),
                                materials: [SimpleMaterial(color: UIColor(red: 0.93, green: 0.88, blue: 0.78, alpha: 1), roughness: 0.85, isMetallic: false)])
        floor.position.y = -0.02
        shell.addChild(floor)
        shell.addChild(grid(width: w, depth: d))

        let wallThickness: Float = 0.06
        let back = ModelEntity(mesh: .generateBox(size: [w + wallThickness * 2, h, wallThickness]),
                               materials: [SimpleMaterial(color: UIColor(white: 0.98, alpha: 1), roughness: 0.9, isMetallic: false)])
        back.position = [0, h / 2, -d / 2 - wallThickness / 2]
        shell.addChild(back)
        for side: Float in [-1, 1] {
            let wall = ModelEntity(mesh: .generateBox(size: [wallThickness, h, d]),
                                   materials: [translucent(UIColor(white: 1, alpha: 1), opacity: 0.28, roughness: 0.3)])
            wall.position = [side * (w / 2 + wallThickness / 2), h / 2, 0]
            shell.addChild(wall)
        }
        for opening in room.openings { shell.addChild(openingMarker(opening, room: room)) }
        for clearance in room.clearances { shell.addChild(clearancePatch(clearance)) }
        return shell
    }

    /// Floor-level reference for AR: room outline, clearances and an origin-corner marker.
    static func floorOutline(_ room: Room) -> Entity {
        let outline = Entity()
        let w = Float(room.widthM), d = Float(room.depthM), t: Float = 0.025
        let material = translucent(doorColor, opacity: 0.8)
        let edges: [(SIMD3<Float>, SIMD3<Float>)] = [
            ([w, 0.004, t], [0, 0.002, -d / 2]), ([w, 0.004, t], [0, 0.002, d / 2]),
            ([t, 0.004, d], [-w / 2, 0.002, 0]), ([t, 0.004, d], [w / 2, 0.002, 0])
        ]
        for (size, center) in edges {
            let edge = ModelEntity(mesh: .generateBox(size: size), materials: [material])
            edge.position = center
            outline.addChild(edge)
        }
        let corner = ModelEntity(mesh: .generateSphere(radius: 0.04),
                                 materials: [SimpleMaterial(color: UIColor(red: 0.36, green: 0.80, blue: 0.36, alpha: 1), isMetallic: false)])
        corner.position = [-w / 2, 0.04, -d / 2]
        outline.addChild(corner)
        for opening in room.openings { outline.addChild(openingMarker(opening, room: room, floorOnly: true)) }
        for clearance in room.clearances { outline.addChild(clearancePatch(clearance)) }
        return outline
    }

    private static func grid(width w: Float, depth d: Float) -> Entity {
        let grid = Entity()
        let material = translucent(.white, opacity: 0.55)
        let step: Float = 0.5
        var x = -w / 2 + step
        while x < w / 2 - 0.01 {
            let line = ModelEntity(mesh: .generateBox(size: [0.008, 0.002, d]), materials: [material])
            line.position = [x, 0.001, 0]; grid.addChild(line); x += step
        }
        var z = -d / 2 + step
        while z < d / 2 - 0.01 {
            let line = ModelEntity(mesh: .generateBox(size: [w, 0.002, 0.008]), materials: [material])
            line.position = [0, 0.001, z]; grid.addChild(line); z += step
        }
        return grid
    }

    /// Interprets `offset_m` as the opening's center along its wall, in scene coordinates
    /// (X for front/back walls, Z for left/right). docs/API.md does not pin this down; this
    /// reading is the one consistent with its door/clearance example.
    static func openingCenterAlongWall(_ opening: Opening) -> Float { Float(opening.offsetM) }

    private static func openingMarker(_ opening: Opening, room: Room, floorOnly: Bool = false) -> Entity {
        let w = Float(room.widthM), d = Float(room.depthM), h = Float(room.heightM)
        let isDoor = opening.kind == "door"
        // The 3D view has no front wall (the camera looks in from there), so front openings
        // are drawn on the floor only instead of as a slab blocking the view.
        let floorOnly = floorOnly || opening.wall == "front"
        let height: Float = floorOnly ? 0.004 : (isDoor ? min(2.05, h - 0.05) : min(1.2, h - 1.0))
        let bottom: Float = floorOnly ? 0 : (isDoor ? 0 : 0.9)
        let along = openingCenterAlongWall(opening), width = Float(opening.widthM), inset: Float = 0.02
        let thickness: Float = floorOnly ? 0.12 : 0.025
        let size: SIMD3<Float>, center: SIMD3<Float>
        switch opening.wall {
        case "left": size = [thickness, height, width]; center = [-w / 2 + inset, bottom + height / 2, along]
        case "right": size = [thickness, height, width]; center = [w / 2 - inset, bottom + height / 2, along]
        case "front": size = [width, height, thickness]; center = [along, bottom + height / 2, d / 2 - inset]
        default: size = [width, height, thickness]; center = [along, bottom + height / 2, -d / 2 + inset]
        }
        let marker = ModelEntity(mesh: .generateBox(size: size),
                                 materials: [translucent(isDoor ? doorColor : windowColor, opacity: isDoor ? 0.85 : 0.6, roughness: 0.2)])
        marker.position = center
        if !floorOnly, isDoor {
            // Walls can be translucent or absent (front), so doors are also marked on the floor.
            let sideways = opening.wall == "left" || opening.wall == "right"
            let threshold = ModelEntity(mesh: .generateBox(size: sideways ? [0.14, 0.004, width] : [width, 0.004, 0.14]),
                                        materials: [SimpleMaterial(color: doorColor, roughness: 0.4, isMetallic: false)])
            threshold.position = [0, -center.y + 0.003, 0]
            marker.addChild(threshold)
        }
        return marker
    }

    private static func clearancePatch(_ clearance: Clearance) -> Entity {
        let patch = ModelEntity(mesh: .generatePlane(width: Float(clearance.widthM), depth: Float(clearance.depthM), cornerRadius: 0.03),
                                materials: [translucent(clearanceColor, opacity: 0.35)])
        patch.position = [Float(clearance.xM), 0.003, Float(clearance.zM)]
        let text = MeshResource.generateText(clearance.label, extrusionDepth: 0.001, font: .systemFont(ofSize: 0.09, weight: .semibold))
        let label = ModelEntity(mesh: text, materials: [SimpleMaterial(color: UIColor(red: 0.45, green: 0.30, blue: 0.0, alpha: 1), isMetallic: false)])
        let bounds = text.bounds
        label.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])
        label.position = [-bounds.center.x, 0.002, bounds.center.y]
        patch.addChild(label)
        return patch
    }
}
