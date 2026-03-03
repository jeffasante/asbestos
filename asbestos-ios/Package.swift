// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "asbestos-ios",
    platforms: [
        .iOS(.v16),
        .macOS(.v13)
    ],
    products: [
        .library(
            name: "asbestos-ios",
            targets: ["asbestos-ios"]),
    ],
    targets: [
        .target(
            name: "asbestos-ios",
            dependencies: ["llama"]),
        .testTarget(
            name: "asbestos-iosTests",
            dependencies: ["asbestos-ios", "llama"]),
        .binaryTarget(
            name: "llama",
            path: "Frameworks/llama.xcframework"
        )
    ]
)
