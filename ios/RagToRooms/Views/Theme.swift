import SwiftUI

// FurniShare Figma: white page, bright blue actions, soft cards.

extension Color {
    static let aeroSky = Color(red: 0.23, green: 0.51, blue: 0.97)     // #3B82F6
    static let aeroGrass = Color(red: 0.34, green: 0.80, blue: 0.56)    // mint from Join card
    static let aeroInk = Color(red: 0.07, green: 0.09, blue: 0.15)      // #111827
    static let aeroAmber = Color(red: 0.95, green: 0.62, blue: 0.10)
    static let aeroRed = Color(red: 0.88, green: 0.25, blue: 0.22)
    static let figmaPage = Color(red: 0.98, green: 0.99, blue: 1.0)
    static let figmaMuted = Color(red: 0.39, green: 0.45, blue: 0.55)
    static let figmaWash = Color(red: 0.93, green: 0.96, blue: 1.0)
}

struct AeroBackground: View {
    var body: some View {
        ZStack {
            Color.figmaPage
            GeometryReader { proxy in
                let size = proxy.size
                Ellipse()
                    .fill(Color(red: 0.86, green: 0.93, blue: 1.0))
                    .frame(width: size.width * 0.9, height: size.height * 0.55)
                    .position(x: size.width * 0.92, y: size.height * 0.08)
                    .blur(radius: 40)
                Ellipse()
                    .fill(Color(red: 0.88, green: 0.98, blue: 0.94).opacity(0.9))
                    .frame(width: size.width * 0.85, height: size.height * 0.45)
                    .position(x: size.width * 0.1, y: size.height * 0.95)
                    .blur(radius: 36)
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}

struct GlassPanel: ViewModifier {
    var cornerRadius: CGFloat = 24
    var padding: CGFloat = 16

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
            .padding(padding)
            .background(shape.fill(Color.white))
            .overlay(shape.strokeBorder(Color.black.opacity(0.04), lineWidth: 1))
            .shadow(color: .black.opacity(0.06), radius: 18, y: 8)
    }
}

extension View {
    func glassPanel(cornerRadius: CGFloat = 24, padding: CGFloat = 16) -> some View {
        modifier(GlassPanel(cornerRadius: cornerRadius, padding: padding))
    }
}

struct AeroButtonStyle: ButtonStyle {
    var tint: Color = .aeroSky
    var compact = false

    func makeBody(configuration: Configuration) -> some View {
        AeroButtonBody(configuration: configuration, tint: tint, compact: compact)
    }

    private struct AeroButtonBody: View {
        let configuration: ButtonStyleConfiguration
        let tint: Color
        let compact: Bool
        @Environment(\.isEnabled) private var isEnabled

        var body: some View {
            configuration.label
                .font(compact ? .subheadline.weight(.semibold) : .headline)
                .foregroundStyle(.white)
                .padding(.horizontal, compact ? 14 : 20)
                .padding(.vertical, compact ? 8 : 12)
                .background(Capsule().fill(isEnabled ? tint : Color.gray.opacity(0.45)))
                .opacity(configuration.isPressed ? 0.85 : 1)
                .scaleEffect(configuration.isPressed ? 0.98 : 1)
        }
    }
}

struct AeroWideButtonStyle: ButtonStyle {
    var tint: Color = .aeroSky
    var outlined = false

    func makeBody(configuration: Configuration) -> some View {
        AeroWideButtonBody(configuration: configuration, tint: tint, outlined: outlined)
    }

    private struct AeroWideButtonBody: View {
        let configuration: ButtonStyleConfiguration
        let tint: Color
        let outlined: Bool
        @Environment(\.isEnabled) private var isEnabled

        var body: some View {
            let shape = RoundedRectangle(cornerRadius: 14, style: .continuous)
            configuration.label
                .font(.headline)
                .foregroundStyle(outlined ? Color.aeroInk : .white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(shape.fill(outlined ? Color.white : (isEnabled ? tint : Color.gray.opacity(0.45))))
                .overlay(shape.strokeBorder(outlined ? Color.black.opacity(0.08) : Color.clear, lineWidth: 1))
                .opacity(configuration.isPressed ? 0.85 : (isEnabled ? 1 : 0.7))
        }
    }
}

struct GlassChipStyle: ButtonStyle {
    var selected = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.medium))
            .foregroundStyle(selected ? Color.aeroSky : Color.aeroInk)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(Capsule().fill(selected ? Color.figmaWash : Color.white))
            .overlay(Capsule().strokeBorder(selected ? Color.aeroSky.opacity(0.25) : Color.black.opacity(0.06), lineWidth: 1))
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

struct PanelHeader: View {
    let title: String
    let symbol: String
    var trailing: String?

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).font(.headline).foregroundStyle(Color.aeroSky)
            Text(title).font(.title3.bold()).foregroundStyle(Color.aeroInk)
            Spacer()
            if let trailing { Text(trailing).font(.caption).foregroundStyle(Color.figmaMuted) }
        }
    }
}

struct StatusBadge: View {
    let text: String
    let symbol: String
    var tint: Color = .aeroInk

    var body: some View {
        Label(text, systemImage: symbol)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(Capsule().fill(Color.figmaWash))
            .accessibilityElement(children: .combine)
    }
}

extension OperationState {
    var tint: Color {
        switch self {
        case .confirmed: Color(red: 0.13, green: 0.55, blue: 0.20)
        case .failed: .aeroRed
        case .unknown: .aeroAmber
        default: Color(red: 0.10, green: 0.42, blue: 0.75)
        }
    }
}

struct ConnectionIndicator: View {
    let status: ConnectionStatus
    let offlineDemo: Bool

    var body: some View {
        let (text, tint): (String, Color) = switch status {
        case .live: ("Live", Color(red: 0.13, green: 0.55, blue: 0.20))
        case .polling: ("Live", Color(red: 0.10, green: 0.42, blue: 0.75))
        case .connecting: ("Connecting…", .aeroInk)
        case .offline: (offlineDemo ? "Demo" : "Offline", .aeroAmber)
        }
        StatusBadge(text: text, symbol: status.symbol, tint: tint)
            .help(statusDetail)
            .accessibilityLabel("Connection: \(text). \(statusDetail)")
    }

    private var statusDetail: String {
        if case .offline(let reason) = status { return reason }
        return ""
    }
}
