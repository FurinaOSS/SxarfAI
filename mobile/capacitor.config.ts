import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.sxarf.ai.mobile",
  appName: "Sxarf AI",
  webDir: "dist",
  ios: {
    contentInset: "automatic",
    preferredContentMode: "mobile",
  },
  android: {
    backgroundColor: "#0b0910",
  },
};

export default config;
