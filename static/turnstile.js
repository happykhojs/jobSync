/* Cloudflare Turnstile helper for WorkOwon login (X-Turnstile-Token). */
(function (global) {
  const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  let loading = null;
  const widgets = new Map();

  function loadScript() {
    if (global.turnstile) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SCRIPT;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Couldn't load Cloudflare Turnstile."));
      document.head.appendChild(s);
    });
    return loading;
  }

  async function mount(el, sitekey, onToken) {
    if (!el || !sitekey) return null;
    await loadScript();
    if (widgets.has(el)) {
      try { global.turnstile.remove(widgets.get(el)); } catch {}
      widgets.delete(el);
      el.innerHTML = "";
    }
    el.dataset.token = "";
    const id = global.turnstile.render(el, {
      sitekey,
      theme: "light",
      size: "flexible",
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
      },
    });
    widgets.set(el, id);
    return id;
  }

  function token(el) {
    if (!el) return "";
    const fromWidget = widgets.has(el) && global.turnstile
      ? (global.turnstile.getResponse(widgets.get(el)) || "")
      : "";
    return (fromWidget || el.dataset.token || "").trim();
  }

  function reset(el) {
    if (!el || !widgets.has(el) || !global.turnstile) return;
    el.dataset.token = "";
    try { global.turnstile.reset(widgets.get(el)); } catch {}
  }

  global.JobSyncTurnstile = { mount, token, reset, loadScript };
})(window);
