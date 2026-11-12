/* Cloudflare Turnstile helper for WorkOwon login (X-Turnstile-Token).
   Mirrors Connect's TurnstileField: always-visible managed widget, retry on failure. */
(function (global) {
  const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  // Same public key as Connect / WorkOwon (NEXT_PUBLIC_TURNSTILE_SITE_KEY).
  const DEFAULT_SITE_KEY = "0x4AAAAAAF8mwjtmsgdq3yaK";
  let loading = null;
  const widgets = new Map();

  function siteKey(override) {
    return String(override || DEFAULT_SITE_KEY).trim();
  }

  function loadScript() {
    if (global.turnstile) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[src*="challenges.cloudflare.com/turnstile"]');
      if (existing) {
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", () => reject(new Error("Couldn't load Cloudflare Turnstile.")));
        if (global.turnstile) resolve();
        return;
      }
      const s = document.createElement("script");
      s.src = SCRIPT;
      s.async = true;
      s.defer = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Couldn't load Cloudflare Turnstile. Disable ad blockers and try again."));
      document.head.appendChild(s);
    }).then(() => waitReady());
    return loading;
  }

  function waitReady() {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      const tick = () => {
        if (global.turnstile && typeof global.turnstile.render === "function") {
          if (typeof global.turnstile.ready === "function") {
            global.turnstile.ready(() => resolve());
          } else {
            resolve();
          }
          return;
        }
        if (Date.now() - start > 10000) {
          reject(new Error("Cloudflare Turnstile timed out loading."));
          return;
        }
        setTimeout(tick, 50);
      };
      tick();
    });
  }

  function showRetry(el, message, retry) {
    el.innerHTML = "";
    el.dataset.token = "";
    const box = document.createElement("div");
    box.style.cssText = "display:flex;flex-direction:column;gap:8px;padding:10px 12px;border:1px solid #fecdca;background:#fef3f2;border-radius:10px;";
    box.setAttribute("role", "alert");
    const p = document.createElement("p");
    p.style.cssText = "margin:0;font-size:12px;color:#b42318;line-height:1.4;";
    p.textContent = message;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Retry verification";
    btn.className = "btn btn-sm";
    btn.style.cssText = "align-self:flex-start;";
    btn.onclick = () => retry();
    box.appendChild(p);
    box.appendChild(btn);
    el.appendChild(box);
  }

  async function mount(el, key, onToken) {
    if (!el) return null;
    const sk = siteKey(key);
    await loadScript();

    const renderWidget = () => {
      if (widgets.has(el)) {
        try { global.turnstile.remove(widgets.get(el)); } catch {}
        widgets.delete(el);
      }
      el.innerHTML = "";
      el.dataset.token = "";
      try {
        const id = global.turnstile.render(el, {
          sitekey: sk,
          theme: "light",
          size: "flexible",
          appearance: "always",
          retry: "auto",
          callback: (token) => {
            el.dataset.token = token || "";
            if (onToken) onToken(token || "");
          },
          "expired-callback": () => {
            el.dataset.token = "";
            if (onToken) onToken("");
          },
          "error-callback": () => {
            el.dataset.token = "";
            if (onToken) onToken("");
            showRetry(
              el,
              "Couldn't load verification. Allow localhost / 127.0.0.1 on the Turnstile widget, disable ad blockers, then retry.",
              () => { mount(el, sk, onToken); },
            );
          },
          "unsupported-callback": () => {
            el.dataset.token = "";
            if (onToken) onToken("");
            showRetry(el, "This browser doesn't support Cloudflare verification.", () => { mount(el, sk, onToken); });
          },
        });
        widgets.set(el, id);
        return id;
      } catch (err) {
        showRetry(
          el,
          (err && err.message) || "Couldn't start Cloudflare verification.",
          () => { mount(el, sk, onToken); },
        );
        throw err;
      }
    };

    return renderWidget();
  }

  function token(el) {
    if (!el) return "";
    const fromWidget = widgets.has(el) && global.turnstile
      ? (global.turnstile.getResponse(widgets.get(el)) || "")
      : "";
    return (fromWidget || el.dataset.token || "").trim();
  }

  function reset(el) {
    if (!el) return;
    el.dataset.token = "";
    if (widgets.has(el) && global.turnstile) {
      try { global.turnstile.reset(widgets.get(el)); return; } catch {}
    }
    // Remount if reset failed (e.g. after error UI replaced the widget).
    const key = el.dataset.sitekey || DEFAULT_SITE_KEY;
    mount(el, key);
  }

  global.JobSyncTurnstile = { mount, token, reset, loadScript, siteKey, DEFAULT_SITE_KEY };
})(window);
