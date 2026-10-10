import SwiftUI
import PhotosUI
import UIKit

extension TextureStatus {
    var label: String {
        switch self {
        case .building: "Applying texture…"
        case .ready: "Photo applied"
        case .failed: "Texture failed"
        case .unavailable: "Needs Blender on the Mac"
        case .unknown: "Texture status unknown"
        }
    }

    var symbol: String {
        switch self {
        case .building: "paintbrush.pointed.fill"
        case .ready: "checkmark.circle.fill"
        case .failed: "xmark.octagon.fill"
        case .unavailable: "exclamationmark.triangle.fill"
        case .unknown: "questionmark.circle"
        }
    }

    var tint: Color {
        switch self {
        case .building: Color(red: 0.10, green: 0.42, blue: 0.75)
        case .ready: Color(red: 0.13, green: 0.5, blue: 0.2)
        case .failed: .aeroRed
        case .unavailable, .unknown: .aeroAmber
        }
    }
}

/// Under the selection bar: "Put a photo on this sofa…", the texture status chip and "Remove photo".
struct ObjectPhotoRow: View {
    @Environment(AppModel.self) private var model
    let object: SceneObject
    let name: String
    @State private var showSheet = false

    var body: some View {
        let busy = model.busy.contains("texture-\(object.objectID)")
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Button { showSheet = true } label: {
                    Label(object.texture == nil ? "Put a photo on this \(object.category.categoryNoun)…" : "Change photo…",
                          systemImage: "photo.badge.plus")
                }
                .buttonStyle(GlassChipStyle())
                .disabled(!model.backendReachable || busy)
                if let texture = object.texture {
                    StatusBadge(text: texture.status.label, symbol: texture.status.symbol, tint: texture.status.tint)
                    Button { Task { await model.removeTexture(objectID: object.objectID) } } label: {
                        if busy { ProgressView() } else { Label("Remove photo", systemImage: "trash") }
                    }
                    .buttonStyle(GlassChipStyle())
                    .disabled(!model.backendReachable || busy)
                }
                Spacer(minLength: 0)
            }
            .lineLimit(1)
            if model.isOfflineDemo {
                Label("Offline demo: photos on furniture need the backend (and Blender on the Mac).", systemImage: "wifi.slash")
                    .font(.caption).foregroundStyle(.secondary)
            } else if object.texture?.status == .unavailable {
                Label("The photo is saved. It appears on the model once Blender is running on the Mac.", systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $showSheet) { ObjectPhotoSheet(object: object, name: name) }
        .task {
            #if DEBUG
            if UserDefaults.standard.string(forKey: "RTRTextureFile") != nil, !ObjectPhotoSheet.debugShown {
                ObjectPhotoSheet.debugShown = true
                showSheet = true
            }
            #endif
        }
    }
}

private struct ObjectPhotoSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let object: SceneObject
    let name: String

    @State private var photoItem: PhotosPickerItem?
    @State private var image: UIImage?
    @State private var showCamera = false
    /// `print` (whole photo) or `tile` (repeating swatch).
    @State private var mode: String
    @State private var tileM = 0.3
    @State private var applying = false
    @State private var failure: String?

    init(object: SceneObject, name: String) {
        self.object = object
        self.name = name
        _mode = State(initialValue: object.texture?.mode ?? (object.category == "rug" ? "print" : "tile"))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if let image {
                        Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 220)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                            .frame(maxWidth: .infinity)
                            .accessibilityLabel("Chosen photo")
                    }
                    PhotosPicker(selection: $photoItem, matching: .images) {
                        Label(image == nil ? "Choose a photo" : "Choose another photo", systemImage: "photo.on.rectangle")
                    }
                    if UIImagePickerController.isSourceTypeAvailable(.camera) {
                        Button { showCamera = true } label: { Label("Take a photo", systemImage: "camera") }
                    }
                } header: {
                    Text("Photo")
                } footer: {
                    Text("A fabric, a rug you like, a wood grain… It's sent to the backend, which builds a textured 3D model of \(name).")
                }

                Section {
                    Picker("Apply as", selection: $mode) {
                        Text("Print").tag("print")
                        Text("Pattern").tag("tile")
                    }
                    .pickerStyle(.segmented)
                    if mode == "tile" {
                        VStack(alignment: .leading) {
                            LabeledContent("Tile size", value: String(format: "%.2f m", tileM))
                            Slider(value: $tileM, in: 0.1...1.0, step: 0.05) {
                                Text("Tile size")
                            } minimumValueLabel: { Text("0.1") } maximumValueLabel: { Text("1.0") }
                        }
                    }
                } header: {
                    Text("How to apply it")
                } footer: {
                    Text(mode == "print"
                         ? "Print: the whole photo once across the top, like a printed rug."
                         : "Pattern: the photo repeats as a swatch over the main surfaces, one tile every \(String(format: "%.2f", tileM)) m.")
                }

                if let failure {
                    Section { Label(failure, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Color.aeroRed) }
                }
            }
            .navigationTitle("Photo on \(name)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if applying { ProgressView() } else { Button("Apply") { Task { await apply() } }.disabled(image == nil) }
                }
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self), let picked = UIImage(data: data) {
                        image = picked; failure = nil
                    } else {
                        failure = "Couldn't read that photo"
                    }
                }
            }
            .task { await debugPrefill() }
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { captured in image = captured; failure = nil }.ignoresSafeArea()
            }
        }
    }

    #if DEBUG
    @MainActor static var debugShown = false
    #endif

    /// Screenshot automation: `-RTRTextureFile /path/photo.jpg` (with `-RTRSelect`) opens this sheet with that photo;
    /// `-RTRTextureApply YES` also applies it after a moment.
    private func debugPrefill() async {
        #if DEBUG
        let defaults = UserDefaults.standard
        guard image == nil, let path = defaults.string(forKey: "RTRTextureFile") else { return }
        image = UIImage(contentsOfFile: path)
        if defaults.bool(forKey: "RTRTextureApply") {
            try? await Task.sleep(for: .seconds(3))
            await apply()
        }
        #endif
    }

    private func apply() async {
        guard let image else { return }
        applying = true
        defer { applying = false }
        guard let upload = await UploadImage.prepare(image, maxLongSide: 2048, name: "texture") else {
            failure = "Couldn't prepare that photo"
            return
        }
        if await model.putTexture(objectID: object.objectID, image: upload, mode: mode, tileM: mode == "tile" ? tileM : nil) {
            dismiss()
        } else {
            failure = model.errorMessage ?? "The backend didn't accept the photo"
            model.errorMessage = nil
        }
    }
}

/// Minimal camera capture via `UIImagePickerController`.
private struct CameraPicker: UIViewControllerRepresentable {
    let onCapture: (UIImage) -> Void
    @Environment(\.dismiss) private var dismiss

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage { parent.onCapture(image) }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
    }
}

extension String {
    /// "sofa", "coffee table", "TV" for sentences like "Put a photo on this sofa…".
    var categoryNoun: String {
        self == "tv" ? "TV" : categoryLabel.lowercased()
    }
}
