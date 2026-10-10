import SwiftUI
import simd
#if canImport(RoomPlan) && !targetEnvironment(simulator)
import RoomPlan
#endif

struct RoomCaptureResult {
    var width: Double
    var depth: Double
    var height: Double?
}

enum RoomCaptureSupport {
    /// RoomPlan needs a LiDAR device; manual measurements remain the baseline.
    static var isAvailable: Bool {
        #if canImport(RoomPlan) && !targetEnvironment(simulator)
        RoomCaptureSession.isSupported
        #else
        false
        #endif
    }
}

/// Full-screen RoomPlan scan. Calls `onFinish(nil)` on cancel or failure.
struct RoomCaptureScreen: View {
    var onFinish: (RoomCaptureResult?) -> Void

    var body: some View {
        #if canImport(RoomPlan) && !targetEnvironment(simulator)
        RoomCaptureContainer(onFinish: onFinish).ignoresSafeArea()
        #else
        VStack(spacing: 16) {
            Text("RoomPlan is not available on this device.")
            Button("Close") { onFinish(nil) }.buttonStyle(AeroButtonStyle())
        }
        #endif
    }
}

#if canImport(RoomPlan) && !targetEnvironment(simulator)
private struct RoomCaptureContainer: View {
    var onFinish: (RoomCaptureResult?) -> Void
    @State private var controller = RoomCaptureController()

    var body: some View {
        ZStack(alignment: .top) {
            RoomCaptureViewRepresentable(controller: controller)
            HStack {
                Button("Cancel") { controller.stop(); onFinish(nil) }
                    .buttonStyle(GlassChipStyle())
                Spacer()
                Text(controller.status).font(.subheadline.weight(.semibold)).foregroundStyle(.white)
                    .padding(8).background(Capsule().fill(.black.opacity(0.4)))
                Spacer()
                Button("Done") { controller.stop() }
                    .buttonStyle(AeroButtonStyle(tint: .aeroGrass, compact: true))
                    .disabled(controller.isFinishing)
            }
            .padding()
        }
        .onAppear { controller.onResult = onFinish; controller.start() }
    }
}

@Observable
@MainActor
final class RoomCaptureController {
    let view = RoomCaptureView(frame: .zero)
    var status = "Slowly scan every wall"
    var isFinishing = false
    var onResult: ((RoomCaptureResult?) -> Void)?
    private let delegate = RoomCaptureDelegate()

    init() {
        delegate.owner = self
        view.delegate = delegate
    }

    func start() { view.captureSession.run(configuration: RoomCaptureSession.Configuration()) }

    func stop() {
        isFinishing = true
        status = "Processing…"
        view.captureSession.stop()
    }

    func finished(_ room: CapturedRoom?) {
        guard let room, let result = Self.measure(room) else {
            status = "Couldn't measure the room; enter it manually"
            onResult?(nil)
            return
        }
        onResult?(result)
    }

    /// Width/depth from wall endpoints in a frame aligned with the longest wall.
    static func measure(_ room: CapturedRoom) -> RoomCaptureResult? {
        guard let longest = room.walls.max(by: { $0.dimensions.x < $1.dimensions.x }) else { return nil }
        let axis = simd_normalize(SIMD2<Float>(longest.transform.columns.0.x, longest.transform.columns.0.z))
        let normal = SIMD2<Float>(-axis.y, axis.x)
        var along: [Float] = [], across: [Float] = []
        for wall in room.walls {
            let center = SIMD2<Float>(wall.transform.columns.3.x, wall.transform.columns.3.z)
            let direction = simd_normalize(SIMD2<Float>(wall.transform.columns.0.x, wall.transform.columns.0.z))
            for end in [center + direction * wall.dimensions.x / 2, center - direction * wall.dimensions.x / 2] {
                along.append(simd_dot(end, axis)); across.append(simd_dot(end, normal))
            }
        }
        guard let a0 = along.min(), let a1 = along.max(), let c0 = across.min(), let c1 = across.max() else { return nil }
        let height = room.walls.map(\.dimensions.y).max()
        return RoomCaptureResult(width: Double(a1 - a0), depth: Double(c1 - c0), height: height.map(Double.init))
    }
}

@objc(RTRRoomCaptureDelegate)
final class RoomCaptureDelegate: NSObject, RoomCaptureViewDelegate {
    weak var owner: RoomCaptureController?

    override init() { super.init() }
    required init?(coder: NSCoder) { super.init() }
    func encode(with coder: NSCoder) {}

    func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool { true }

    func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
        Task { @MainActor in owner?.finished(error == nil ? processedResult : nil) }
    }
}

private struct RoomCaptureViewRepresentable: UIViewRepresentable {
    let controller: RoomCaptureController
    func makeUIView(context: Context) -> RoomCaptureView { controller.view }
    func updateUIView(_ uiView: RoomCaptureView, context: Context) {}
}
#endif
