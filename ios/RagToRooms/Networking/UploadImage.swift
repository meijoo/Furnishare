import UIKit

/// An image ready for a multipart upload. The backend accepts PNG and JPEG only.
struct UploadImage: Sendable {
    var data: Data
    var mimeType: String
    var filename: String

    /// HEIC, large PNGs and anything else become a JPEG whose long side is at most `maxLongSide` pixels,
    /// with the EXIF orientation applied. A PNG that is already small enough is kept as is when `keepPNG`
    /// (sharp lines matter for floor plans). Runs off the main actor; decoding a 48 MP photo is slow.
    static func prepare(_ data: Data, maxLongSide: CGFloat, keepPNG: Bool, name: String) async -> UploadImage? {
        await Task.detached(priority: .userInitiated) {
            guard let image = UIImage(data: data) else { return nil }
            let isPNG = data.starts(with: [0x89, 0x50, 0x4E, 0x47])
            if keepPNG, isPNG, max(image.size.width, image.size.height) * image.scale <= maxLongSide {
                return UploadImage(data: data, mimeType: "image/png", filename: "\(name).png")
            }
            return jpeg(from: image, maxLongSide: maxLongSide, name: name)
        }.value
    }

    static func prepare(_ image: UIImage, maxLongSide: CGFloat, name: String) async -> UploadImage? {
        await Task.detached(priority: .userInitiated) { jpeg(from: image, maxLongSide: maxLongSide, name: name) }.value
    }

    private static func jpeg(from image: UIImage, maxLongSide: CGFloat, name: String) -> UploadImage? {
        let pixels = CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale)
        let longSide = max(pixels.width, pixels.height)
        guard longSide > 0 else { return nil }
        let factor = min(1, maxLongSide / longSide)
        let target = CGSize(width: max(1, (pixels.width * factor).rounded()), height: max(1, (pixels.height * factor).rounded()))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let rendered = UIGraphicsImageRenderer(size: target, format: format).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(origin: .zero, size: target))
            image.draw(in: CGRect(origin: .zero, size: target))
        }
        guard let data = rendered.jpegData(compressionQuality: 0.85) else { return nil }
        return UploadImage(data: data, mimeType: "image/jpeg", filename: "\(name).jpg")
    }
}
