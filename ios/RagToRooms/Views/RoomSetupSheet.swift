import SwiftUI

/// Manual room measurements (the baseline) and optional RoomPlan capture.
struct RoomSetupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var room: Room
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
                    Text("Measure wall to wall with a tape. Openings and clearance zones are kept as they are: \(room.openings.count) opening(s), \(room.clearances.count) clearance zone(s). Inspiration photos live on the Inspiration tab.")
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
}
