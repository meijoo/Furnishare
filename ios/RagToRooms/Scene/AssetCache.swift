import Foundation
import CryptoKit

/// Downloads USDZ assets once and keeps them on disk, keyed by the SHA-256 of the full URL.
actor AssetCache {
    static let shared = AssetCache()

    private let directory: URL
    private var inFlight: [URL: Task<URL, Error>] = [:]

    init() {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        directory = caches.appendingPathComponent("USDZ", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    func localFile(for remote: URL) async throws -> URL {
        let destination = cachedPath(for: remote)
        if FileManager.default.fileExists(atPath: destination.path) { return destination }
        if let task = inFlight[remote] { return try await task.value }
        let task = Task<URL, Error> {
            let (temp, response) = try await URLSession.shared.download(from: remote)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                try? FileManager.default.removeItem(at: temp)
                throw BackendError.http(status: http.statusCode, message: "Asset download failed")
            }
            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.moveItem(at: temp, to: destination)
            return destination
        }
        inFlight[remote] = task
        defer { inFlight[remote] = nil }
        return try await task.value
    }

    func clear() {
        try? FileManager.default.removeItem(at: directory)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    nonisolated private func cachedPath(for remote: URL) -> URL {
        let digest = SHA256.hash(data: Data(remote.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
        // RealityKit picks the loader from the extension, so always keep `.usdz`.
        return directory.appendingPathComponent(digest).appendingPathExtension("usdz")
    }
}
