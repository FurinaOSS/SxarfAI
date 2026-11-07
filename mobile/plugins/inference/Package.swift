// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SxarfInference",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "SxarfInference", targets: ["SxarfInferencePlugin"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.6.0")
    ],
    targets: [
        .binaryTarget(
            name: "llama",
            path: "../../native/llama.cpp/build-apple/llama.xcframework"
        ),
        .target(
            name: "SxarfRuntime",
            dependencies: ["llama"],
            path: "ios/Sources/SxarfRuntime",
            publicHeadersPath: "include",
            cxxSettings: [.headerSearchPath("include")]
        ),
        .target(
            name: "SxarfInferencePlugin",
            dependencies: [
                "SxarfRuntime",
                .product(name: "Capacitor", package: "capacitor-swift-pm")
            ],
            path: "ios/Sources/SxarfInferencePlugin"
        ),
        .testTarget(
            name: "SxarfRuntimeTests",
            dependencies: ["SxarfRuntime"],
            path: "ios/Tests/SxarfRuntimeTests"
        )
    ],
    cxxLanguageStandard: .cxx17
)
