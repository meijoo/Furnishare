import SwiftUI

enum RoomScene: String {
    case living, bedroom, kitchen, dining, bathroom, createGroup, joinGroup, solo

    init(kind: RoomKind) {
        switch kind {
        case .living: self = .living
        case .bedroom: self = .bedroom
        case .kitchen: self = .kitchen
        case .dining: self = .dining
        case .bathroom: self = .bathroom
        default: self = .living
        }
    }

    init(mode: LivingMode) {
        switch mode {
        case .createGroup: self = .createGroup
        case .joinGroup: self = .joinGroup
        case .solo: self = .solo
        }
    }
}

/// Flat interior scenes in the FurniShare Figma style.
struct RoomIllustration: View {
    let scene: RoomScene

    var body: some View {
        Canvas { context, size in
            let w = size.width
            let h = size.height
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(wall))

            // Window
            let win = CGRect(x: w * 0.52, y: h * 0.08, width: w * 0.36, height: h * 0.28)
            context.fill(Path(roundedRect: win, cornerRadius: 8), with: .linearGradient(
                Gradient(colors: [Color(red: 0.55, green: 0.75, blue: 0.92), Color(red: 0.82, green: 0.90, blue: 0.96)]),
                startPoint: CGPoint(x: win.midX, y: win.minY),
                endPoint: CGPoint(x: win.midX, y: win.maxY)
            ))
            // Window plants
            if scene != .bathroom {
                for i in 0..<3 {
                    let px = win.minX + 12 + CGFloat(i) * 16
                    context.fill(Path(ellipseIn: CGRect(x: px, y: win.maxY - 28, width: 10, height: 22)),
                                 with: .color(Color(red: 0.22, green: 0.42, blue: 0.28)))
                }
            }

            // Floor
            context.fill(Path(CGRect(x: 0, y: h * 0.52, width: w, height: h * 0.48)),
                         with: .color(Color(red: 0.91, green: 0.86, blue: 0.78)))

            switch scene {
            case .living, .createGroup:
                drawSofa(context, size)
                drawPlant(context, at: CGPoint(x: w * 0.14, y: h * 0.62), scale: min(w, h) / 180)
            case .bedroom, .solo:
                drawBed(context, size, laptop: false)
                if scene == .solo { drawDesk(context, size) }
            case .joinGroup:
                drawBed(context, size, laptop: true)
            case .kitchen:
                drawKitchen(context, size)
            case .dining:
                drawDining(context, size)
            case .bathroom:
                drawBath(context, size)
            }
        }
        .accessibilityHidden(true)
    }

    private var wall: Color {
        switch scene {
        case .kitchen: Color(red: 0.96, green: 0.97, blue: 0.98)
        case .bathroom: Color(red: 0.94, green: 0.97, blue: 0.99)
        default: Color(red: 0.97, green: 0.96, blue: 0.93)
        }
    }

    private func drawSofa(_ context: GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        let sofa = CGRect(x: w * 0.08, y: h * 0.36, width: w * 0.62, height: h * 0.38)
        context.fill(Path(roundedRect: CGRect(x: sofa.minX, y: sofa.minY + sofa.height * 0.35, width: sofa.width, height: sofa.height * 0.65), cornerRadius: 10),
                     with: .color(Color(red: 0.72, green: 0.82, blue: 0.93)))
        context.fill(Path(roundedRect: CGRect(x: sofa.minX, y: sofa.minY, width: sofa.width, height: sofa.height * 0.42), cornerRadius: 10),
                     with: .color(Color(red: 0.64, green: 0.76, blue: 0.90)))
        context.fill(Path(roundedRect: CGRect(x: sofa.minX + 8, y: sofa.minY + sofa.height * 0.45, width: sofa.width * 0.28, height: sofa.height * 0.28), cornerRadius: 6),
                     with: .color(Color(red: 0.82, green: 0.88, blue: 0.94)))
        let table = CGRect(x: w * 0.20, y: h * 0.78, width: w * 0.30, height: h * 0.08)
        context.fill(Path(roundedRect: table, cornerRadius: 4), with: .color(Color(red: 0.78, green: 0.64, blue: 0.44)))
    }

    private func drawBed(_ context: GraphicsContext, _ size: CGSize, laptop: Bool) {
        let w = size.width, h = size.height
        let bed = CGRect(x: w * 0.08, y: h * 0.34, width: w * 0.64, height: h * 0.42)
        context.fill(Path(roundedRect: CGRect(x: bed.minX, y: bed.minY + bed.height * 0.35, width: bed.width, height: bed.height * 0.65), cornerRadius: 8),
                     with: .color(Color(red: 0.78, green: 0.64, blue: 0.48)))
        context.fill(Path(roundedRect: CGRect(x: bed.minX + 6, y: bed.minY + bed.height * 0.2, width: bed.width - 12, height: bed.height * 0.55), cornerRadius: 6),
                     with: .color(.white))
        context.fill(Path(roundedRect: CGRect(x: bed.minX + 10, y: bed.minY, width: bed.width * 0.28, height: bed.height * 0.28), cornerRadius: 5),
                     with: .color(Color(red: 0.88, green: 0.91, blue: 0.95)))
        context.fill(Path(roundedRect: CGRect(x: bed.minX + bed.width * 0.42, y: bed.minY, width: bed.width * 0.28, height: bed.height * 0.28), cornerRadius: 5),
                     with: .color(Color(red: 0.55, green: 0.68, blue: 0.84)))
        if laptop {
            context.fill(Path(roundedRect: CGRect(x: bed.midX - 16, y: bed.minY + 8, width: 32, height: 20), cornerRadius: 3),
                         with: .color(Color(red: 0.16, green: 0.16, blue: 0.18)))
        }
        // Nightstand
        context.fill(Path(roundedRect: CGRect(x: w * 0.78, y: h * 0.58, width: w * 0.12, height: h * 0.14), cornerRadius: 4),
                     with: .color(Color(red: 0.72, green: 0.58, blue: 0.40)))
    }

    private func drawDesk(_ context: GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        context.fill(Path(roundedRect: CGRect(x: w * 0.72, y: h * 0.52, width: w * 0.20, height: 8), cornerRadius: 2),
                     with: .color(Color(red: 0.70, green: 0.55, blue: 0.38)))
        context.fill(Path(CGRect(x: w * 0.74, y: h * 0.52, width: 4, height: h * 0.18)), with: .color(Color(red: 0.55, green: 0.42, blue: 0.28)))
        context.fill(Path(CGRect(x: w * 0.88, y: h * 0.52, width: 4, height: h * 0.18)), with: .color(Color(red: 0.55, green: 0.42, blue: 0.28)))
    }

    private func drawKitchen(_ context: GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        context.fill(Path(roundedRect: CGRect(x: 0, y: h * 0.38, width: w, height: h * 0.18), cornerRadius: 0),
                     with: .color(Color.white))
        context.fill(Path(CGRect(x: 0, y: h * 0.54, width: w, height: 8)), with: .color(Color(red: 0.85, green: 0.87, blue: 0.90)))
        context.fill(Path(roundedRect: CGRect(x: w * 0.22, y: h * 0.58, width: w * 0.46, height: h * 0.16), cornerRadius: 8),
                     with: .color(Color(red: 0.90, green: 0.91, blue: 0.93)))
        context.fill(Path(ellipseIn: CGRect(x: w * 0.30, y: h * 0.52, width: 16, height: 16)),
                     with: .color(Color(red: 0.75, green: 0.55, blue: 0.32)))
        context.fill(Path(ellipseIn: CGRect(x: w * 0.48, y: h * 0.54, width: 10, height: 10)),
                     with: .color(Color(red: 0.55, green: 0.55, blue: 0.58)))
    }

    private func drawDining(_ context: GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        context.fill(Path(ellipseIn: CGRect(x: w * 0.22, y: h * 0.58, width: w * 0.46, height: h * 0.12)),
                     with: .color(Color(red: 0.72, green: 0.56, blue: 0.38)))
        context.fill(Path(roundedRect: CGRect(x: w * 0.18, y: h * 0.52, width: 16, height: h * 0.18), cornerRadius: 4),
                     with: .color(Color(red: 0.78, green: 0.64, blue: 0.46)))
        context.fill(Path(roundedRect: CGRect(x: w * 0.70, y: h * 0.52, width: 16, height: h * 0.18), cornerRadius: 4),
                     with: .color(Color(red: 0.78, green: 0.64, blue: 0.46)))
        context.stroke(Path(ellipseIn: CGRect(x: w * 0.40, y: h * 0.20, width: 36, height: 14)),
                       with: .color(Color(red: 0.75, green: 0.72, blue: 0.62)), lineWidth: 3)
    }

    private func drawBath(_ context: GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        context.fill(Path(roundedRect: CGRect(x: w * 0.18, y: h * 0.52, width: w * 0.42, height: h * 0.22), cornerRadius: 10),
                     with: .color(.white))
        context.stroke(Path(roundedRect: CGRect(x: w * 0.18, y: h * 0.52, width: w * 0.42, height: h * 0.22), cornerRadius: 10),
                       with: .color(Color(red: 0.72, green: 0.80, blue: 0.88)), lineWidth: 3)
        context.fill(Path(roundedRect: CGRect(x: w * 0.68, y: h * 0.28, width: 10, height: h * 0.36), cornerRadius: 4),
                     with: .color(Color(red: 0.70, green: 0.80, blue: 0.88)))
    }

    private func drawPlant(_ context: GraphicsContext, at origin: CGPoint, scale: CGFloat) {
        context.fill(Path(ellipseIn: CGRect(x: origin.x, y: origin.y - 28 * scale, width: 16 * scale, height: 28 * scale)),
                     with: .color(Color(red: 0.22, green: 0.45, blue: 0.32)))
        context.fill(Path(ellipseIn: CGRect(x: origin.x + 10 * scale, y: origin.y - 22 * scale, width: 12 * scale, height: 22 * scale)),
                     with: .color(Color(red: 0.30, green: 0.55, blue: 0.38)))
        context.fill(Path(roundedRect: CGRect(x: origin.x + 6 * scale, y: origin.y - 4 * scale, width: 14 * scale, height: 10 * scale), cornerRadius: 2),
                     with: .color(Color(red: 0.78, green: 0.60, blue: 0.40)))
    }
}

extension RoomKind {
    var scene: RoomScene { RoomScene(kind: self) }
}
