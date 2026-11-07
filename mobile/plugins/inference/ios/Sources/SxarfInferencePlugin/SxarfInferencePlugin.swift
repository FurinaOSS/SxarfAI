import Capacitor
import CryptoKit
import Darwin
import Foundation
import SxarfRuntime
import UIKit

private struct InstalledModel: Codable {
    let id: String
    let filename: String
    let sizeBytes: Int64
    let sha256: String
}

private final class GenerationSink {
    private let lock = NSLock()
    private var output = ""
    weak var plugin: SxarfInferencePlugin?

    func append(_ text: String) {
        lock.lock()
        output.append(text)
        lock.unlock()
        DispatchQueue.main.async { [weak plugin] in
            plugin?.notifyListeners("token", data: ["token": text])
        }
    }

    func value() -> String {
        lock.lock()
        defer { lock.unlock() }
        return output
    }
}

private final class ModelDownloadTransfer: NSObject, URLSessionDownloadDelegate {
    private weak var plugin: SxarfInferencePlugin?
    private let modelId: String
    private let expectedSize: Int64
    private let destinationDirectory: URL
    private var continuation: CheckedContinuation<URL, Error>?
    private var session: URLSession?
    private var downloadedFile: URL?
    private var lastPercent: Int64 = -1

    init(plugin: SxarfInferencePlugin, modelId: String, expectedSize: Int64, destinationDirectory: URL) {
        self.plugin = plugin
        self.modelId = modelId
        self.expectedSize = expectedSize
        self.destinationDirectory = destinationDirectory
    }

    func run(url: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            let configuration = URLSessionConfiguration.default
            session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
            session?.downloadTask(with: url).resume()
        }
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        let total = totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : expectedSize
        let percent = total > 0 ? totalBytesWritten * 100 / total : 0
        guard percent != lastPercent else { return }
        lastPercent = percent
        plugin?.emitDownloadProgress(modelId, received: totalBytesWritten, total: total, state: "downloading")
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        do {
            guard let response = downloadTask.response as? HTTPURLResponse,
                  (200..<300).contains(response.statusCode) else {
                throw DownloadError.invalidResponse
            }
            let staging = destinationDirectory.appendingPathComponent("\(modelId).download")
            if FileManager.default.fileExists(atPath: staging.path) {
                try FileManager.default.removeItem(at: staging)
            }
            try FileManager.default.moveItem(at: location, to: staging)
            downloadedFile = staging
        } catch {
            continuation?.resume(throwing: error)
            continuation = nil
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        guard let continuation else { return }
        self.continuation = nil
        if let error {
            continuation.resume(throwing: error)
        } else if let downloadedFile {
            continuation.resume(returning: downloadedFile)
        } else {
            continuation.resume(throwing: DownloadError.missingFile)
        }
        self.session = nil
    }
}

private let sxarfTokenCallback: sxarf_token_callback = { bytes, length, context in
    guard let bytes, let context, length > 0 else { return }
    let sink = Unmanaged<GenerationSink>.fromOpaque(context).takeUnretainedValue()
    let byteArray = UnsafeBufferPointer(start: bytes, count: length).map { UInt8(bitPattern: $0) }
    let text = String(decoding: byteArray, as: UTF8.self)
    sink.append(text)
}

@objc(SxarfInferencePlugin)
public class SxarfInferencePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "SxarfInferencePlugin"
    public let jsName = "SxarfInference"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "initialize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "listModels", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "downloadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "deleteModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "loadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "unloadModel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "generate", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelGeneration", returnType: CAPPluginReturnPromise)
    ]

    private let generationLock = NSLock()
    private let downloadLock = NSLock()
    private var generating = false
    private var loadedModelId: String?
    private var downloadingIds = Set<String>()

    override public func load() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleMemoryWarning),
            name: UIApplication.didReceiveMemoryWarningNotification,
            object: nil
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    @objc public func initialize(_ call: CAPPluginCall) {
        guard sxarf_runtime_initialize() else {
            call.reject("llama.cpp runtime initialization failed.")
            return
        }
        do {
            try ensureModelDirectory()
            let fileSystem = try FileManager.default.attributesOfFileSystem(forPath: NSHomeDirectory())
            let freeBytes = (fileSystem[.systemFreeSize] as? NSNumber)?.uint64Value ?? 0
            let backend = String(cString: sxarf_runtime_backend())
            call.resolve([
                "runtime": "llama.cpp",
                "version": String(cString: sxarf_runtime_version()),
                "commit": String(cString: sxarf_runtime_commit()),
                "backend": backend,
                "gpuAvailable": sxarf_runtime_supports_gpu(),
                "platform": "iOS/iPadOS",
                "totalMemoryBytes": ProcessInfo.processInfo.physicalMemory,
                "availableStorageBytes": freeBytes
            ])
        } catch {
            call.reject("Could not prepare the on-device model directory.", nil, error)
        }
    }

    @objc public func listModels(_ call: CAPPluginCall) {
        do {
            let records = try readInstalledModels()
            let models = records.compactMap { record -> [String: Any]? in
                let path = modelDirectory().appendingPathComponent(record.filename)
                guard FileManager.default.fileExists(atPath: path.path) else { return nil }
                return ["id": record.id, "path": path.path, "sizeBytes": record.sizeBytes]
            }
            call.resolve(["models": models])
        } catch {
            call.reject("Could not read the installed-model list.", nil, error)
        }
    }

    @objc public func downloadModel(_ call: CAPPluginCall) {
        guard let id = call.getString("id"), isValidModelId(id),
              let filename = call.getString("filename"), isValidFilename(filename),
              let source = call.getString("url"), let url = URL(string: source),
              url.scheme == "https", url.host == "huggingface.co",
              let sha256 = call.getString("sha256"), isValidSha256(sha256),
              let sizeNumber = call.options["sizeBytes"] as? NSNumber,
              sizeNumber.int64Value > 0 else {
            call.reject("The model download metadata is invalid.")
            return
        }
        guard loadedModelId != id else {
            call.reject("Unload the model before replacing its file.")
            return
        }
        guard beginDownload(id) else {
            call.reject("This model is already downloading.")
            return
        }
        let expectedSize = sizeNumber.int64Value
        Task {
            defer { endDownload(id) }
            do {
                try ensureModelDirectory()
                let transfer = ModelDownloadTransfer(
                    plugin: self,
                    modelId: id,
                    expectedSize: expectedSize,
                    destinationDirectory: modelDirectory()
                )
                let temporaryURL = try await transfer.run(url: url)
                emitDownloadProgress(id, received: expectedSize, total: expectedSize, state: "verifying")
                let attributes = try FileManager.default.attributesOfItem(atPath: temporaryURL.path)
                guard (attributes[.size] as? NSNumber)?.int64Value == expectedSize else {
                    throw DownloadError.sizeMismatch
                }
                guard try Self.sha256(of: temporaryURL).lowercased() == sha256.lowercased() else {
                    throw DownloadError.checksumMismatch
                }
                let destination = modelDirectory().appendingPathComponent(filename)
                if FileManager.default.fileExists(atPath: destination.path) {
                    try FileManager.default.removeItem(at: destination)
                }
                try FileManager.default.moveItem(at: temporaryURL, to: destination)
                var records = try readInstalledModels().filter { $0.id != id }
                records.append(InstalledModel(
                    id: id,
                    filename: filename,
                    sizeBytes: expectedSize,
                    sha256: sha256.lowercased()
                ))
                try writeInstalledModels(records)
                emitDownloadProgress(id, received: expectedSize, total: expectedSize, state: "complete")
                call.resolve(["id": id, "path": destination.path, "sizeBytes": expectedSize])
            } catch {
                emitDownloadProgress(id, received: 0, total: expectedSize, state: "failed")
                call.reject("Model download or checksum verification failed: \(error.localizedDescription)", nil, error)
            }
        }
    }

    @objc public func deleteModel(_ call: CAPPluginCall) {
        guard let id = call.getString("id"), isValidModelId(id) else {
            call.reject("A valid model ID is required.")
            return
        }
        guard !isGenerating else {
            call.reject("Stop generation before deleting a model.")
            return
        }
        guard loadedModelId != id else {
            call.reject("Unload the model before deleting it.")
            return
        }
        do {
            var records = try readInstalledModels()
            if let record = records.first(where: { $0.id == id }) {
                let file = modelDirectory().appendingPathComponent(record.filename)
                if FileManager.default.fileExists(atPath: file.path) {
                    try FileManager.default.removeItem(at: file)
                }
                records.removeAll { $0.id == id }
                try writeInstalledModels(records)
            }
            call.resolve()
        } catch {
            call.reject("Could not delete the model.", nil, error)
        }
    }

    @objc public func loadModel(_ call: CAPPluginCall) {
        guard let id = call.getString("id"), isValidModelId(id),
              let contextValue = call.options["contextLength"] as? NSNumber,
              contextValue.intValue > 0,
              let threadValue = call.options["threads"] as? NSNumber,
              threadValue.intValue > 0 else {
            call.reject("The model load options are invalid.")
            return
        }
        guard !isGenerating else {
            call.reject("Stop generation before switching models.")
            return
        }
        do {
            guard let record = try readInstalledModels().first(where: { $0.id == id }) else {
                call.reject("The model is not installed on this device.")
                return
            }
            let path = modelDirectory().appendingPathComponent(record.filename)
            DispatchQueue.global(qos: .userInitiated).async {
                var errorBuffer = [CChar](repeating: 0, count: 512)
                let result = path.path.withCString { pathPointer in
                    errorBuffer.withUnsafeMutableBufferPointer { errorPointer in
                        sxarf_model_load(
                            pathPointer,
                            UInt32(contextValue.intValue),
                            Int32(min(threadValue.intValue, 8)),
                            errorPointer.baseAddress,
                            errorPointer.count
                        )
                    }
                }
                guard result == 0 else {
                    DispatchQueue.main.async { call.reject(String(cString: errorBuffer)) }
                    return
                }
                let backend = String(cString: sxarf_runtime_backend())
                let info: [String: Any] = [
                    "id": id,
                    "description": String(cString: sxarf_model_description()),
                    "sizeBytes": record.sizeBytes,
                    "parameterCount": sxarf_model_parameter_count(),
                    "trainedContext": sxarf_model_trained_context(),
                    "activeContext": sxarf_model_context_length(),
                    "backend": backend,
                    "processMemoryBytes": self.residentMemoryBytes()
                ]
                DispatchQueue.main.async {
                    self.loadedModelId = id
                    call.resolve(info)
                }
            }
        } catch {
            call.reject("Could not load the model.", nil, error)
        }
    }

    @objc public func unloadModel(_ call: CAPPluginCall) {
        guard !isGenerating else {
            call.reject("Stop generation before unloading the model.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            sxarf_model_unload()
            DispatchQueue.main.async {
                self.loadedModelId = nil
                call.resolve()
            }
        }
    }

    @objc public func generate(_ call: CAPPluginCall) {
        guard let prompt = call.getString("prompt"), !prompt.isEmpty,
              let tokenValue = call.options["maxTokens"] as? NSNumber,
              tokenValue.intValue > 0,
              let temperatureValue = call.options["temperature"] as? NSNumber else {
            call.reject("The generation options are invalid.")
            return
        }
        guard loadedModelId != nil else {
            call.reject("Load a model before generating.")
            return
        }
        guard setGenerating(true) else {
            call.reject("Generation is already running.")
            return
        }
        let sink = GenerationSink()
        sink.plugin = self
        Task.detached {
            defer { self.setGenerating(false) }
            var errorBuffer = [CChar](repeating: 0, count: 512)
            let sinkPointer = Unmanaged.passUnretained(sink).toOpaque()
            let status = prompt.withCString { promptPointer in
                errorBuffer.withUnsafeMutableBufferPointer { errorPointer in
                    sxarf_generate(
                        promptPointer,
                        Int32(min(tokenValue.intValue, 4096)),
                        Float(max(0, min(temperatureValue.doubleValue, 2))),
                        sxarfTokenCallback,
                        sinkPointer,
                        errorPointer.baseAddress,
                        errorPointer.count
                    )
                }
            }
            DispatchQueue.main.async {
                if status < 0 {
                    call.reject(String(cString: errorBuffer))
                } else {
                    call.resolve(["text": sink.value(), "cancelled": status == 1])
                }
            }
        }
    }

    @objc public func cancelGeneration(_ call: CAPPluginCall) {
        sxarf_cancel_generation()
        call.resolve()
    }

    @objc private func handleMemoryWarning() {
        notifyListeners("memoryWarning", data: [
            "message": "iOS reported memory pressure. Stop generation and unload the model if the app becomes unstable."
        ])
    }

    private var isGenerating: Bool {
        generationLock.lock()
        defer { generationLock.unlock() }
        return generating
    }

    @discardableResult
    private func setGenerating(_ value: Bool) -> Bool {
        generationLock.lock()
        defer { generationLock.unlock() }
        if value && generating { return false }
        generating = value
        return true
    }

    private func modelDirectory() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("SxarfAI/Models", isDirectory: true)
    }

    private func ensureModelDirectory() throws {
        try FileManager.default.createDirectory(at: modelDirectory(), withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var directory = modelDirectory()
        try directory.setResourceValues(values)
    }

    func emitDownloadProgress(_ id: String, received: Int64, total: Int64, state: String) {
        DispatchQueue.main.async { [weak self] in
            self?.notifyListeners("downloadProgress", data: [
                "modelId": id,
                "receivedBytes": received,
                "totalBytes": total,
                "state": state
            ])
        }
    }

    private func beginDownload(_ id: String) -> Bool {
        downloadLock.lock()
        defer { downloadLock.unlock() }
        return downloadingIds.insert(id).inserted
    }

    private func endDownload(_ id: String) {
        downloadLock.lock()
        downloadingIds.remove(id)
        downloadLock.unlock()
    }

    private func modelIndexURL() -> URL {
        modelDirectory().appendingPathComponent("installed-models.json")
    }

    private func readInstalledModels() throws -> [InstalledModel] {
        let url = modelIndexURL()
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        return try JSONDecoder().decode([InstalledModel].self, from: Data(contentsOf: url))
    }

    private func writeInstalledModels(_ records: [InstalledModel]) throws {
        let data = try JSONEncoder().encode(records)
        try data.write(to: modelIndexURL(), options: .atomic)
    }

    private func isValidModelId(_ value: String) -> Bool {
        value.range(of: "^[a-z0-9][a-z0-9-]{0,80}$", options: .regularExpression) != nil
    }

    private func isValidFilename(_ value: String) -> Bool {
        value == URL(fileURLWithPath: value).lastPathComponent && value.hasSuffix(".gguf")
    }

    private func isValidSha256(_ value: String) -> Bool {
        value.range(of: "^[a-fA-F0-9]{64}$", options: .regularExpression) != nil
    }

    private static func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var digest = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            digest.update(data: chunk)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func residentMemoryBytes() -> UInt64 {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size) / 4
        let status = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return status == KERN_SUCCESS ? UInt64(info.resident_size) : 0
    }
}

private enum DownloadError: LocalizedError {
    case invalidResponse
    case missingFile
    case sizeMismatch
    case checksumMismatch

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "The model server returned an invalid response."
        case .missingFile:
            return "The model server completed without a downloaded file."
        case .sizeMismatch:
            return "The downloaded model size does not match the catalog."
        case .checksumMismatch:
            return "The downloaded model SHA-256 does not match the catalog."
        }
    }
}
