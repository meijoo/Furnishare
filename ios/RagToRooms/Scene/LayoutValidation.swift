import Foundation
import simd

/// A footprint on the floor plane (X/Z), centered at `center`, rotated by `angle` about +Y.
struct OrientedRect: Equatable {
    var center: SIMD2<Double>
    var halfSize: SIMD2<Double>   // (width / 2, depth / 2)
    var angle: Double

    /// Local +X and +Z axes in floor coordinates. Rotation about +Y by θ maps
    /// local (x, z) to (x cosθ + z sinθ, −x sinθ + z cosθ).
    var axes: (SIMD2<Double>, SIMD2<Double>) {
        let c = cos(angle), s = sin(angle)
        return (SIMD2(c, -s), SIMD2(s, c))
    }

    var corners: [SIMD2<Double>] {
        let (ax, az) = axes
        let ex = ax * halfSize.x, ez = az * halfSize.y
        return [center + ex + ez, center + ex - ez, center - ex - ez, center - ex + ez]
    }

    /// Separating axis test. Rectangles that merely touch (overlap ≤ tolerance) do not intersect.
    func intersects(_ other: OrientedRect, tolerance: Double = 0.005) -> Bool {
        let (a1, a2) = axes, (b1, b2) = other.axes
        let mine = corners, theirs = other.corners
        for axis in [a1, a2, b1, b2] {
            let p = mine.map { simd_dot($0, axis) }, q = theirs.map { simd_dot($0, axis) }
            let overlap = min(p.max()!, q.max()!) - max(p.min()!, q.min()!)
            if overlap <= tolerance { return false }
        }
        return true
    }
}

struct LayoutHint: Identifiable, Hashable {
    enum Kind: Hashable { case outOfBounds, overlap, clearance }
    let kind: Kind
    let objectIDs: [String]
    let message: String
    var id: String { "\(kind)-\(objectIDs.joined(separator: "+"))-\(message)" }

    var symbol: String {
        switch kind {
        case .outOfBounds: "rectangle.dashed.badge.record"
        case .overlap: "square.on.square.intersection.dashed"
        case .clearance: "figure.walk.motion"
        }
    }
}

struct LayoutReport {
    var hints: [LayoutHint] = []
    var invalidIDs: Set<String> { Set(hints.flatMap(\.objectIDs)) }
    func hints(for objectID: String) -> [LayoutHint] { hints.filter { $0.objectIDs.contains(objectID) } }
}

enum LayoutValidation {
    static func footprint(_ object: SceneObject) -> OrientedRect {
        OrientedRect(center: SIMD2(object.x, object.z),
                     halfSize: SIMD2(object.dimensionsM.width / 2, object.dimensionsM.depth / 2),
                     angle: object.rotationYRad)
    }

    static func rect(_ clearance: Clearance) -> OrientedRect {
        OrientedRect(center: SIMD2(clearance.xM, clearance.zM),
                     halfSize: SIMD2(clearance.widthM / 2, clearance.depthM / 2), angle: 0)
    }

    /// Rugs are meant to sit under other furniture and may be walked over, so they are only
    /// checked against the room bounds.
    static func isFloorCovering(_ object: SceneObject) -> Bool { object.category == "rug" }

    static func validate(objects: [SceneObject], room: Room, name: (SceneObject) -> String) -> LayoutReport {
        var report = LayoutReport()
        let halfW = room.widthM / 2, halfD = room.depthM / 2, tol = 0.005
        let rects = objects.map(footprint)

        for (object, rect) in zip(objects, rects) {
            let outside = rect.corners.contains { abs($0.x) > halfW + tol || abs($0.y) > halfD + tol }
            if outside {
                report.hints.append(.init(kind: .outOfBounds, objectIDs: [object.objectID],
                                          message: "\(name(object)) extends outside the room"))
            }
        }

        for i in objects.indices where !isFloorCovering(objects[i]) {
            for j in objects.indices where j > i && !isFloorCovering(objects[j]) {
                if rects[i].intersects(rects[j]) {
                    report.hints.append(.init(kind: .overlap, objectIDs: [objects[i].objectID, objects[j].objectID],
                                              message: "\(name(objects[i])) overlaps \(name(objects[j]))"))
                }
            }
            for clearance in room.clearances where rects[i].intersects(rect(clearance)) {
                report.hints.append(.init(kind: .clearance, objectIDs: [objects[i].objectID],
                                          message: "\(name(objects[i])) blocks the \(clearance.label) clearance"))
            }
        }
        return report
    }
}
