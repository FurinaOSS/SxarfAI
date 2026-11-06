#!/usr/bin/env python3
import sys
import os

MOTION_BLOCK = """<!-- SXARF-MOTION:START — paste right before </body>, after SXARF-UPGRADE:END (or SXARF-PREMIUM:END) -->
<style id="sxarf-motion">
@property --sx-ang { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
:root { --sx-spring: cubic-bezier(.34,1.56,.64,1); --sx-out: cubic-bezier(.16,1,.3,1); }

/* --- empty state title gradient & word reveal --- */
.sx-w {
  display: inline-block; padding-bottom: .08em; margin-right: .26em;
  background: linear-gradient(to top, #cdcdcd, #fff);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
body:not(.anim-off):not(.reduce-motion) .sx-w {
  animation: sxWord .8s var(--sx-out) both;
  animation-delay: calc(var(--w) * 75ms);
}
.empty-state h1 { transition: none; opacity: 1 !important; transform: none !important; }

/* hero-orb mouse magnetic translation with smooth return & smooth position shift when title size changes */
.hero-orb {
  translate: var(--px, 0px) var(--py, 0px);
  transition: translate 0.45s var(--sx-out), margin 0.55s var(--sx-out), transform 0.55s var(--sx-out);
}

/* everything below is skipped when Animations = Off or Reduce motion is on */
body:not(.anim-off):not(.reduce-motion) {
  /* --- messages --- */
  & .message.user { animation: sxUserIn .6s var(--sx-spring) both; transform-origin: 100% 100%; }
  & .message.assistant { animation: sxAsstIn .7s var(--sx-out) both; }
  & .message.assistant .mark { animation: sxPop .6s var(--sx-spring) .12s both; }
  & .message.assistant .message-content > * { animation: sxLine .6s var(--sx-out) both; }
  & .message.assistant .message-content.streaming > * { animation: none; }

  /* --- glowing live caret instead of a blinking bar --- */
  & .message-content.streaming > :last-child::after {
    width: 8px; height: 8px; margin-left: 5px; vertical-align: 1px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 10px var(--accent), 0 0 22px var(--accent-line);
    animation: sxCaret 1.1s ease-in-out infinite;
  }

  /* --- composer: rotating light ring on focus, faster while generating --- */
  & .input-wrapper::before {
    content: ""; position: absolute; inset: 0; z-index: 3; padding: 1.5px; border-radius: inherit; pointer-events: none;
    background: conic-gradient(from var(--sx-ang), transparent 0 55%, var(--accent) 78%, transparent 92%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0);
    opacity: 0; transition: opacity .4s; animation: sxSpin 4s linear infinite;
  }
  & .input-wrapper:focus-within::before { opacity: .9; }
  & .input-wrapper:has(.send-btn.stop)::before { opacity: 1; animation-duration: 1.4s; }
  & #userInput { transition: height .18s var(--sx-out); }

  /* --- send button: magnetic + icon swap --- */
  & .send-btn { transition: transform .35s var(--sx-spring), opacity .2s, background .2s, box-shadow .3s; }
  & .send-btn:not(:disabled):hover { box-shadow: 0 6px 22px var(--accent-line); }
  & .send-btn:not(:disabled) { translate: var(--mx, 0) var(--my, 0); }

  /* --- sidebar items & load-in --- */
  & .history-item.sx-new { animation: sxSlide .55s var(--sx-out) both; animation-delay: calc(var(--i, 0) * 35ms); }
  & .history-item.active::before { animation: sxBar .45s var(--sx-spring) both; transform-origin: center; }
  & .sidebar > * { animation: sxSlide .7s var(--sx-out) both; animation-delay: calc(var(--k, 0) * 70ms); }
  & .chat-header { animation: sxDown .7s var(--sx-out) both; }
  & .input-area { animation: sxUp .8s var(--sx-out) .15s both; }

  /* --- settings: rows cascade in, panes slide --- */
  & .settings-pane:not([hidden]) .setting-row, & .settings-pane:not([hidden]) .group-label { animation: sxUp .5s var(--sx-out) both; animation-delay: calc(var(--r, 0) * 40ms); }
  & .plan-card { animation: sxUp .6s var(--sx-spring) both; animation-delay: calc(var(--r, 0) * 70ms); }
  & .modal { animation: sxModal .45s var(--sx-spring); }
  & .toast.visible { animation: sxToast .5s var(--sx-spring); }

  /* --- chat switch crossfade (View Transitions) --- */
  & .messages { view-transition-name: sx-chat; }
}
::view-transition-old(sx-chat) { animation: sxOut .18s ease both; }
::view-transition-new(sx-chat) { animation: sxIn .38s var(--sx-out) both; }
::view-transition-group(root) { animation: none; }

@keyframes sxUserIn { from { opacity: 0; transform: translate(26px, 18px) scale(.86); filter: blur(4px); } }
@keyframes sxAsstIn { from { opacity: 0; transform: translateY(14px); filter: blur(6px); } }
@keyframes sxLine { from { opacity: 0; transform: translateY(8px); } }
@keyframes sxPop { from { opacity: 0; transform: scale(.3) rotate(-25deg); } }
@keyframes sxCaret { 0%, 100% { transform: scale(.6); opacity: .6; } 50% { transform: scale(1.25); opacity: 1; } }
@keyframes sxSpin { to { --sx-ang: 360deg; } }
@keyframes sxSlide { from { opacity: 0; transform: translateX(-14px); } }
@keyframes sxBar { from { transform: scaleY(0); } }
@keyframes sxDown { from { opacity: 0; transform: translateY(-12px); } }
@keyframes sxUp { from { opacity: 0; transform: translateY(14px); } }
@keyframes sxWord { from { opacity: 0; transform: translateY(18px) scale(.96); filter: blur(8px); } }
@keyframes sxModal { from { opacity: 0; transform: translateY(18px) scale(.94); } }
@keyframes sxToast { from { opacity: 0; transform: translate(-50%, 20px) scale(.9); } }
@keyframes sxOut { to { opacity: 0; transform: translateY(-6px); } }
@keyframes sxIn { from { opacity: 0; transform: translateY(12px); } }
body.sx-idle .input-wrapper::before { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) { .input-wrapper::before, .sx-w { animation: none !important; } }
</style>

<script id="sxarf-motion-js">
(() => {
"use strict";
function boot() {
const $q = (s, r = document) => r.querySelector(s);
const motionOn = () => !document.body.classList.contains("anim-off") && !document.body.classList.contains("reduce-motion");
const full = () => motionOn() && !document.body.classList.contains("anim-subtle");

/* 1. staggered sidebar load-in + settings cascade indices */
[...$q("#sidebar").children].forEach((el, k) => el.style.setProperty("--k", k));
const indexRows = () => document.querySelectorAll(".settings-pane").forEach(p =>
  p.querySelectorAll(".setting-row,.group-label,.plan-card").forEach((el, r) => el.style.setProperty("--r", Math.min(r, 12))));
indexRows();
new MutationObserver(indexRows).observe($q("#settingsModal"), { attributes: true, attributeFilter: ["class"] });

/* 2. only chats that are NEW to the sidebar animate in */
const seen = new Set(); let first = true;
const hist = $q("#chatHistory");
new MutationObserver(() => {
  let i = 0;
  hist.querySelectorAll(".history-item").forEach(el => {
    const key = el.querySelector(".history-title")?.textContent + "|" + el.querySelector(".history-open")?.title;
    if (!seen.has(key)) { seen.add(key); el.style.setProperty("--i", Math.min(i++, 14)); if (full() && (first || i < 2)) el.classList.add("sx-new"); }
  });
  first = false;
}).observe(hist, { childList: true });

/* 3. word-by-word title reveal + random title generator on new chat */
const h = $q("#rotatingTitle");
function splitTitle() {
  if (!h || h.dataset.busy || !h.textContent.trim()) return;
  h.dataset.busy = 1;
  const words = h.textContent.trim().split(/\\s+/);
  h.replaceChildren(...words.map((w, i) => { const s = document.createElement("span"); s.className = "sx-w"; s.style.setProperty("--w", i); s.textContent = w; return s; }));
  h.setAttribute("aria-label", words.join(" "));
  requestAnimationFrame(() => delete h.dataset.busy);
}
if (h) {
  splitTitle();
  new MutationObserver(splitTitle).observe(h, { childList: true });
}

// Hook into startNewChat to randomize title immediately when starting a new chat
const _snc = window.startNewChat;
if (typeof _snc === "function") {
  window.startNewChat = function() {
    if (h && typeof rotatingTitles !== "undefined" && rotatingTitles.length) {
      currentTitleIndex = Math.floor(Math.random() * rotatingTitles.length);
      h.textContent = rotatingTitles[currentTitleIndex];
      delete h.dataset.busy;
      splitTitle();
    }
    return _snc.apply(this, arguments);
  };
}

/* 4. cursor-reactive hero orb magnet (max 37px displacement, smooth spring return to center) */
const empty = $q("#emptyState");
window.addEventListener("pointermove", e => {
  if (!full()) return;
  const orb = $q(".hero-orb");
  if (orb && empty.offsetParent) {
    const r = orb.getBoundingClientRect();
    const currentPx = parseFloat(orb.style.getPropertyValue("--px")) || 0;
    const currentPy = parseFloat(orb.style.getPropertyValue("--py")) || 0;
    
    // Calculate true layout center of orb
    const cx = r.left + r.width / 2 - currentPx;
    const cy = r.top + r.height / 2 - currentPy;
    
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const dist = Math.hypot(dx, dy);
    
    // Magnetize towards mouse within 400px radius, scaling up to max 37px displacement
    const maxPull = 37;
    const pullRadius = 400;
    let pull = 0;
    if (dist < pullRadius) {
      pull = (1 - dist / pullRadius) * maxPull;
    }
    
    const px = dist > 1 ? (dx / dist) * pull : 0;
    const py = dist > 1 ? (dy / dist) * pull : 0;
    
    orb.style.setProperty("--px", px.toFixed(2) + "px");
    orb.style.setProperty("--py", py.toFixed(2) + "px");
  }
  
  const b = $q("#sendBtn");
  if (b) {
    const rb = b.getBoundingClientRect();
    const dxi = e.clientX - (rb.left + rb.width / 2), dyi = e.clientY - (rb.top + rb.height / 2), di = Math.hypot(dxi, dyi);
    if (di < 70 && !b.disabled) { b.style.setProperty("--mx", (dxi * .22).toFixed(2) + "px"); b.style.setProperty("--my", (dyi * .22).toFixed(2) + "px"); }
    else { b.style.setProperty("--mx", "0px"); b.style.setProperty("--my", "0px"); }
  }
}, { passive: true });

/* 5. smooth crossfade when switching chats */
const _lc = loadChat;
loadChat = function (id) {
  if (full() && document.startViewTransition && !isGenerating) document.startViewTransition(() => _lc(id));
  else _lc(id);
};
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
</script>
<!-- SXARF-MOTION:END -->"""

def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Clean up any previously applied motion block to ensure idempotent updates
    if "<!-- SXARF-MOTION:START" in content and "<!-- SXARF-MOTION:END -->" in content:
        start_idx = content.find("<!-- SXARF-MOTION:START")
        end_idx = content.find("<!-- SXARF-MOTION:END -->") + len("<!-- SXARF-MOTION:END -->")
        content = content[:start_idx] + content[end_idx:]

    inserted = False
    for marker in ["<!-- SXARF-UPGRADE:END -->", "<!-- SXARF-PREMIUM:END -->"]:
        if marker in content:
            parts = content.split(marker, 1)
            content = parts[0] + marker + "\n" + MOTION_BLOCK + "\n" + parts[1]
            inserted = True
            print(f"Successfully patched after '{marker}' in '{filepath}'.")
            break

    if not inserted:
        if "</body>" in content:
            parts = content.rsplit("</body>", 1)
            content = parts[0] + "\n" + MOTION_BLOCK + "\n</body>" + parts[1]
            inserted = True
            print(f"Successfully patched right before </body> in '{filepath}'.")
        else:
            content += "\n" + MOTION_BLOCK + "\n"
            print(f"Successfully appended patch to the end of '{filepath}'.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    main()