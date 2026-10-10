import SwiftUI
import PhotosUI

/// Manual room measurements (the baseline), optional RoomPlan capture, and inspiration upload.
struct RoomSetupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var room: Room
    @State private var photoItem: PhotosPickerItem?
    @State private var showCapture = false
    @State private var captureNote: String?

    init(room: Room) { _room = State(initialValue: room) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    measurement("Width (along the back wall)", value: $room.widthM, range: 1.5...15)
                    measurement("Depth (back wall to front)", value: $room.depthM, range: 1.5...15)
                    measurement("Ceiling height", value: $room.heightM, range: 2...6)
                    if RoomCaptureSupport.isAvailable {
                        Button { showCapture = true } label: {
                            Label("Measure with RoomPlan (LiDAR)", systemImage: "camera.metering.matrix")
                        }
                    }
                    if let captureNote { Text(captureNote).font(.caption).foregroundStyle(.secondary) }
                } header: {
                    Text("Measurements (meters)")
                } footer: {
                    Text("Measure wall to wall with a tape. Openings and clearance zones are kept as they are: \(room.openings.count) opening(s), \(room.clearances.count) clearance zone(s).")
                }

                Section {
                    let hasInspiration = model.state.room.inspirationImageURL != nil || model.inspirationPreview != nil
                    PhotosPicker(selection: $photoItem, matching: .images) {
                        Label(hasInspiration ? "Replace inspiration photo" : "Choose inspiration photo",
                              systemImage: "photo.on.rectangle.angled")
                    }
                    if model.busy.contains("inspiration") {
                        HStack { ProgressView(); Text("Uploading…") }
                    }
                    inspirationPreview
                } header: {
                    Text("Inspiration")
                } footer: {
                    Text("The agent ranks products by how well their color and style match this photo.")
                }
            }
            .navigationTitle("Room setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        let updated = room
                        Task { await model.saveRoom(updated) }
                        dismiss()
                    }
                    .disabled(model.busy.contains("room"))
                }
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                        await model.uploadInspiration(image)
                    } else {
                        model.errorMessage = "Couldn't read that photo"
                    }
                }
            }
            .fullScreenCover(isPresented: $showCapture) {
                RoomCaptureScreen { result in
                    showCapture = false
                    guard let result else { return }
                    room.widthM = (result.width * 100).rounded() / 100
                    room.depthM = (result.depth * 100).rounded() / 100
                    if let h = result.height { room.heightM = min(max((h * 100).rounded() / 100, 2), 6) }
                    captureNote = String(format: "RoomPlan measured %.2f × %.2f m. Check against a tape measure before saving.",
                                         result.width, result.depth)
                }
            }
        }
    }

    private func measurement(_ title: String, value: Binding<Double>, range: ClosedRange<Double>) -> some View {
        Stepper(value: value, in: range, step: 0.05) {
            HStack {
                Text(title)
                Spacer()
                Text(String(format: "%.2f m", value.wrappedValue)).monospacedDigit().foregroundStyle(Color.aeroInk)
            }
        }
        .accessibilityValue(String(format: "%.2f meters", value.wrappedValue))
    }

    @ViewBuilder private var inspirationPreview: some View {
        if let image = model.inspirationPreview {
            Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 180)
                .clipShape(RoundedRectangle(cornerRadius: 12))
        } else if let url = model.client?.resolve(model.state.room.inspirationImageURL) {
            AsyncImage(url: url) { image in
                image.resizable().scaledToFit()
            } placeholder: { ProgressView() }
                .frame(maxHeight: 180)
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}
