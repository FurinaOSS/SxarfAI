import { registerPlugin } from "@capacitor/core";
import type { PluginListenerHandle } from "@capacitor/core";

export interface RuntimeInfo {
  runtime: string;
  version: string;
  commit: string;
  backend: "Metal" | "Vulkan" | "CPU";
  gpuAvailable: boolean;
  platform?: string;
  totalMemoryBytes?: number;
  availableMemoryBytes?: number;
  availableStorageBytes?: number;
}

export interface ModelInfo {
  id: string;
  description: string;
  sizeBytes: number;
  parameterCount: number;
  trainedContext: number;
  activeContext: number;
  backend: "Metal" | "Vulkan" | "CPU";
  processMemoryBytes: number;
}

export interface NativeModel {
  id: string;
  path: string;
  sizeBytes: number;
}

export interface DownloadProgress {
  modelId: string;
  receivedBytes: number;
  totalBytes: number;
  state: "downloading" | "verifying" | "complete" | "failed";
}

export interface TokenEvent {
  token: string;
}

export interface SxarfInferencePlugin {
  initialize(): Promise<RuntimeInfo>;
  listModels(): Promise<{ models: NativeModel[] }>;
  downloadModel(options: {
    id: string;
    url: string;
    filename: string;
    sha256: string;
    sizeBytes: number;
  }): Promise<NativeModel>;
  deleteModel(options: { id: string }): Promise<void>;
  loadModel(options: {
    id: string;
    contextLength: number;
    threads: number;
  }): Promise<ModelInfo>;
  unloadModel(): Promise<void>;
  generate(options: {
    prompt: string;
    maxTokens: number;
    temperature: number;
  }): Promise<{ text: string; cancelled: boolean }>;
  cancelGeneration(): Promise<void>;
  addListener(
    eventName: "token",
    listenerFunc: (event: TokenEvent) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    eventName: "downloadProgress",
    listenerFunc: (event: DownloadProgress) => void,
  ): Promise<PluginListenerHandle>;
  addListener(
    eventName: "memoryWarning",
    listenerFunc: (event: { message: string }) => void,
  ): Promise<PluginListenerHandle>;
}

export const SxarfInference = registerPlugin<SxarfInferencePlugin>(
  "SxarfInference",
);
