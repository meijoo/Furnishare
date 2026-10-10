import Foundation

struct ServerSentEvent: Sendable {
    var event: String
    var data: String
    var id: String?
}

/// Minimal `text/event-stream` reader over `URLSession.bytes`.
/// Parses bytes manually because `AsyncLineSequence` drops the blank lines that delimit events.
enum EventStream {
    /// Synthetic event yielded once the server has accepted the stream (HTTP 2xx).
    static let openEvent = "__open"

    static let session: URLSession = {
        let config = URLSessionConfiguration.default
        // Idle timeout between chunks. Servers that send keep-alive comments stay connected;
        // otherwise the stream ends and the caller falls back to polling, then retries.
        config.timeoutIntervalForRequest = 120
        config.timeoutIntervalForResource = 24 * 60 * 60
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: config)
    }()

    static func events(from url: URL) -> AsyncThrowingStream<ServerSentEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: url)
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
                    let (bytes, response) = try await session.bytes(for: request)
                    if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                        throw BackendError.http(status: http.statusCode, message: "Event stream unavailable")
                    }
                    continuation.yield(ServerSentEvent(event: openEvent, data: ""))
                    var parser = Parser()
                    var line: [UInt8] = []
                    for try await byte in bytes {
                        if byte == UInt8(ascii: "\n") {
                            if let event = parser.consume(line: String(decoding: line, as: UTF8.self)) {
                                continuation.yield(event)
                            }
                            line.removeAll(keepingCapacity: true)
                        } else if byte != UInt8(ascii: "\r") {
                            line.append(byte)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    struct Parser {
        private var eventName = ""
        private var dataLines: [String] = []
        private var lastID: String?

        mutating func consume(line: String) -> ServerSentEvent? {
            if line.isEmpty {
                defer { eventName = ""; dataLines = [] }
                guard !dataLines.isEmpty else { return nil }
                return ServerSentEvent(event: eventName.isEmpty ? "message" : eventName,
                                       data: dataLines.joined(separator: "\n"), id: lastID)
            }
            if line.hasPrefix(":") { return nil }
            let field: Substring
            var value: Substring
            if let colon = line.firstIndex(of: ":") {
                field = line[..<colon]
                value = line[line.index(after: colon)...]
                if value.hasPrefix(" ") { value = value.dropFirst() }
            } else {
                field = Substring(line); value = ""
            }
            switch field {
            case "event": eventName = String(value)
            case "data": dataLines.append(String(value))
            case "id": lastID = String(value)
            default: break
            }
            return nil
        }
    }
}
