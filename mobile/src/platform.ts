import { Capacitor } from "@capacitor/core";
import { SxarfInference } from "@sxarf/inference";

export const mobilePlatform = {
  isNative: () => Capacitor.isNativePlatform(),
  inference: SxarfInference,
};
