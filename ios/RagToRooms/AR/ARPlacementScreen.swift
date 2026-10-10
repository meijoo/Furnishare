import SwiftUI
import RealityKit
import ARKit
import AVFoundation

/// True-scale AR: either the whole layout aligned to the real room with two floor taps,
/// or a single item dropped wherever the user taps.
struct ARPlacementScreen: View {
    let room: Room
    let objects: [SceneObject]
    let names: [String: String]
    let baseURL: URL?
    let initialObjectID: String?

    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var controller = ARPlacementController()
    @State private var cameraStatus = AVCaptureDevice.authorizationStatus(for: .video)

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if !ARWorldTrackingConfiguration.isSupported {
                unavailable(title: "AR needs a physical iPad",
                            detail: "World tracking isn't available here (for example in the Simulator). The 3D room view shows the same layout at true scale.")
            } else {
                switch cameraStatus {
                case .authorized:
                    ARViewContainer(controller: controller).ignoresSafeArea()
                    overlay
                case .notDetermined:
                    ProgressView("Requesting camera access…").tint(.white).foregroundStyle(.white)
                        .task {
                            _ = await AVCaptureDevice.requestAccess(for: .video)
                            cameraStatus = AVCaptureDevice.authorizationStatus(for: .video)
                        }
                default:
                    unavailable(title: "Camera access is off",
                                detail: "Allow camera access for RAG to Rooms in Settings to place furniture in your room.",
                                showSettings: true)
                }
            }
        }
        .onAppear {
            controller.configure(room: room, objects: objects, baseURL: baseURL)
            if let initialObjectID, objects.contains(where: { $0.objectID == initialObjectID }) {
                controller.singleItemID = initialObjectID
            } else {
                controller.singleItemID = objects.first(where: { $0.category != "rug" })?.objectID ?? objects.first?.objectID
            }
        }
        .onDisappear { controller.pause() }
        .statusBarHidden()
    }

    // MARK: Overlay

    private var overlay: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                Button { dismiss() } label: { Label("Close", systemImage: "xmark") }
                    .buttonStyle(GlassChipStyle())
                Picker("Mode", selection: Binding(get: { controller.mode }, set: { controller.setMode($0) })) {
                    Text("Whole room").tag(ARPlacementController.Mode.wholeRoom)
                    Text("Single item").tag(ARPlacementController.Mode.singleItem)
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 320)
                Spacer()
                Button { controller.reset() } label: { Label("Reset", systemImage: "arrow.counterclockwise") }
                    .buttonStyle(GlassChipStyle())
            }
            if controller.mode == .singleItem { itemPicker }
            Spacer()
            instruction
        }
        .padding(16)
    }

    private var itemPicker: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(objects) { object in
                    Button {
                        controller.singleItemID = object.objectID
                    } label: {
                        Label(names[object.objectID] ?? object.category.categoryLabel, systemImage: object.category.categorySymbol)
                    }
                    .buttonStyle(GlassChipStyle(selected: controller.singleItemID == object.objectID))
                }
            }
        }
        .scrollIndicators(.hidden)
    }

    private var instruction: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: controller.step.symbol).font(.title2).foregroundStyle(Color.aeroSky)
            VStack(alignment: .leading, spacing: 2) {
                Text(controller.step.title(mode: controller.mode)).font(.headline)
                Text(controller.step.detail(mode: controller.mode, room: room)).font(.subheadline).foregroundStyle(.secondary)
                if let note = controller.note {
                    Label(note, systemImage: "info.circle").font(.caption).foregroundStyle(Color.aeroInk)
                }
            }
            .foregroundStyle(Color.aeroInk)
            Spacer()
            if controller.step == .direction {
                Button("Redo corner") { controller.redoCorner() }.buttonStyle(GlassChipStyle())
            }
        }
        .glassPanel(cornerRadius: 20, padding: 14)
        .frame(maxWidth: 640)
    }

    private func unavailable(title: String, detail: String, showSettings: Bool = false) -> some View {
        VStack(spacing: 14) {
            Image(systemName: "arkit").font(.system(size: 44)).foregroundStyle(Color.aeroSky)
            Text(title).font(.title2.bold())
            Text(detail).multilineTextAlignment(.center).foregroundStyle(.secondary)
            HStack {
                if showSettings, let url = URL(string: UIApplication.openSettingsURLString) {
                    Button("Open Settings") { openURL(url) }.buttonStyle(AeroButtonStyle())
                }
                Button("Close") { dismiss() }.buttonStyle(GlassChipStyle())
            }
        }
        .foregroundStyle(Color.aeroInk)
        .glassPanel()
        .frame(maxWidth: 520)
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AeroBackground())
    }
}

// MARK: - Controller

@Observable
@MainActor
final class ARPlacementController {
    enum Mode: Hashable { case wholeRoom, singleItem }

    enum Step: Equatable {
        case findFloor, corner, direction, placed

        var symbol: String {
            switch self {
            case .findFloor: "viewfinder"
            case .corner: "1.circle.fill"
            case .direction: "2.circle.fill"
            case .placed: "checkmark.circle.fill"
            }
        }

        func title(mode: Mode) -> String {
            switch (self, mode) {
            case (.findFloor, _): "Find the floor"
            case (.corner, .wholeRoom): "Step 1: tap the back-left corner"
            case (.direction, .wholeRoom): "Step 2: tap along the back wall"
            case (.placed, .wholeRoom): "Layout placed at true scale"
            case (.placed, .singleItem): "Item placed at true scale"
            case (_, .singleItem): "Tap the floor to place"
            }
        }

        func detail(mode: Mode, room: Room) -> String {
            switch (self, mode) {
            case (.findFloor, _): "Move the iPad slowly so it can see the floor."
            case (.corner, .wholeRoom): "Stand facing the back wall and tap the floor where it meets the left wall."
            case (.direction, .wholeRoom): String(format: "Tap a floor point further right along the back wall (the room is %.2f m wide).", room.widthM)
            case (.placed, .wholeRoom): "Drag furniture to move it, twist with two fingers to rotate. Changes stay on this iPad."
            case (.placed, .singleItem): "Drag to move, twist to rotate. Tap the floor elsewhere to move it there."
            case (_, .singleItem): "The item faces you when placed."
            }
        }
    }

    private(set) var mode: Mode = .wholeRoom
    private(set) var step: Step = .findFloor
    var singleItemID: String? {
        didSet { if mode == .singleItem, oldValue != singleItemID, step == .placed { clearContent(); step = .corner } }
    }
    var note: String?
    private(set) var cameraLive = false

    private(set) var view: ARView?
    private var room = Room(widthM: 4, depthM: 4, heightM: 2.5)
    private var objects: [SceneObject] = []
    private var baseURL: URL?
    private var floorFound = false
    private var cornerPoint: SIMD3<Float>?
    private var cornerMarker: AnchorEntity?
    private var contentAnchor: AnchorEntity?
    private var nodes: [FurnitureNode] = []
    private var gestureRecognizers: [UIGestureRecognizer] = []
    private let sessionDelegate = SessionDelegate()

    func configure(room: Room, objects: [SceneObject], baseURL: URL?) {
        self.room = room; self.objects = objects; self.baseURL = baseURL
    }

    func makeView() -> ARView {
        if let view { return view }
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.environment.sceneUnderstanding.options.insert(.receivesLighting)
        sessionDelegate.onPlane = { [weak self] in self?.planeDetected() }
        sessionDelegate.onProblem = { [weak self] message in self?.note = message }
        sessionDelegate.onFirstFrame = { [weak self] in self?.cameraLive = true }
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(4))
            guard let self, !self.cameraLive, self.note == nil else { return }
            self.note = "No camera image after 4 s. Make sure the app is full screen, then tap Reset."
        }
        view.session.delegate = sessionDelegate

        let coaching = ARCoachingOverlayView()
        coaching.session = view.session
        coaching.goal = .horizontalPlane
        coaching.activatesAutomatically = true
        coaching.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(coaching)
        NSLayoutConstraint.activate([
            coaching.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            coaching.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            coaching.topAnchor.constraint(equalTo: view.topAnchor),
            coaching.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        let tap = UITapGestureRecognizer(target: TapTarget.shared, action: #selector(TapTarget.handle(_:)))
        TapTarget.shared.onTap = { [weak self] point in self?.handleTap(at: point) }
        view.addGestureRecognizer(tap)
        self.view = view
        runSession(reset: true)
        return view
    }

    func pause() { view?.session.pause() }

    func setMode(_ newMode: Mode) {
        guard newMode != mode else { return }
        mode = newMode
        clearContent()
        step = floorFound ? .corner : .findFloor
    }

    func reset() {
        clearContent()
        floorFound = false
        step = .findFloor
        runSession(reset: true)
    }

    func redoCorner() {
        cornerPoint = nil
        cornerMarker?.removeFromParent(); cornerMarker = nil
        step = .corner
    }

    // MARK: Internals

    private func runSession(reset: Bool) {
        guard let view else { return }
        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        config.environmentTexturing = .automatic
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) { config.sceneReconstruction = .mesh }
        view.session.run(config, options: reset ? [.resetTracking, .removeExistingAnchors] : [])
    }

    private func planeDetected() {
        floorFound = true
        if step == .findFloor { step = .corner }
    }

    private func floorHit(at point: CGPoint) -> SIMD3<Float>? {
        guard let view else { return nil }
        let result = view.raycast(from: point, allowing: .existingPlaneGeometry, alignment: .horizontal).first
            ?? view.raycast(from: point, allowing: .estimatedPlane, alignment: .horizontal).first
        guard let result else { return nil }
        let c = result.worldTransform.columns.3
        return SIMD3(c.x, c.y, c.z)
    }

    private func handleTap(at point: CGPoint) {
        guard let view else { return }
        // Taps on furniture are for the entity gestures, not for placement.
        if step == .placed, mode == .wholeRoom { return }
        if step == .placed, mode == .singleItem, view.entity(at: point) != nil { return }
        guard let hit = floorHit(at: point) else {
            note = "No floor found there yet. Aim at the floor and try again."
            return
        }
        note = nil
        if step == .findFloor { planeDetected() }
        switch mode {
        case .wholeRoom:
            if step == .corner {
                cornerPoint = hit
                let marker = AnchorEntity(world: hit)
                let sphere = ModelEntity(mesh: .generateSphere(radius: 0.03),
                                         materials: [SimpleMaterial(color: UIColor(red: 0.36, green: 0.80, blue: 0.36, alpha: 1), isMetallic: false)])
                sphere.position.y = 0.03
                marker.addChild(sphere)
                view.scene.addAnchor(marker)
                cornerMarker = marker
                step = .direction
            } else if step == .direction, let corner = cornerPoint {
                let level = SIMD3(hit.x, corner.y, hit.z)
                guard let transform = RoomAlignment.transform(corner: corner, alongBackWall: level, room: room) else {
                    note = "Tap at least \(Int(RoomAlignment.minimumBaseline * 100)) cm away from the corner."
                    return
                }
                placeWholeRoom(transform)
            }
        case .singleItem:
            placeSingle(at: hit)
        }
    }

    private func placeWholeRoom(_ transform: simd_float4x4) {
        guard let view else { return }
        clearContent(keepCorner: false)
        let anchor = AnchorEntity(world: transform)
        anchor.addChild(EntityFactory.floorOutline(room))
        for object in objects {
            let node = FurnitureNode(object: object, assetURL: BackendClient.resolve(object.assetURL, base: baseURL))
            anchor.addChild(node.root)
            nodes.append(node)
        }
        view.scene.addAnchor(anchor)
        contentAnchor = anchor
        nodes.forEach { $0.appear() }
        installGestures()
        step = .placed
    }

    private func placeSingle(at hit: SIMD3<Float>) {
        guard let view, let id = singleItemID, var object = objects.first(where: { $0.objectID == id }) else {
            note = "Choose an item first."
            return
        }
        let camera = view.cameraTransform.translation
        object.positionM = [0, 0, 0]
        object.rotationYRad = Double(RoomAlignment.yawFacing(camera, from: hit))
        if let node = nodes.first, node.objectID == id, let anchor = contentAnchor {
            anchor.move(to: Transform(translation: hit), relativeTo: nil, duration: 0.25, timingFunction: .easeInOut)
            node.setPose(x: 0, z: 0, angle: object.rotationYRad, animated: true)
            return
        }
        clearContent()
        let anchor = AnchorEntity(world: hit)
        let node = FurnitureNode(object: object, assetURL: BackendClient.resolve(object.assetURL, base: baseURL))
        anchor.addChild(node.root)
        view.scene.addAnchor(anchor)
        contentAnchor = anchor
        nodes = [node]
        node.appear()
        installGestures()
        step = .placed
    }

    private func installGestures() {
        guard let view else { return }
        removeGestures()
        for node in nodes {
            gestureRecognizers += view.installGestures([.translation, .rotation], for: node.root)
        }
    }

    private func removeGestures() {
        for recognizer in gestureRecognizers { recognizer.view?.removeGestureRecognizer(recognizer) }
        gestureRecognizers = []
    }

    private func clearContent(keepCorner: Bool = false) {
        removeGestures()
        contentAnchor?.removeFromParent(); contentAnchor = nil
        nodes = []
        if !keepCorner {
            cornerMarker?.removeFromParent(); cornerMarker = nil
            cornerPoint = nil
        }
    }

    // MARK: Bridges

    private final class SessionDelegate: NSObject, ARSessionDelegate {
        var onPlane: (@MainActor () -> Void)?
        var onProblem: (@MainActor (String?) -> Void)?
        var onFirstFrame: (@MainActor () -> Void)?
        private var sawFrame = false

        func session(_ session: ARSession, didUpdate frame: ARFrame) {
            guard !sawFrame else { return }
            sawFrame = true
            let callback = onFirstFrame
            Task { @MainActor in callback?() }
        }

        func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
            guard anchors.contains(where: { ($0 as? ARPlaneAnchor)?.alignment == .horizontal }) else { return }
            let callback = onPlane
            Task { @MainActor in callback?() }
        }

        func session(_ session: ARSession, didFailWithError error: Error) {
            report("AR stopped: \(error.localizedDescription). Tap Reset to try again.")
        }

        func sessionWasInterrupted(_ session: ARSession) {
            report("The camera was interrupted. iPadOS only gives AR apps the camera in full screen, so make RAG to Rooms full screen (not a window or split view).")
        }

        func sessionInterruptionEnded(_ session: ARSession) {
            report(nil)
        }

        func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
            if case .notAvailable = camera.trackingState {
                report("Tracking isn't available. Make the app full screen and point the iPad at a well-lit floor.")
            }
        }

        private func report(_ message: String?) {
            let callback = onProblem
            Task { @MainActor in callback?(message) }
        }
    }

    @MainActor
    private final class TapTarget: NSObject {
        static let shared = TapTarget()
        var onTap: ((CGPoint) -> Void)?
        @objc func handle(_ gesture: UITapGestureRecognizer) {
            guard let view = gesture.view else { return }
            onTap?(gesture.location(in: view))
        }
    }
}

private struct ARViewContainer: UIViewRepresentable {
    let controller: ARPlacementController
    func makeUIView(context: Context) -> ARView { controller.makeView() }
    func updateUIView(_ uiView: ARView, context: Context) {}
}