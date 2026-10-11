import SwiftUI

struct SettingsSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(AppNavigation.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @AppStorage(AppModel.baseURLKey) private var baseURL = AppModel.defaultBaseURL
    @AppStorage(AppModel.patchMovesKey) private var patchMoves = false
    @State private var draftURL = ""
    @State private var confirmReset = false
    @State private var healthText: String?
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                if let account = model.account {
                    Section("Account") {
                        Text(account.name)
                        Text("@\(account.username)").foregroundStyle(.secondary)
                        Button("Sign out", role: .destructive) {
                            Task {
                                await model.signOut()
                                nav.replayIntro()
                                dismiss()
                            }
                        }
                    }
                }
                Section {
                    Picker("Acting as", selection: Binding(get: { model.actingMemberID }, set: {
                        model.setActingMember($0)
                        if model.currentGroupID == nil {
                            nav.profileName = model.actingMemberName
                            nav.persistProfile()
                        }
                    })) {
                        ForEach(model.actingCandidates, id: \.id) { candidate in
                            Text(candidate.name).tag(candidate.id)
                        }
                    }
                    Button {
                        dismiss()
                        nav.showShare = true
                    } label: {
                        Label("Share this space", systemImage: "square.and.arrow.up")
                    }
                    HStack(spacing: 8) {
                        ConnectionIndicator(status: model.connection, offlineDemo: model.isOfflineDemo)
                        if case .offline(let reason) = model.connection {
                            Text(reason).font(.subheadline).foregroundStyle(Color.figmaMuted)
                        }
                    }
                } header: {
                    Text("Household")
                }

                Section {
                    HStack {
                        TextField("Mac IP, e.g. 192.168.1.20", text: $draftURL)
                            .keyboardType(.numbersAndPunctuation)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.go)
                            .onSubmit(apply)
                        if !draftURL.isEmpty {
                            Button("Clear", systemImage: "xmark.circle.fill") { draftURL = "" }
                                .labelStyle(.iconOnly).foregroundStyle(.secondary).buttonStyle(.borderless)
                        }
                    }
                    HStack {
                        Button("Connect", systemImage: "bolt.horizontal.circle", action: apply)
                            .buttonStyle(.borderless)
                        Spacer()
                        PasteButton(payloadType: String.self) { strings in
                            guard let text = strings.first else { return }
                            Task { @MainActor in
                                draftURL = text.trimmingCharacters(in: .whitespacesAndNewlines)
                                apply()
                            }
                        }
                        .labelStyle(.titleAndIcon)
                        .buttonBorderShape(.capsule)
                        Button("Use default") { draftURL = AppModel.defaultBaseURL }
                            .buttonStyle(.borderless)
                    }
                    Button {
                        Task { await checkHealth() }
                    } label: {
                        HStack {
                            Label("Check /health", systemImage: "stethoscope")
                            if checking { Spacer(); ProgressView() }
                        }
                    }
                    if let healthText { Text(healthText).font(.caption.monospaced()).foregroundStyle(.secondary) }
                } header: {
                    Text("Backend")
                } footer: {
                    Text("Type just the Mac's IP (System Settings → Wi‑Fi → Details); http:// and :8000 are added for you. Run the backend with scripts/serve.sh. 127.0.0.1 only works in the Simulator.")
                }

                Section {
                    if model.state.designEdits != nil {
                        Label("Furniture edits sync across connected iPads", systemImage: "arrow.triangle.2.circlepath")
                    } else {
                        Toggle("Save moves to the backend", isOn: $patchMoves)
                    }
                } header: {
                    Text("Room editing")
                } footer: {
                    Text(model.state.designEdits != nil
                         ? "Changes to furniture, positions and selections are shared with the other devices using this room."
                         : "Connect to the shared backend to sync room edits. Offline changes stay on this iPad.")
                }

                Section {
                    Button("Reset demo household", systemImage: "arrow.counterclockwise.circle", role: .destructive) {
                        confirmReset = true
                    }
                    .disabled(model.currentGroupID != nil || !model.busy.isEmpty)
                    Button("Clear downloaded 3D assets", systemImage: "trash") {
                        Task { await AssetCache.shared.clear() }
                    }
                    Button("Replay intro", systemImage: "figure.walk.arrival") {
                        dismiss()
                        nav.replayIntro()
                    }
                } header: {
                    Text("Demo")
                } footer: {
                    Text(model.isOfflineDemo
                         ? "Reset clears your changes and restores the neatly furnished demo rooms. Replay intro restarts the walkthrough."
                         : "Reset clears saved edits, photos, searches and queued demo messages, then restores the furnished rooms across connected iPads. Seed contacts reload without sending texts.")
                }

                Section("About") {
                    LabeledContent("Data source", value: model.isOfflineDemo ? "Bundled demo fixtures" : "Live backend")
                    LabeledContent("State version", value: "\(model.state.stateVersion)")
                    if let mode = model.state.catalogMode { LabeledContent("Catalog", value: mode) }
                    if let simulator = model.state.finance.simulator {
                        LabeledContent("Payments", value: simulator == "mock" ? "Simulated (mock)" : "Nessie sandbox (\(simulator))")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .confirmationDialog("Reset the demo household?", isPresented: $confirmReset, titleVisibility: .visible) {
                Button("Reset demo", role: .destructive) { Task { await model.resetDemo() } }
            } message: {
                Text("Clear all demo changes and restore the original furnished rooms, floor plan and budgets across connected iPads? Approvals and simulated payments reset. Seed contacts reload without sending texts.")
            }
        }
        .onAppear { draftURL = baseURL }
    }

    private func apply() {
        let trimmed = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        baseURL = trimmed
        model.reconnect()
    }

    private func checkHealth() async {
        checking = true
        defer { checking = false }
        do {
            let client = try BackendClient(baseURLString: draftURL)
            let health = try await client.health()
            healthText = "OK: status \(health.status ?? "?") at \(client.baseURL.absoluteString)"
        } catch {
            healthText = AppModel.message(error)
        }
    }
}
