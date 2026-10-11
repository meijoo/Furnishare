import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// "Import floor plan" (Photos or a PNG/JPEG file), the width prompt when no sizes are printed,
/// warnings, the plan-image toggle and "Restore built-in plan".
struct FloorPlanImportControls: View {
    @Environment(AppModel.self) private var model
    let apartment: Apartment
    @Binding var showImage: Bool
    var prominent = false

    @State private var showPhotos = false
    @State private var photoItem: PhotosPickerItem?
    @State private var showFiles = false
    @State private var confirmRestore = false
    @State private var preparing = false
    @State private var startedAt: Date?
    /// Kept so the user can retry with an overall width after a 422.
    @State private var pending: UploadImage?
    @State private var widthPrompt: String?
    @State private var widthText = ""
    @State private var widthInFeet = false
    @State private var warnings: [String] = []
    @State private var failure: String?

    private var working: Bool { preparing || model.busy.contains("floorplan") }
    private var uploadTitle: String { apartment.isImported ? "Reupload floor plan" : "Import floor plan" }
    private let uploadError = "Couldn't upload your floor plan. Please try again with a clear PNG or JPEG image."

    var body: some View {
        VStack(alignment: prominent ? .center : .leading, spacing: 10) {
            if apartment.isImported && !working {
                Label("Floor plan uploaded", systemImage: "checkmark.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.aeroGrass)
            }
            if prominent {
                importHero
            } else {
                compactControls
            }
            if !model.backendReachable {
                Label(model.isOfflineDemo
                      ? "Connect to the backend to analyze your floor plan."
                      : "Connect to the backend to import a floor plan.",
                      systemImage: "wifi.slash")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if working { progress }
            if widthPrompt != nil && !working { widthCard }
            if let failure {
                note(failure, symbol: "exclamationmark.triangle.fill", tint: .aeroRed) { self.failure = nil }
            }
            if !warnings.isEmpty {
                note(warnings.joined(separator: "\n"), symbol: "exclamationmark.bubble", tint: .aeroAmber,
                     title: warnings.count == 1 ? "1 note from the import" : "\(warnings.count) notes from the import") { warnings = [] }
            }
        }
        .photosPicker(isPresented: $showPhotos, selection: $photoItem, matching: .images)
        .fileImporter(isPresented: $showFiles, allowedContentTypes: [.png, .jpeg]) { result in
            switch result {
            case .success(let url):
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                if let data = try? Data(contentsOf: url) { Task { await begin(data) } } else { failure = uploadError }
            case .failure:
                failure = uploadError
            }
        }
        .onChange(of: photoItem) { _, item in
            guard let item else { return }
            photoItem = nil
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) { await begin(data) }
                else { failure = uploadError }
            }
        }
        .task { await debugImport() }
        .confirmationDialog("Restore the built-in plan?", isPresented: $confirmRestore, titleVisibility: .visible) {
            Button("Restore built-in plan", role: .destructive) { Task { await restore() } }
        } message: {
            Text("The imported plan is removed and the bedrooms are re-seeded at their built-in sizes, which replaces their current proposals. The living room is not changed.")
        }
    }

    private var importHero: some View {
        VStack(spacing: 18) {
            Image(systemName: "photo.on.rectangle")
                .font(.system(size: 44, weight: .medium))
                .foregroundStyle(Color.aeroSky)
            Menu {
                Button("Choose from Photos", systemImage: "photo.on.rectangle") { showPhotos = true }
                Button("Choose a PNG or JPEG file", systemImage: "folder") { showFiles = true }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "square.and.arrow.down.on.square")
                    Text(uploadTitle)
                }
            }
            .buttonStyle(AeroWideButtonStyle())
            .disabled(!model.backendReachable || working)
            .frame(maxWidth: 420)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 44)
        .padding(.horizontal, 28)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.figmaWash.opacity(0.65)))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.aeroSky.opacity(0.18), lineWidth: 1.5))
    }

    private var compactControls: some View {
        FlowButtons {
            Menu {
                Button("Choose from Photos", systemImage: "photo.on.rectangle") { showPhotos = true }
                Button("Choose a PNG or JPEG file", systemImage: "folder") { showFiles = true }
            } label: {
                Label(uploadTitle, systemImage: "square.and.arrow.down.on.square")
            }
            .buttonStyle(AeroButtonStyle(compact: true))
            .disabled(!model.backendReachable || working)
            if apartment.isImported {
                Button { showImage.toggle() } label: {
                    Label(showImage ? "Hide plan image" : "Show plan image", systemImage: showImage ? "eye.slash" : "eye")
                }
                .buttonStyle(GlassChipStyle(selected: showImage))
                Button { confirmRestore = true } label: {
                    Label("Restore built-in plan", systemImage: "arrow.uturn.backward")
                }
                .buttonStyle(GlassChipStyle())
                .disabled(!model.backendReachable || working)
            }
        }
    }

    private var progress: some View {
        HStack(spacing: 10) {
            ProgressView()
            VStack(alignment: .leading, spacing: 2) {
                Text(preparing ? "Preparing the image…" : startedAt != nil ? "Analyzing floor plan…" : "Restoring the built-in plan…")
                    .font(.subheadline.weight(.semibold))
                if let startedAt {
                    TimelineView(.periodic(from: startedAt, by: 1)) { context in
                        Text("\(Int(context.date.timeIntervalSince(startedAt))) s · usually 5–15 s")
                            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.5)))
        .accessibilityElement(children: .combine)
    }

    private var widthCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("No room sizes are printed on this plan", systemImage: "ruler").font(.subheadline.weight(.semibold))
            Text("Enter the overall width of the plan (left to right) and import again.").font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                TextField(widthInFeet ? "Width in feet, e.g. 34" : "Width in metres, e.g. 10.5", text: $widthText)
                    .keyboardType(.decimalPad)
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 10).fill(.white.opacity(0.8)))
                    .frame(maxWidth: 220)
                Picker("Unit", selection: $widthInFeet) {
                    Text("m").tag(false)
                    Text("ft").tag(true)
                }
                .pickerStyle(.segmented)
                .frame(width: 100)
                Button { Task { await retryWithWidth() } } label: { Label("Import", systemImage: "arrow.clockwise") }
                    .buttonStyle(AeroButtonStyle(compact: true))
                    .disabled(widthMeters == nil)
                Button("Cancel") { widthPrompt = nil; pending = nil }
                    .buttonStyle(GlassChipStyle())
            }
            if !widthText.isEmpty, widthMeters == nil {
                Label("Use a width between 2 and 60 m (7 and 196 ft)", systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.55)))
    }

    private func note(_ text: String, symbol: String, tint: Color, title: String? = nil, dismiss: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol).foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 2) {
                if let title { Text(title).font(.caption.weight(.bold)) }
                Text(text).font(.caption).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Button("Dismiss", systemImage: "xmark", action: dismiss).labelStyle(.iconOnly).buttonStyle(GlassChipStyle())
        }
        .foregroundStyle(Color.aeroInk)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.55)))
        .accessibilityElement(children: .contain)
    }

    private var widthMeters: Double? {
        let cleaned = widthText.replacingOccurrences(of: ",", with: ".").trimmingCharacters(in: .whitespaces)
        guard let value = Double(cleaned) else { return nil }
        let meters = widthInFeet ? value * 0.3048 : value
        return (2...60).contains(meters) ? meters : nil
    }

    private func begin(_ data: Data) async {
        failure = nil
        warnings = []
        widthPrompt = nil
        preparing = true
        let image = await UploadImage.prepare(data, maxLongSide: 1600, keepPNG: true, name: "floorplan")
        preparing = false
        guard let image else { failure = uploadError; return }
        pending = image
        await send(widthM: nil)
    }

    private func retryWithWidth() async {
        guard let width = widthMeters else { return }
        widthPrompt = nil
        await send(widthM: width)
    }

    private func send(widthM: Double?) async {
        guard let image = pending else { return }
        startedAt = Date()
        let outcome = await model.importFloorplan(image, widthM: widthM)
        startedAt = nil
        switch outcome {
        case .imported(let notes):
            warnings = notes
            pending = nil
            showImage = true
        case .needsWidth(let message):
            widthPrompt = message
        case .failed:
            failure = uploadError
            pending = nil
        }
    }

    /// Screenshot automation: `-RTRImportPlanFile /path/plan.png` imports that file once, as if picked.
    private func debugImport() async {
        #if DEBUG
        guard !Self.debugImportDone, let path = UserDefaults.standard.string(forKey: "RTRImportPlanFile") else { return }
        Self.debugImportDone = true
        try? await Task.sleep(for: .seconds(4))
        if let data = FileManager.default.contents(atPath: path) { await begin(data) } else { failure = uploadError }
        #endif
    }

    #if DEBUG
    @MainActor private static var debugImportDone = false
    #endif

    private func restore() async {
        failure = nil
        if await model.restoreBuiltInPlan() != nil {
            failure = "Couldn't restore the floor plan. Please try again."
        } else {
            warnings = []
        }
    }
}
