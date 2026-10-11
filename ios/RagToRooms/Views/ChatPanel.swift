import SwiftUI

struct ChatPanel: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""

    var body: some View {
        let suggestion = model.chatSuggestion
        let canSend = model.actingMemberInScope
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader(title: "Refine", symbol: "bubble.left.and.text.bubble.right.fill", trailing: model.currentRoomName)
            if model.chat.isEmpty {
                Button { draft = suggestion } label: { Label(suggestion, systemImage: "sparkles").multilineTextAlignment(.leading) }
                    .buttonStyle(GlassChipStyle())
                    .disabled(!canSend)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(model.chat.suffix(12)) { message in bubble(message) }
                }
            }
            HStack(spacing: 8) {
                TextField(model.state.proposal == nil ? "Describe the room…" : "Cheaper sofa, more oak…",
                          text: $draft, axis: .vertical)
                    .lineLimit(1...4)
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 14).fill(.white.opacity(0.75)))
                    .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white, lineWidth: 1))
                    .onSubmit(send)
                Button(action: send) {
                    if model.busy.contains("chat") { ProgressView().tint(.white) } else { Label("Send", systemImage: "paperplane.fill") }
                }
                .buttonStyle(AeroButtonStyle(compact: true))
                .disabled(!canSend || draft.trimmingCharacters(in: .whitespaces).isEmpty || model.busy.contains("chat"))
            }
            if let note = model.notInScopeNote {
                Label(note, systemImage: "eye").font(.caption).foregroundStyle(.secondary)
            }
        }
        .glassPanel()
    }

    private func send() {
        let text = draft
        draft = ""
        Task { await model.sendChat(text) }
    }

    private func bubble(_ message: ChatMessage) -> some View {
        HStack {
            if message.fromMe { Spacer(minLength: 40) }
            VStack(alignment: .leading, spacing: 2) {
                Text(message.author).font(.caption2.weight(.bold)).foregroundStyle(.secondary)
                HStack(alignment: .top, spacing: 6) {
                    if message.isError { Image(systemName: "exclamationmark.triangle").foregroundStyle(Color.aeroRed) }
                    Text(message.text).font(.subheadline).foregroundStyle(Color.aeroInk).textSelection(.enabled)
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 16).fill(message.fromMe ? Color.aeroSky.opacity(0.25) : .white.opacity(0.7)))
            if !message.fromMe { Spacer(minLength: 40) }
        }
    }
}
