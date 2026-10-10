import simd

/// Maps canonical room space (Y-up, origin at floor center, back wall at z = -depth/2,
/// width along +X) onto the real floor from two taps: the back-left corner, then any
/// point further along the back wall to the right.
enum RoomAlignment {
    /// Minimum distance between the two taps; closer points give an unreliable direction.
    static let minimumBaseline: Float = 0.25

    /// World transform of the room origin, or nil if the two points are too close.
    static func transform(corner: SIMD3<Float>, alongBackWall point: SIMD3<Float>, room: Room) -> simd_float4x4? {
        var direction = point - corner
        direction.y = 0
        let length = simd_length(direction)
        guard length >= minimumBaseline else { return nil }
        let xAxis = direction / length
        let yAxis = SIMD3<Float>(0, 1, 0)
        // Right-handed: +Z = X × Y points from the back wall into the room.
        let zAxis = simd_cross(xAxis, yAxis)
        let halfW = Float(room.widthM) / 2, halfD = Float(room.depthM) / 2
        let origin = corner + xAxis * halfW + zAxis * halfD
        return simd_float4x4(columns: (SIMD4(xAxis, 0), SIMD4(yAxis, 0), SIMD4(zAxis, 0), SIMD4(origin, 1)))
    }

    /// Rotation about +Y that makes an object's front (+Z) face `viewer` from `position`.
    static func yawFacing(_ viewer: SIMD3<Float>, from position: SIMD3<Float>) -> Float {
        atan2(viewer.x - position.x, viewer.z - position.z)
    }
}
