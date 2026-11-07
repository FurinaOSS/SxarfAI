import "./style.css";
import { Haptics, ImpactStyle } from "@capacitor/haptics";
import { Preferences } from "@capacitor/preferences";
import { Share } from "@capacitor/share";
import type { DownloadProgress, ModelInfo, NativeModel, RuntimeInfo } from "@sxarf/inference";
import { formatBytes, MODEL_CATALOG, modelDownloadUrl, type MobileModel } from "./catalog";
import { mobilePlatform } from "./platform";

type Role = "user" | "assistant";
interface Message { role: Role; content: string; }
interface Conversation {
  id: string;
  title: string;
  updated: number;
  messages: Message[];
}
interface AppState {
  chats: Conversation[];
  currentChatId: string | null;
  selectedModelId: string;
  contextLength: number;
  temperature: number;
}

const STORAGE_KEY = "sxarf-mobile-state-v1";
const DEFAULT_MODEL_ID = MODEL_CATALOG[0]?.id ?? "";
const defaultState = (): AppState => ({
  chats: [],
  currentChatId: null,
  selectedModelId: DEFAULT_MODEL_ID,
  contextLength: 2048,
  temperature: 0.7,
});
let state = defaultState();
let activeConversation: Conversation | null = null;
let runtime: RuntimeInfo | null = null;
let runtimeStatus = "Checking on-device runtime…";
let loadedModel: ModelInfo | null = null;
let installedModels: NativeModel[] = [];
let generating = false;
let progressByModel = new Map<string, DownloadProgress>();
let toastTimer: number | undefined;

const byId = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing mobile UI element: ${id}`);
  return element as T;
};

const elements = {
  sidebar: byId<HTMLElement>("sidebar"),
  runtimeStatus: byId<HTMLElement>("runtimeStatus"),
  runtimeDetails: byId<HTMLElement>("runtimeDetails"),
  topbarTitle: byId<HTMLElement>("topbarTitle"),
  modelSelect: byId<HTMLSelectElement>("modelSelect"),
  messagesScroll: byId<HTMLElement>("messagesScroll"),
  welcome: byId<HTMLElement>("welcome"),
  messages: byId<HTMLElement>("messages"),
  messageInput: byId<HTMLTextAreaElement>("messageInput"),
  sendButton: byId<HTMLButtonElement>("sendButton"),
  stopButton: byId<HTMLButtonElement>("stopButton"),
  modelStatus: byId<HTMLElement>("modelStatus"),
  chatHistory: byId<HTMLElement>("chatHistory"),
  historySearch: byId<HTMLInputElement>("historySearch"),
  modelList: byId<HTMLElement>("modelList"),
  deviceCard: byId<HTMLElement>("deviceCard"),
  contextSetting: byId<HTMLSelectElement>("contextSetting"),
  temperatureSetting: byId<HTMLInputElement>("temperatureSetting"),
  unloadButton: byId<HTMLButtonElement>("unloadButton"),
  toast: byId<HTMLElement>("toast"),
};

function showToast(message: string): void {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 3500);
}

function saveState(): void {
  void Preferences.set({ key: STORAGE_KEY, value: JSON.stringify(state) }).catch((error: unknown) => {
    console.error("Could not save mobile chat history:", error);
    showToast("Could not save chat history on this device.");
  });
}

async function restoreState(): Promise<void> {
  const result = await Preferences.get({ key: STORAGE_KEY });
  if (!result.value) return;
  try {
    const saved = JSON.parse(result.value) as Partial<AppState>;
    state = {
      ...defaultState(),
      ...saved,
      chats: Array.isArray(saved.chats) ? saved.chats.filter(isConversation) : [],
      contextLength: [1024, 2048, 4096].includes(Number(saved.contextLength))
        ? Number(saved.contextLength)
        : 2048,
      temperature: Math.max(0, Math.min(1.2, Number(saved.temperature) || 0.7)),
    };
  } catch (error) {
    console.error("Could not parse saved mobile chat history:", error);
    showToast("Saved chat history could not be read.");
  }
}

function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== "object") return false;
  const conversation = value as Partial<Conversation>;
  return typeof conversation.id === "string" && Array.isArray(conversation.messages);
}

function currentConversation(): Conversation {
  if (activeConversation) return activeConversation;
  const existing = state.chats.find((chat) => chat.id === state.currentChatId);
  activeConversation = existing ?? {
    id: crypto.randomUUID(),
    title: "New chat",
    updated: Date.now(),
    messages: [],
  };
  return activeConversation;
}

function persistConversation(): void {
  if (!activeConversation || !activeConversation.messages.length) return;
  const firstUser = activeConversation.messages.find((message) => message.role === "user");
  activeConversation.title = (firstUser?.content ?? "New chat").replace(/\s+/g, " ").slice(0, 64);
  activeConversation.updated = Date.now();
  state.currentChatId = activeConversation.id;
  state.chats = [
    activeConversation,
    ...state.chats.filter((chat) => chat.id !== activeConversation?.id),
  ].sort((a, b) => b.updated - a.updated).slice(0, 100);
  saveState();
  renderHistory();
}

function renderInline(text: string, parent: HTMLElement): void {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    parent.append(document.createTextNode(text.slice(offset, index)));
    const token = match[0];
    if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.append(code);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.append(strong);
    } else if (token.startsWith("*")) {
      const emphasis = document.createElement("em");
      emphasis.textContent = token.slice(1, -1);
      parent.append(emphasis);
    } else {
      const linkMatch = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(token);
      if (linkMatch) {
        const link = document.createElement("a");
        link.textContent = linkMatch[1];
        link.href = linkMatch[2];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
      }
    }
    offset = index + token.length;
  }
  parent.append(document.createTextNode(text.slice(offset)));
}

function renderMarkdown(container: HTMLElement, markdown: string): void {
  container.replaceChildren();
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  let index = 0;
  const flushParagraph = (): void => {
    if (!paragraph.length) return;
    const p = document.createElement("p");
    paragraph.forEach((line, lineIndex) => {
      if (lineIndex) p.append(document.createElement("br"));
      renderInline(line, p);
    });
    container.append(p);
    paragraph = [];
  };
  while (index < lines.length) {
    const line = lines[index];
    const fence = /^\s*```([\w+-]*)\s*$/.exec(line);
    if (fence) {
      flushParagraph();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) codeLines.push(lines[index++]);
      if (index < lines.length) index += 1;
      const block = document.createElement("div");
      block.className = "code-block";
      const head = document.createElement("div");
      head.className = "code-head";
      const language = document.createElement("span");
      language.textContent = fence[1] || "code";
      const copy = document.createElement("button");
      copy.textContent = "Copy code";
      const codeText = codeLines.join("\n");
      copy.addEventListener("click", () => void navigator.clipboard.writeText(codeText)
        .then(() => showToast("Code copied."))
        .catch((error: unknown) => {
          console.error("Could not copy code:", error);
          showToast("Clipboard access is unavailable.");
        }));
      head.append(language, copy);
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeText;
      pre.append(code);
      block.append(head, pre);
      container.append(block);
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      const h = document.createElement(`h${heading[1].length}`);
      renderInline(heading[2], h);
      container.append(h);
      index += 1;
      continue;
    }
    if (!line.trim()) flushParagraph();
    else paragraph.push(line);
    index += 1;
  }
  flushParagraph();
}

function renderMessage(message: Message, index: number): HTMLElement {
  const row = document.createElement("article");
  row.className = `message ${message.role}`;
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = message.role === "assistant" ? "S" : "●";
  const body = document.createElement("div");
  body.className = "message-body";
  const role = document.createElement("div");
  role.className = "message-role";
  role.textContent = message.role === "assistant" ? "Sxarf AI" : "You";
  const content = document.createElement("div");
  content.className = "message-content";
  renderMarkdown(content, message.content);
  const actions = document.createElement("div");
  actions.className = "message-actions";
  if (message.role === "assistant") {
    const copy = document.createElement("button");
    copy.textContent = "Copy";
    copy.addEventListener("click", () => void navigator.clipboard.writeText(message.content)
      .then(() => showToast("Message copied."))
      .catch((error: unknown) => {
        console.error("Could not copy message:", error);
        showToast("Clipboard access is unavailable.");
      }));
    actions.append(copy);
    if (index === currentConversation().messages.length - 1) {
      const regenerate = document.createElement("button");
      regenerate.textContent = "Regenerate";
      regenerate.addEventListener("click", () => void regenerateLast());
      actions.append(regenerate);
    }
  } else {
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.addEventListener("click", () => editMessage(index));
    actions.append(edit);
  }
  body.append(role, content, actions);
  row.append(avatar, body);
  return row;
}

function renderConversation(): void {
  const conversation = activeConversation;
  elements.welcome.hidden = Boolean(conversation?.messages.length);
  elements.messages.replaceChildren();
  if (!conversation) {
    elements.topbarTitle.textContent = "New chat";
    return;
  }
  elements.topbarTitle.textContent = conversation.title;
  conversation.messages.forEach((message, index) => {
    elements.messages.append(renderMessage(message, index));
  });
  elements.messagesScroll.scrollTop = elements.messagesScroll.scrollHeight;
}

function renderHistory(): void {
  const query = elements.historySearch.value.trim().toLowerCase();
  const chats = state.chats.filter((chat) => chat.title.toLowerCase().includes(query));
  elements.chatHistory.replaceChildren();
  if (!chats.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = query ? "No conversations match." : "Your saved conversations will appear here.";
    elements.chatHistory.append(empty);
    return;
  }
  for (const chat of chats) {
    const row = document.createElement("div");
    row.className = `history-item${chat.id === state.currentChatId ? " active" : ""}`;
    const button = document.createElement("button");
    button.className = "history-item-open";
    const title = document.createElement("span");
    title.textContent = chat.title || "New chat";
    const deleteButton = document.createElement("button");
    deleteButton.className = "icon-button";
    deleteButton.type = "button";
    deleteButton.title = "Delete conversation";
    deleteButton.setAttribute("aria-label", `Delete ${chat.title}`);
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      state.chats = state.chats.filter((item) => item.id !== chat.id);
      if (activeConversation?.id === chat.id) {
        activeConversation = null;
        state.currentChatId = null;
        renderConversation();
      }
      saveState();
      renderHistory();
    });
    button.append(title);
    button.addEventListener("click", () => {
      if (generating) return;
      activeConversation = chat;
      state.currentChatId = chat.id;
      renderConversation();
      renderHistory();
      closeSidebar();
    });
    row.append(button, deleteButton);
    elements.chatHistory.append(row);
  }
}

function formatPrompt(messages: Message[], model: MobileModel): string {
  return messages.map((message) => {
    const template = model.promptTemplate[message.role];
    return template.replace("{content}", message.content);
  }).join("");
}

function syncChatControls(): void {
  elements.sendButton.disabled = !loadedModel || generating || !elements.messageInput.value.trim();
  elements.messageInput.disabled = !loadedModel || generating;
  elements.messageInput.placeholder = loadedModel ? "Message Sxarf AI…" : "Load a model to start chatting…";
  elements.sendButton.hidden = generating;
  elements.stopButton.hidden = !generating;
  elements.modelSelect.disabled = generating;
  elements.unloadButton.disabled = !loadedModel || generating;
  elements.modelStatus.textContent = loadedModel
    ? `${loadedModel.backend} · ${formatBytes(loadedModel.processMemoryBytes)} process memory`
    : runtime
      ? `${runtime.backend} inference ready · no model loaded`
      : runtimeStatus;
}

function setRuntimeInfo(info: RuntimeInfo): void {
  runtime = info;
  runtimeStatus = `${info.backend} inference ready · llama.cpp ${info.version}`;
  elements.runtimeStatus.textContent = runtimeStatus;
  elements.runtimeStatus.previousElementSibling?.classList.add("ready");
  elements.runtimeDetails.textContent = [
    `${info.runtime} ${info.version}`,
    `Commit: ${info.commit}`,
    `Backend: ${info.backend}`,
    `GPU offload: ${info.gpuAvailable ? "available" : "unavailable"}`,
    info.totalMemoryBytes ? `Device memory: ${formatBytes(info.totalMemoryBytes)}` : "",
    info.availableStorageBytes ? `Available storage: ${formatBytes(info.availableStorageBytes)}` : "",
  ].filter(Boolean).join("\n");
  const memory = info.totalMemoryBytes ? ` · RAM ${formatBytes(info.totalMemoryBytes)}` : "";
  const storage = info.availableStorageBytes ? ` · Free storage ${formatBytes(info.availableStorageBytes)}` : "";
  elements.deviceCard.textContent = `Device: ${info.platform ?? "mobile"} · Runtime: ${info.backend}${memory}${storage}. Compatibility recommendations are estimates, not device test results.`;
}

function setDownloadProgress(progress: DownloadProgress): void {
  progressByModel.set(progress.modelId, progress);
  renderModels();
}

async function initializeNative(): Promise<void> {
  if (!mobilePlatform.isNative()) {
    runtimeStatus = "Web preview only · native inference is unavailable";
    elements.runtimeStatus.textContent = runtimeStatus;
    elements.runtimeDetails.textContent = "Run on an iOS or Android application to access native inference.";
    elements.deviceCard.textContent = "Native device information is unavailable in a browser preview.";
    return;
  }
  try {
    const [info, models] = await Promise.all([
      mobilePlatform.inference.initialize(),
      mobilePlatform.inference.listModels(),
    ]);
    setRuntimeInfo(info);
    installedModels = models.models;
    await chooseSavedModel();
  } catch (error) {
    console.error("Native inference initialization failed:", error);
    runtimeStatus = "Native inference initialization failed";
    elements.runtimeStatus.textContent = runtimeStatus;
    elements.runtimeDetails.textContent = error instanceof Error ? error.message : String(error);
    elements.deviceCard.textContent = "The native inference runtime could not initialize. Check the build and runtime logs.";
    showToast("The on-device inference runtime could not initialize.");
  }
}

async function chooseSavedModel(): Promise<void> {
  if (!state.selectedModelId) return;
  const installed = installedModels.find((model) => model.id === state.selectedModelId);
  if (installed) await loadModel(state.selectedModelId);
}

function renderModels(): void {
  elements.modelSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a model";
  elements.modelSelect.append(placeholder);
  for (const model of MODEL_CATALOG) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name;
    elements.modelSelect.append(option);
  }
  elements.modelSelect.value = state.selectedModelId;
  elements.modelList.replaceChildren();
  for (const model of MODEL_CATALOG) elements.modelList.append(renderModelCard(model));
}

function renderModelCard(model: MobileModel): HTMLElement {
  const card = document.createElement("article");
  card.className = "model-card";
  const head = document.createElement("div");
  head.className = "model-card-head";
  const titleGroup = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = model.name;
  const subtitle = document.createElement("p");
  subtitle.className = "model-subtitle";
  subtitle.textContent = `${model.quantization} · ${model.contextLength.toLocaleString()} context`;
  titleGroup.append(title, subtitle);
  const size = document.createElement("span");
  size.className = "model-size";
  size.textContent = formatBytes(model.sizeBytes);
  head.append(titleGroup, size);

  const metadata = document.createElement("div");
  metadata.className = "model-meta";
  for (const [label, value] of [
    ["LICENSE", model.license],
    ["RECOMMENDED RAM", `${formatBytes(model.minimumRecommendedRamBytes)}*`],
    ["FREE STORAGE", `${formatBytes(model.recommendedFreeStorageBytes)}*`],
  ]) {
    const item = document.createElement("div");
    const caption = document.createElement("span");
    caption.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    item.append(caption, content);
    metadata.append(item);
  }

  const note = document.createElement("p");
  note.className = "model-note";
  const totalMemory = runtime?.totalMemoryBytes;
  const availableStorage = runtime?.availableStorageBytes;
  const insufficientMemory = totalMemory !== undefined && totalMemory < model.minimumRecommendedRamBytes;
  const insufficientStorage = availableStorage !== undefined && availableStorage < model.recommendedFreeStorageBytes;
  note.textContent = [
    model.notes,
    insufficientMemory ? "This device is below the model's recommended RAM; download and load are disabled." : "",
    insufficientStorage ? "There is not enough free storage for the recommended installation space." : "",
  ].filter(Boolean).join(" ");
  const actions = document.createElement("div");
  actions.className = "model-actions";
  const installed = installedModels.find((item) => item.id === model.id);
  const progress = progressByModel.get(model.id);
  if (progress?.state === "downloading" || progress?.state === "verifying") {
    const progressTrack = document.createElement("div");
    progressTrack.className = "progress-track";
    const fill = document.createElement("span");
    const percent = progress.totalBytes > 0
      ? Math.min(100, (progress.receivedBytes / progress.totalBytes) * 100)
      : 0;
    fill.style.width = `${percent}%`;
    progressTrack.append(fill);
    const label = document.createElement("span");
    label.textContent = progress.state === "verifying" ? "Verifying…" : `${percent.toFixed(0)}%`;
    actions.append(progressTrack, label);
  } else if (installed) {
    const load = document.createElement("button");
    load.className = "secondary-button";
    load.textContent = loadedModel && state.selectedModelId === model.id ? "Loaded" : "Load model";
    load.disabled = !mobilePlatform.isNative() || insufficientMemory ||
      Boolean(loadedModel && state.selectedModelId === model.id);
    load.addEventListener("click", () => void loadModel(model.id).catch(showError));
    const remove = document.createElement("button");
    remove.className = "secondary-button";
    remove.textContent = "Delete";
    remove.disabled = loadedModel?.id === model.id;
    remove.addEventListener("click", () => void deleteModel(model.id).catch(showError));
    actions.append(load, remove);
  } else {
    const download = document.createElement("button");
    download.className = "secondary-button";
    download.textContent = "Download model";
    download.disabled = !mobilePlatform.isNative() || insufficientMemory || insufficientStorage;
    download.addEventListener("click", () => void downloadModel(model).catch(showError));
    actions.append(download);
  }
  card.append(head, metadata, note, actions);
  return card;
}

async function downloadModel(model: MobileModel): Promise<void> {
  await mobilePlatform.inference.downloadModel({
    id: model.id,
    url: modelDownloadUrl(model),
    filename: model.filename,
    sha256: model.sha256,
    sizeBytes: model.sizeBytes,
  });
  installedModels = (await mobilePlatform.inference.listModels()).models;
  progressByModel.delete(model.id);
  renderModels();
  showToast(`${model.name} downloaded and verified.`);
}

async function deleteModel(id: string): Promise<void> {
  await mobilePlatform.inference.deleteModel({ id });
  installedModels = (await mobilePlatform.inference.listModels()).models;
  renderModels();
  showToast("Model deleted from this device.");
}

async function loadModel(id: string): Promise<void> {
  if (generating) return;
  const model = MODEL_CATALOG.find((item) => item.id === id);
  if (!model || !installedModels.some((item) => item.id === id)) {
    showToast("Download and verify the model before loading it.");
    return;
  }
  if (loadedModel) {
    await mobilePlatform.inference.unloadModel();
    loadedModel = null;
  }
  elements.modelStatus.textContent = "Loading model…";
  syncChatControls();
  try {
    loadedModel = await mobilePlatform.inference.loadModel({
      id,
      contextLength: Math.min(model.contextLength, state.contextLength),
      threads: Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1)),
    });
    state.selectedModelId = id;
    saveState();
    setRuntimeInfo({
      ...(runtime ?? { runtime: "llama.cpp", version: "unknown", commit: "unknown", gpuAvailable: false }),
      backend: loadedModel.backend,
      gpuAvailable: loadedModel.backend !== "CPU",
    });
    renderModels();
    showToast(`${model.name} is ready.`);
  } catch (error) {
    loadedModel = null;
    throw error;
  } finally {
    syncChatControls();
  }
}

async function generateMessage(): Promise<void> {
  const text = elements.messageInput.value.trim();
  if (!text || !loadedModel || generating) return;
  const conversation = currentConversation();
  conversation.messages.push({ role: "user", content: text });
  persistConversation();
  elements.messageInput.value = "";
  resizeInput();
  generating = true;
  syncChatControls();
  try {
    await Haptics.impact({ style: ImpactStyle.Light });
  } catch {
    // Haptics may be unavailable on simulators and some devices.
  }
  const assistant: Message = { role: "assistant", content: "" };
  conversation.messages.push(assistant);
  renderConversation();
  const row = renderMessage(assistant, conversation.messages.length - 1);
  row.querySelector(".message-content")?.classList.add("typing");
  elements.messages.append(row);
  let finalText = "";
  let streamFrame = 0;
  const tokenListener = await mobilePlatform.inference.addListener("token", (event) => {
    finalText += event.token;
    assistant.content = finalText;
    if (!streamFrame) {
      streamFrame = requestAnimationFrame(() => {
        streamFrame = 0;
        const content = row.querySelector(".message-content");
        if (content) {
          content.classList.remove("typing");
          content.textContent = finalText;
        }
        elements.messagesScroll.scrollTop = elements.messagesScroll.scrollHeight;
      });
    }
  });
  try {
    const model = MODEL_CATALOG.find((item) => item.id === state.selectedModelId);
    if (!model) throw new Error("The selected model is not in the mobile catalog.");
    const result = await mobilePlatform.inference.generate({
      prompt: formatPrompt(conversation.messages.slice(0, -1), model),
      maxTokens: Math.min(1024, state.contextLength),
      temperature: state.temperature,
    });
    finalText = result.text || finalText;
    assistant.content = finalText;
    if (!finalText.trim() && !result.cancelled) throw new Error("The model returned an empty response.");
  } catch (error) {
    if (!assistant.content) conversation.messages.pop();
    throw error;
  } finally {
    if (streamFrame) cancelAnimationFrame(streamFrame);
    await tokenListener.remove();
    generating = false;
    if (assistant.content) persistConversation();
    renderConversation();
    syncChatControls();
  }
}

async function regenerateLast(): Promise<void> {
  if (generating || !activeConversation) return;
  const messages = activeConversation.messages;
  if (messages.at(-1)?.role === "assistant") messages.pop();
  if (messages.at(-1)?.role !== "user") return;
  const question = messages.pop()?.content;
  if (!question) return;
  elements.messageInput.value = question;
  await generateMessage();
}

function editMessage(index: number): void {
  if (!activeConversation || generating) return;
  const target = activeConversation.messages[index];
  if (target?.role !== "user") return;
  elements.messageInput.value = target.content;
  activeConversation.messages.splice(index);
  persistConversation();
  renderConversation();
  elements.messageInput.focus();
  resizeInput();
}

function resizeInput(): void {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 180)}px`;
  syncChatControls();
}

function showError(error: unknown): void {
  console.error("Mobile action failed:", error);
  showToast(error instanceof Error ? error.message : String(error));
}

function showView(name: string): void {
  document.querySelectorAll<HTMLElement>(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `${name}View`);
  });
  document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  if (name === "models") renderModels();
  closeSidebar();
}

function closeSidebar(): void {
  elements.sidebar.classList.remove("open");
  document.querySelector(".drawer-scrim")?.classList.remove("open");
}

function bindEvents(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view ?? "chat"));
  });
  byId<HTMLButtonElement>("newChat").addEventListener("click", () => {
    if (generating) return;
    persistConversation();
    activeConversation = null;
    state.currentChatId = null;
    elements.messageInput.value = "";
    renderConversation();
    renderHistory();
    resizeInput();
    showView("chat");
  });
  byId<HTMLButtonElement>("browseModels").addEventListener("click", () => showView("models"));
  byId<HTMLButtonElement>("menuButton").addEventListener("click", () => {
    elements.sidebar.classList.add("open");
    const scrim = document.createElement("button");
    scrim.className = "drawer-scrim open";
    scrim.setAttribute("aria-label", "Close navigation");
    scrim.addEventListener("click", () => {
      scrim.remove();
      closeSidebar();
    });
    document.body.append(scrim);
  });
  elements.historySearch.addEventListener("input", renderHistory);
  elements.messageInput.addEventListener("input", resizeInput);
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void generateMessage().catch(showError);
    }
  });
  elements.sendButton.addEventListener("click", () => void generateMessage().catch(showError));
  elements.stopButton.addEventListener("click", () => {
    if (generating) void mobilePlatform.inference.cancelGeneration().catch(showError);
  });
  elements.modelSelect.addEventListener("change", () => {
    const id = elements.modelSelect.value;
    if (!id) return;
    state.selectedModelId = id;
    saveState();
    if (installedModels.some((model) => model.id === id)) void loadModel(id).catch(showError);
    else {
      showView("models");
      showToast("Download the selected model to this device before loading it.");
    }
  });
  elements.contextSetting.addEventListener("change", () => {
    state.contextLength = Number(elements.contextSetting.value);
    saveState();
  });
  elements.temperatureSetting.addEventListener("input", () => {
    state.temperature = Number(elements.temperatureSetting.value);
    saveState();
  });
  elements.unloadButton.addEventListener("click", () => {
    if (generating) return;
    void mobilePlatform.inference.unloadModel()
      .then(() => {
        loadedModel = null;
        syncChatControls();
        renderModels();
        showToast("Model unloaded; model memory released.");
      })
      .catch(showError);
  });
  byId<HTMLButtonElement>("shareButton").addEventListener("click", () => {
    const content = activeConversation?.messages.map((message) =>
      `${message.role === "user" ? "You" : "Sxarf AI"}: ${message.content}`,
    ).join("\n\n") ?? "";
    if (!content) {
      showToast("There is no conversation to share.");
      return;
    }
    void Share.share({ title: activeConversation?.title ?? "Sxarf AI chat", text: content })
      .catch(showError);
  });
  const resizeViewport = (): void => {
    const height = window.visualViewport?.height ?? window.innerHeight;
    document.documentElement.style.setProperty("--keyboard-height", `${height}px`);
  };
  window.visualViewport?.addEventListener("resize", resizeViewport);
  window.addEventListener("resize", resizeViewport);
  resizeViewport();
}

async function main(): Promise<void> {
  await restoreState();
  activeConversation = state.chats.find((chat) => chat.id === state.currentChatId) ?? null;
  elements.contextSetting.value = String(state.contextLength);
  elements.temperatureSetting.value = String(state.temperature);
  renderModels();
  renderHistory();
  renderConversation();
  bindEvents();
  if (mobilePlatform.isNative()) {
    mobilePlatform.inference.addListener("downloadProgress", setDownloadProgress)
      .catch(showError);
    mobilePlatform.inference.addListener("memoryWarning", (event) => {
      showToast(event.message);
    }).catch(showError);
  }
  await initializeNative();
  syncChatControls();
}

void main().catch(showError);
