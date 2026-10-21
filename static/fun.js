/* Fun Zone: animals, weather, surprises and memes. Purely decorative: every element sits in a
   click-through layer behind the app, and nothing here touches job data. */
(() => {
  const KEY = "funZone";
  const MAX_ACTIVE = 14;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const rand = (a, b) => a + Math.random() * (b - a);
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const store = {
    get() { try { return localStorage.getItem(KEY) === "on"; } catch { return false; } },
    set(on) { try { localStorage.setItem(KEY, on ? "on" : "off"); } catch {} },
  };

  const WALKERS = ["🐈", "🐈‍⬛", "🐕", "🦮", "🐩", "🦆", "🐢", "🐌", "🐓", "🐖", "🐇", "🦔", "🐿️", "🦙", "🐘", "🦒", "🐧", "🦩"];
  const LINES = [
    "Post that job! 🚀", "Meow, any openings? 🐟", "I'm a fresher, hire me!", "Woof! 3 yrs experience in fetch",
    "Have you tried Improve? ✨", "Quack. Remote only.", "Slow and steady posts the job 🐢", "Is this an internship?",
    "Pune or Bengaluru? 🤔", "Skills: napping, purring", "One more job and then snacks", "Recruiter mode: ON 😎",
  ];
  const STICKERS = ["⭐", "🌈", "🎈", "🍩", "🌵", "🪐", "🎵", "💼", "🍕", "☕", "🧃", "🎯", "🍀", "💡"];
  const FLOWERS = ["🌷", "🌻", "🌼", "🌸", "🌹", "🌿", "🍄", "🌱"];
  const CHEERS = ["Job posted! 🎉", "Another one! 🙌", "Someone's dream job just went live 💼", "Nice! Keep going 🚀", "Hiring heroes 🦸"];

  let layer, front, timers = [], active = 0;

  function el(cls, html, style = {}) {
    const n = document.createElement("div");
    n.className = cls;
    if (html) n.innerHTML = html;
    Object.assign(n.style, style);
    return n;
  }

  // Moving things go in the front layer (over cards, click-through); scenery stays in the back layer.
  function spawn(node, ms, back = false) {
    if (active >= MAX_ACTIVE) return null;
    active++;
    (back ? layer : front).appendChild(node);
    setTimeout(() => { if (node.isConnected) { node.remove(); active--; } }, ms);
    return node;
  }

  /* ---------- scenery (built once) ---------- */
  function scenery() {
    layer.appendChild(el("fun-sun", "🌞"));
    for (let i = 0; i < 4; i++) {
      const c = el("fun-cloud", "☁️", { top: `${rand(60, 300)}px`, animationDuration: `${rand(70, 140)}s`, animationDelay: `-${rand(0, 120)}s`, fontSize: `${rand(60, 110)}px` });
      layer.appendChild(c);
    }
    for (let i = 0; i < 18; i++) {
      // Stickers live in the side margins and lower area, mostly outside the content column.
      const side = Math.random() < 0.5 ? rand(1, 9) : rand(91, 98);
      const s = el("fun-sticker", pick(STICKERS), { left: `${side}vw`, top: `${rand(12, 88)}vh`, animationDelay: `-${rand(0, 6)}s` });
      layer.appendChild(s);
    }
    front.appendChild(el("fun-ground"));
    const count = Math.ceil(window.innerWidth / 70);
    for (let i = 0; i < count; i++) {
      front.appendChild(el("fun-flower", pick(FLOWERS), { left: `${i * 70 + rand(0, 40)}px`, animationDelay: `-${rand(0, 3)}s`, fontSize: `${rand(20, 30)}px` }));
    }
  }

  /* ---------- characters ---------- */
  function walker(emoji = pick(WALKERS), talk = Math.random() < 0.35) {
    const toRight = Math.random() < 0.5;
    const w = el(`fun-walker ${toRight ? "flip" : ""}`, `<span class="bod">${emoji}</span>`);
    const dur = rand(14, 30) * 1000;
    if (!spawn(w, dur)) return;
    const from = toRight ? -80 : window.innerWidth + 80, to = toRight ? window.innerWidth + 80 : -80;
    w.animate([{ transform: `translateX(${from}px)` }, { transform: `translateX(${to}px)` }], { duration: dur, easing: "linear" });
    if (talk) setTimeout(() => {
      const b = el("fun-bubble", pick(LINES));
      w.appendChild(b);
      setTimeout(() => b.remove(), 3500);
    }, rand(2000, dur / 2));
  }

  function flyAcross(emoji, { top = rand(80, 260), dur = rand(8, 14) * 1000, wobble = 20, size = 40, extra = "" } = {}) {
    const toRight = Math.random() < 0.5;
    const f = el("fun-fly", `<span style="display:inline-block;${toRight ? "transform:scaleX(-1)" : ""}">${emoji}</span>${extra}`, { top: `${top}px`, fontSize: `${size}px` });
    if (!spawn(f, dur)) return;
    const from = toRight ? -120 : window.innerWidth + 120, to = toRight ? window.innerWidth + 120 : -120;
    const frames = [];
    for (let i = 0; i <= 10; i++) frames.push({ transform: `translate(${from + (to - from) * i / 10}px, ${Math.sin(i) * wobble}px)` });
    f.animate(frames, { duration: dur, easing: "linear" });
  }

  /* ---------- surprise events ---------- */
  function banner(text) {
    // One banner at a time: a new announcement replaces the previous one.
    front.querySelectorAll(".fun-banner").forEach((b) => { b.remove(); active--; });
    spawn(el("fun-banner", text), 4000);
  }

  const EVENTS = {
    rain() {
      banner("🌧️ Uh oh, it's raining!");
      for (let i = 0; i < 70; i++) setTimeout(() => {
        spawn(el("fun-drop", "", { left: `${rand(0, 100)}vw`, animationDuration: `${rand(0.7, 1.3)}s`, "--dx": "-40px" }), 1400);
      }, i * 120);
      setTimeout(() => walker("☂️", false), 500);
    },
    snow() {
      banner("❄️ Snow day!");
      for (let i = 0; i < 40; i++) setTimeout(() => {
        spawn(el("fun-flake", pick(["❄️", "❅", "❆"]), { left: `${rand(0, 100)}vw`, animationDuration: `${rand(5, 9)}s`, "--dx": `${rand(-80, 80)}px` }), 9000);
      }, i * 180);
    },
    balloons() {
      for (let i = 0; i < 8; i++) setTimeout(() => {
        spawn(el("fun-rise", pick(["🎈", "🎈", "🎈", "🪁"]), { left: `${rand(5, 95)}vw`, animationDuration: `${rand(8, 13)}s`, "--dx": `${rand(-120, 120)}px`, "--rot": `${rand(-30, 30)}deg` }), 13000);
      }, i * 500);
    },
    ufo() {
      banner("🛸 Is that... a recruiter from space?");
      flyAcross("🛸", { top: 110, dur: 12000, wobble: 12, size: 46, extra: '<div class="fun-beam"></div>' });
      setTimeout(() => walker("🐄", false), 300);
    },
    dino() { banner("🦖 RAWR! Deadline incoming!"); walker("🦖", false); setTimeout(() => walker("🏃", false), 900); },
    butterflies() { for (let i = 0; i < 4; i++) setTimeout(() => flyAcross("🦋", { wobble: 40, size: 28, dur: rand(9, 14) * 1000 }), i * 700); },
    birds() { for (let i = 0; i < 5; i++) setTimeout(() => flyAcross(pick(["🐦", "🕊️", "🦅"]), { top: rand(70, 200), wobble: 10, size: 26 }), i * 400); },
    star() {
      for (let i = 0; i < 3; i++) setTimeout(() => spawn(el("fun-star", "", { top: `${rand(60, 240)}px`, left: `${rand(50, 95)}vw` }), 1500), i * 600);
    },
    rainbow() { banner("🌈 Good vibes only"); spawn(el("fun-rainbow"), 9000, true); },
    parade() { banner("🎺 Animal parade!"); ["🐘", "🦒", "🐒", "🦓", "🐪"].forEach((e, i) => setTimeout(() => walker(e, i === 0), i * 1300)); },
    rocket() { spawn(el("fun-rise", "🚀", { left: `${rand(10, 90)}vw`, animationDuration: "6s", fontSize: "46px" }), 6000); },
    ghost() { flyAcross("👻", { top: rand(150, 400), wobble: 30, size: 36, dur: 11000 }); },
  };

  function surprise() { if (!document.hidden) pick(Object.values(EVENTS))(); }

  /* ---------- lifecycle ---------- */
  function start() {
    if (!layer) {
      layer = el("fun-layer");
      front = el("fun-front");
      layer.setAttribute("aria-hidden", "true");
      front.setAttribute("aria-hidden", "true");
      document.body.prepend(layer);
      document.body.appendChild(front);
      scenery();
    }
    document.body.classList.add("fun");
    if (reduced) return;
    const loop = (fn, min, max) => {
      const t = setTimeout(() => { if (!document.hidden) fn(); loop(fn, min, max); }, rand(min, max));
      timers.push(t);
    };
    walker(); setTimeout(() => walker(), 2500);
    loop(() => walker(), 5000, 11000);
    loop(surprise, 25000, 60000);
    setTimeout(surprise, 6000);
  }

  function stop() {
    document.body.classList.remove("fun");
    timers.forEach(clearTimeout); timers = [];
    document.querySelectorAll(".fun-walker,.fun-fly,.fun-drop,.fun-flake,.fun-rise,.fun-star,.fun-rainbow,.fun-banner").forEach((n) => n.remove());
    active = 0;
  }

  /* ---------- celebrations ---------- */
  function burst(x, y, make, count, spread) {
    if (!enabled() || reduced) return;
    for (let i = 0; i < count; i++) {
      const n = make();
      const angle = rand(0, Math.PI * 2), dist = rand(spread * 0.3, spread);
      n.style.left = `${x}px`; n.style.top = `${y}px`;
      n.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
      n.style.setProperty("--dy", `${Math.sin(angle) * dist + 120}px`);
      n.style.setProperty("--rot", `${rand(-540, 540)}deg`);
      document.body.appendChild(n);
      setTimeout(() => n.remove(), 1700);
    }
  }
  const COLORS = ["#ff4500", "#0079d3", "#46d160", "#ffd635", "#ff66ac", "#7193ff"];

  function celebrate(x = window.innerWidth / 2, y = window.innerHeight / 3) {
    burst(x, y, () => el("fun-confetti", "", { background: pick(COLORS) }), 70, 260);
    if (enabled()) { banner(pick(CHEERS)); if (Math.random() < 0.5) walker(pick(["🐈", "🐕", "🦆"]), true); }
  }
  function sparkle(x = window.innerWidth / 2, y = window.innerHeight / 3) {
    burst(x, y, () => el("fun-spark", pick(["✨", "⭐", "💫"])), 14, 120);
  }

  /* ---------- meme loader ---------- */
  let memes = [], memeIndex = 0;
  async function loadMemes() {
    if (memes.length) return memes;
    try { memes = (await (await fetch("/api/memes")).json()).memes || []; } catch { memes = []; }
    return memes;
  }
  function memeHTML(status) {
    return `<div class="meme-card" id="memeCard"><div class="meme-status"><span class="spinner"></span>${status}</div>
      <div id="memeBody"><p class="meme-sub">Finding you a meme…</p></div>
      <div class="meme-actions"><button type="button" class="btn btn-sm" id="nextMeme">Next meme 😂</button></div></div>`;
  }
  async function showMeme() {
    const body = document.getElementById("memeBody"); if (!body) return;
    const list = await loadMemes();
    if (!document.getElementById("memeBody")) return; // search already finished
    if (!list.length) { body.innerHTML = `<p class="meme-title">🐈 No memes right now. Here's a cat instead.</p><div style="font-size:90px">🐈</div>`; return; }
    const m = list[memeIndex++ % list.length];
    const safe = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    body.innerHTML = `<p class="meme-title">${safe(m.title)}</p><img src="${safe(m.url)}" alt="${safe(m.title)}" referrerpolicy="no-referrer">
      <span class="meme-sub">r/${safe(m.subreddit)}</span>`;
  }
  function mountMemes(container, status = "Searching jobs… enjoy a meme meanwhile") {
    container.innerHTML = memeHTML(status);
    document.getElementById("nextMeme").onclick = showMeme;
    showMeme();
  }

  function enabled() { return document.body.classList.contains("fun"); }
  function toggle() { const on = !enabled(); on ? start() : stop(); store.set(on); return on; }

  document.addEventListener("visibilitychange", () => { if (!document.hidden && enabled() && active === 0) walker(); });
  window.Fun = { enabled, toggle, mountMemes, celebrate, sparkle, events: EVENTS, init() { if (store.get()) start(); } };
})();
