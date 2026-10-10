import SwiftUI

struct ActivityPanel: View {
    @Environment(AppModel.self) private var model
    private static let parser = ISO8601DateFormatter()
    private static let fractionalParser: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    var body: some View {
        // The backend lists activity newest first; keep its order for entries with the same timestamp.
        let entries = model.state.activity.enumerated().sorted { $0.element.at == $1.element.at ? $0.offset < $1.offset : $0.element.at > $1.element.at }
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader(title: "Activity", symbol: "clock.arrow.circlepath",
                        trailing: model.lastUpdated.map { "Updated \($0.formatted(date: .omitted, time: .standard))" })
            if entries.isEmpty {
                Text("Nothing yet.").foregroundStyle(.secondary)
            }
            ForEach(Array(entries.prefix(25)), id: \.offset) { item in
                let entry = item.element
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(time(entry.at)).font(.caption.monospacedDigit()).foregroundStyle(.secondary).frame(width: 64, alignment: .leading)
                    Text(entry.text).font(.subheadline).foregroundStyle(Color.aeroInk)
                    Spacer(minLength: 0)
                }
            }
        }
        .glassPanel()
    }

    private func time(_ iso: String) -> String {
        guard let date = Self.parser.date(from: iso) ?? Self.fractionalParser.date(from: iso) else { return "" }
        return date.formatted(date: .omitted, time: .shortened)
    }
}
