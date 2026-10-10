import SwiftUI

struct Furniture: Identifiable, Hashable {
    let id: String
    let name: String
    let category: String
    let price: Int
    let width: Float
    let height: Float
    let depth: Float
    let hue: Double
    var color: UIColor { UIColor(hue: hue, saturation: 0.38, brightness: 0.82, alpha: 1) }
    var dimensions: String { String(format: "%.2f × %.2f × %.2f m", width, depth, height) }
    static let samples: [Furniture] = [
        .init(id: "sofa-blue", name: "Cloud sofa", category: "sofa", price: 60000, width: 2.1, height: 0.85, depth: 0.9, hue: 0.56),
        .init(id: "sofa-compact", name: "Cove loveseat", category: "sofa", price: 45000, width: 1.65, height: 0.8, depth: 0.85, hue: 0.55),
        .init(id: "sofa-green", name: "Meadow sofa", category: "sofa", price: 52000, width: 1.9, height: 0.85, depth: 0.88, hue: 0.35),
        .init(id: "table", name: "Pebble table", category: "table", price: 12000, width: 1.0, height: 0.42, depth: 0.55, hue: 0.10),
        .init(id: "rug", name: "Lagoon rug", category: "rug", price: 8000, width: 2.3, height: 0.015, depth: 1.6, hue: 0.47),
        .init(id: "tv", name: "Horizon television", category: "tv", price: 30000, width: 1.12, height: 0.7, depth: 0.22, hue: 0.62)
    ]
}

struct FurniturePart {
    let size: SIMD3<Float>
    let center: SIMD3<Float>
    let color: UIColor
}

// Shared geometry contract: meters, Y up, origin at floor-center of the footprint.
func parts(for item: Furniture) -> [FurniturePart] {
    parts(category: item.category, width: item.width, height: item.height, depth: item.depth, color: item.color)
}

func parts(category: String, width w: Float, height h: Float, depth d: Float, color: UIColor) -> [FurniturePart] {
    func box(_ size: SIMD3<Float>, _ center: SIMD3<Float>, _ color: UIColor) -> FurniturePart {
        FurniturePart(size: size, center: center, color: color)
    }
    switch category {
    case "sofa":
        return [box([w, h * 0.38, d], [0, h * 0.35, 0], color),
                box([w, h * 0.65, d * 0.17], [0, h * 0.675, -d * 0.415], color),
                box([w * 0.08, h * 0.6, d], [-w * 0.46, h * 0.5, 0], color),
                box([w * 0.08, h * 0.6, d], [w * 0.46, h * 0.5, 0], color)] + [-1 as Float, 1].flatMap { x in
                    [-1 as Float, 1].map { z in box([0.08, h * 0.16, 0.08], [x * w * 0.4, h * 0.08, z * d * 0.35], .darkGray) }
                }
    case "table", "coffee_table":
        return [box([w, 0.07, d], [0, h - 0.035, 0], color)] + [-1 as Float, 1].flatMap { x in
            [-1 as Float, 1].map { z in box([0.055, h - 0.07, 0.055], [x * w * 0.4, (h - 0.07) / 2, z * d * 0.35], .brown) }
        }
    case "bed":
        return [box([w, h * 0.3, d], [0, h * 0.15, 0], color),
                box([w * 0.96, h * 0.2, d * 0.9], [0, h * 0.4, d * 0.04], .white),
                box([w, h, 0.08], [0, h / 2, -d / 2 + 0.04], color),
                box([w * 0.36, h * 0.08, 0.3], [-w * 0.22, h * 0.54, -d / 2 + 0.3], .white),
                box([w * 0.36, h * 0.08, 0.3], [w * 0.22, h * 0.54, -d / 2 + 0.3], .white)]
    case "desk":
        let legHeight = h - 0.04, legX = w / 2 - 0.04, legZ = d / 2 - 0.04
        var desk = [box([w, 0.04, d], [0, h - 0.02, 0], color)]
        for x: Float in [-1, 1] {
            for z: Float in [-1, 1] {
                desk.append(box([0.04, legHeight, 0.04], SIMD3<Float>(x * legX, legHeight / 2, z * legZ), .darkGray))
            }
        }
        return desk
    case "tv":
        return [box([w, h * 0.85, 0.05], [0, h * 0.575, 0], .darkGray),
                box([w * 0.94, h * 0.76, 0.008], [0, h * 0.575, 0.029], color),
                box([w * 0.5, 0.04, d], [0, 0.02, 0], .darkGray),
                box([0.08, h * 0.2, 0.06], [0, h * 0.1, 0], .darkGray)]
    default: return [box([w, max(h, 0.005), d], [0, max(h, 0.005) / 2, 0], color)]
    }
}

func dollars(_ cents: Int) -> String { (Double(cents) / 100).formatted(.currency(code: "USD")) }

/// Plan meters shown the way people measure rooms: `12' × 14'`.
func feetLabel(widthM: Double, depthM: Double) -> String {
    let width = Int((widthM * 3.28084).rounded())
    let depth = Int((depthM * 3.28084).rounded())
    return "\(width)' × \(depth)'"
}

extension UIColor {
    convenience init?(hex: String?) {
        guard var s = hex?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let value = UInt32(s, radix: 16) else { return nil }
        self.init(red: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255,
                  blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }
}
