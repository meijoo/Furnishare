import SwiftUI

struct BrandMark: View {
    var compact = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "house.fill")
                .font(compact ? .body : .title3)
                .foregroundStyle(.white)
                .frame(width: compact ? 32 : 38, height: compact ? 32 : 38)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.aeroSky))
            Text("Furnishare")
                .font(compact ? .headline : .title3.weight(.semibold))
                .foregroundStyle(Color.aeroInk)
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
    var captions: [String] = []

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 6) {
                ForEach(1...total, id: \.self) { step in
                    Capsule()
                        .fill(step <= current ? Color.aeroSky : Color.black.opacity(0.08))
                        .frame(width: step == current ? 40 : 28, height: 5)
                }
            }
            if !captions.isEmpty {
                HStack(spacing: 16) {
                    ForEach(Array(captions.enumerated()), id: \.offset) { index, caption in
                        Text(caption)
                            .font(.caption.weight(index + 1 == current ? .semibold : .regular))
                            .foregroundStyle(index + 1 <= current ? Color.aeroInk : Color.figmaMuted)
                    }
                }
            } else {
                Text("\(current) of \(total)").font(.caption.weight(.semibold)).foregroundStyle(Color.figmaMuted)
            }
        }
        .accessibilityElement(children: .combine)
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
                        .textInputAutocapitalization(keyboard == .emailAddress ? .never : .words)
                        .autocorrectionDisabled(keyboard == .emailAddress || keyboard == .URL)
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
