import SwiftUI

struct BrandMark: View {
    var compact = false
    var prominent = false

    var body: some View {
        HStack(spacing: prominent ? 16 : 8) {
            Image(systemName: "house.fill")
                .font(prominent ? .system(size: 34) : compact ? .body : .title3)
                .foregroundStyle(.white)
                .frame(width: prominent ? 72 : compact ? 32 : 38, height: prominent ? 72 : compact ? 32 : 38)
                .background(RoundedRectangle(cornerRadius: prominent ? 18 : 10, style: .continuous).fill(Color.aeroSky))
            Text("Furnishare")
                .font(prominent ? .system(size: 44, weight: .bold) : compact ? .headline : .title3.weight(.semibold))
                .foregroundStyle(Color.aeroInk)
                .minimumScaleFactor(0.7)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Furnishare")
    }
}

struct SplitHeadline: View {
    let lead: String
    let accent: String
    var size: Font = .largeTitle.bold()

    var body: some View {
        (Text(lead).foregroundStyle(Color.aeroInk) + Text(accent).foregroundStyle(Color.aeroSky))
            .font(size)
            .multilineTextAlignment(.center)
    }
}

struct FlowStepBar: View {
    let current: Int
    let total: Int
    var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<max(0, total), id: \.self) { index in
                Capsule()
                    .fill(index + 1 <= current ? Color.aeroSky : Color.black.opacity(0.08))
                    .frame(width: 28, height: 5)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(current) of \(total)")
    }
}

struct FlowScreen<Content: View>: View {
    var maxWidth: CGFloat = 720
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            content
                .frame(maxWidth: maxWidth)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 24)
                .padding(.vertical, 20)
        }
        .scrollIndicators(.hidden)
    }
}

struct FlowField: View {
    let title: String
    let symbol: String
    var prompt: String
    @Binding var text: String
    var keyboard: UIKeyboardType = .default
    var secure = false
    var username = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption.weight(.semibold)).foregroundStyle(Color.figmaMuted)
            HStack(spacing: 10) {
                Image(systemName: symbol).foregroundStyle(Color.figmaMuted).frame(width: 20)
                if secure {
                    SecureField(prompt, text: $text)
                } else {
                    TextField(prompt, text: $text)
                        .keyboardType(keyboard)
                        .textInputAutocapitalization(username || keyboard == .emailAddress ? .never : .words)
                        .autocorrectionDisabled(username || keyboard == .emailAddress || keyboard == .URL)
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.white))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.black.opacity(0.08), lineWidth: 1))
        }
    }
}

struct MemberAvatars: View {
    let names: [String]
    var extra = 0

    var body: some View {
        HStack(spacing: -8) {
            ForEach(Array(names.prefix(4).enumerated()), id: \.offset) { index, name in
                Text(initials(name))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color.aeroInk)
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(Color.white))
                    .overlay(Circle().strokeBorder(Color.white, lineWidth: 2))
                    .shadow(color: .black.opacity(0.08), radius: 2, y: 1)
                    .zIndex(Double(4 - index))
            }
            if extra > 0 || names.count > 4 {
                Text("+\(extra + max(0, names.count - 4))")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color.aeroSky)
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(Color.figmaWash))
            }
        }
        .accessibilityLabel(names.joined(separator: ", "))
    }

    private func initials(_ name: String) -> String {
        let parts = name.split(separator: " ")
        let letters = parts.prefix(2).compactMap(\.first)
        return String(letters).uppercased()
    }
}

struct HowItWorksRow: View {
    let number: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.caption.weight(.heavy))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(Circle().fill(Color.aeroSky))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.aeroInk)
                Text(detail).font(.caption).foregroundStyle(Color.figmaMuted)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

struct SettingsGearButton: View {
    @Environment(AppNavigation.self) private var nav
    static let reservedWidth: CGFloat = 56

    var body: some View {
        Button { nav.showSettings = true } label: {
            Image(systemName: "gearshape").accessibilityLabel("Settings")
        }
        .buttonStyle(GlassChipStyle())
    }
}

struct SidebarRow: View {
    let title: String
    let symbol: String
    var selected = false
    var disabled = false

    var body: some View {
        Label(title, systemImage: symbol)
            .font(.subheadline.weight(selected ? .semibold : .medium))
            .foregroundStyle(disabled ? Color.figmaMuted.opacity(0.7) : (selected ? Color.aeroSky : Color.aeroInk))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(selected ? Color.figmaWash : Color.clear))
    }
}
