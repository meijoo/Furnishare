import SwiftUI

/// Quiet aquatic accents shared across the app's pages.
struct AquaticBackground: View {
    // Pale blue from the welcome screen reference (#DBECFC).
    private static let bubbleBlue = Color(red: 219.0 / 255, green: 236.0 / 255, blue: 252.0 / 255)

    var body: some View {
        GeometryReader { proxy in
            let bubbleSize = min(180.0, proxy.size.width * 0.18)
            ZStack {
                LinearGradient(
                    colors: [Self.bubbleBlue, .white,
                             Color(red: 0.91, green: 0.98, blue: 0.95)],
                    startPoint: .topTrailing, endPoint: .bottomLeading
                )
                HStack(alignment: .bottom) {
                    bubbleCluster(size: bubbleSize)
                    Spacer(minLength: 0)
                    bubbleCluster(size: bubbleSize * 0.85)
                        .scaleEffect(x: -1, y: 1)
                        .padding(.bottom, 36)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 28)
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func bubbleCluster(size: CGFloat) -> some View {
        ZStack(alignment: .bottomLeading) {
            pearlBubble(size: size)
            Image(systemName: "fish.fill")
                .font(.system(size: size * 0.3, weight: .light))
                .foregroundStyle(Color(red: 0.57, green: 0.74, blue: 0.88).opacity(0.6))
                .rotationEffect(.degrees(-12))
                .offset(x: size * 0.38, y: -size * 0.3)
            pearlBubble(size: size * 0.38)
                .offset(x: size * 0.7, y: -size * 0.95)
            pearlBubble(size: size * 0.2)
                .offset(x: size * 0.22, y: -size * 1.38)
            pearlBubble(size: size * 0.25)
                .offset(x: size * 0.5, y: -size * 1.8)
            pearlBubble(size: size * 0.13)
                .offset(x: size * 0.12, y: -size * 2.15)
            pearlBubble(size: size * 0.18)
                .offset(x: size * 0.8, y: size * 0.35)
            pearlBubble(size: size * 0.30)
                .offset(x: size * 0.30, y: size * 0.65)
            pearlBubble(size: size * 0.16)
                .offset(x: size * 0.15, y: size * 1.25)
        }
        .frame(width: size * 1.1, height: size * 1.6, alignment: .bottomLeading)
        .padding(.bottom, size * 1.15)
    }

    private func pearlBubble(size: CGFloat) -> some View {
        Circle()
            .fill(RadialGradient(
                colors: [.white.opacity(0.75), Self.bubbleBlue.opacity(0.7), Self.bubbleBlue],
                center: .topLeading, startRadius: 0, endRadius: size
            ))
            .overlay {
                Circle().strokeBorder(
                    LinearGradient(colors: [.white, Self.bubbleBlue, Color(red: 0.68, green: 0.81, blue: 0.94)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: 1.5
                )
            }
            .overlay(alignment: .topLeading) {
                Ellipse()
                    .fill(.white.opacity(0.85))
                    .frame(width: size * 0.32, height: size * 0.13)
                    .rotationEffect(.degrees(-35))
                    .offset(x: size * 0.15, y: size * 0.18)
            }
            .frame(width: size, height: size)
    }

}
