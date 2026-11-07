export interface MobileModel {
  id: string;
  name: string;
  source: string;
  revision: string;
  filename: string;
  sizeBytes: number;
  quantization: string;
  contextLength: number;
  license: string;
  sha256: string;
  minimumRecommendedRamBytes: number;
  recommendedFreeStorageBytes: number;
  promptTemplate: {
    system: string;
    user: string;
    assistant: string;
  };
  notes: string;
}

export const MODEL_CATALOG: readonly MobileModel[] = [
  {
    id: "tinyllama-1.1b-chat-q4km",
    name: "TinyLlama 1.1B Chat (Q4_K_M)",
    source: "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
    revision: "52e7645ba7c309695bec7ac98f4f005b139cf465",
    filename: "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
    sizeBytes: 668788096,
    quantization: "Q4_K_M",
    contextLength: 2048,
    license: "Apache-2.0",
    sha256: "9fecc3b3cd76bba89d504f29b616eedf7da85b96540e490ca5824d3f7d2776a0",
    minimumRecommendedRamBytes: 4 * 1024 ** 3,
    recommendedFreeStorageBytes: 2 * 1024 ** 3,
    promptTemplate: {
      system: "<|system|>\n{content}</s>\n",
      user: "<|user|>\n{content}</s>\n",
      assistant: "<|assistant|>\n{content}</s>\n",
    },
    notes:
      "Upstream TinyLlama config declares max_position_embeddings=2048 (https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0/raw/main/config.json). RAM and free-storage values are conservative recommendations, not measured device requirements.",
  },
];

export function modelDownloadUrl(model: MobileModel): string {
  return `${model.source}/resolve/${model.revision}/${encodeURIComponent(model.filename)}`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex > 0 ? 1 : 0)} ${units[unitIndex]}`;
}
