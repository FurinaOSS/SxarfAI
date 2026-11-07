import Foundation
import SxarfRuntime
import XCTest

private final class TokenCapture {
    var bytes = [UInt8]()
    var cancelAfterFirstToken = false
    var tokenCount = 0
}

private let captureToken: sxarf_token_callback = { bytes, length, context in
    guard let bytes, let context, length > 0 else { return }
    let capture = Unmanaged<TokenCapture>.fromOpaque(context).takeUnretainedValue()
    capture.bytes.append(contentsOf: UnsafeBufferPointer(start: bytes, count: length).map { UInt8(bitPattern: $0) })
    capture.tokenCount += 1
    if capture.cancelAfterFirstToken {
        sxarf_cancel_generation()
    }
}

final class SxarfRuntimeSmokeTests: XCTestCase {
    func testLoadGenerateCancelAndUnload() throws {
        guard let modelPath = ProcessInfo.processInfo.environment["SXARF_TEST_GGUF"],
              FileManager.default.fileExists(atPath: modelPath) else {
            throw XCTSkip("Set SXARF_TEST_GGUF to a development-only small GGUF fixture.")
        }

        XCTAssertTrue(sxarf_runtime_initialize())
        var errorBuffer = [CChar](repeating: 0, count: 512)
        let loadResult = modelPath.withCString { path in
            errorBuffer.withUnsafeMutableBufferPointer { error in
                sxarf_model_load(path, 64, 2, error.baseAddress, error.count)
            }
        }
        XCTAssertEqual(loadResult, 0, String(cString: errorBuffer))
        XCTAssertTrue(sxarf_model_is_loaded())
        XCTAssertGreaterThan(sxarf_model_parameter_count(), 0)

        let generated = TokenCapture()
        errorBuffer = [CChar](repeating: 0, count: 512)
        let generateResult = "Once upon a time".withCString { prompt in
            errorBuffer.withUnsafeMutableBufferPointer { error in
                sxarf_generate(
                    prompt,
                    8,
                    0.7,
                    captureToken,
                    Unmanaged.passUnretained(generated).toOpaque(),
                    error.baseAddress,
                    error.count
                )
            }
        }
        XCTAssertEqual(generateResult, 0, String(cString: errorBuffer))
        XCTAssertGreaterThan(generated.tokenCount, 0)
        XCTAssertFalse(generated.bytes.isEmpty)

        let cancelled = TokenCapture()
        cancelled.cancelAfterFirstToken = true
        errorBuffer = [CChar](repeating: 0, count: 512)
        let cancelResult = "Continue the story".withCString { prompt in
            errorBuffer.withUnsafeMutableBufferPointer { error in
                sxarf_generate(
                    prompt,
                    32,
                    0.7,
                    captureToken,
                    Unmanaged.passUnretained(cancelled).toOpaque(),
                    error.baseAddress,
                    error.count
                )
            }
        }
        XCTAssertEqual(cancelResult, 1)
        XCTAssertGreaterThan(cancelled.tokenCount, 0)

        sxarf_model_unload()
        XCTAssertFalse(sxarf_model_is_loaded())
    }
}
