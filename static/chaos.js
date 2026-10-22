/* Super Fun chaos: anything can happen. Button pranks, giant animals, a train through the middle,
   hunts, cavemen, floods, falling petals and synth sounds. The playable dino lives in game.js.
   Ground rules: a pranked button always comes back and still does its job; only takeovers and the
   train pause clicks (for ~3-4s); the Fun Zone / Super Fun / sound toggles and the login box are never pranked. */
(() => {
  const F = window.Fun, S = window.SuperFun;
  if (!F || !S) return;
  const { el, rand, pick } = F;
  const MUTE_KEY = "sfMuted";
  let on = false, timers = [], muteBtn;

  /* ================= sound (synthesised with Web Audio, no files) ================= */
  const Sound = (() => {
    let ctx, master, noiseBuf, rainNode;
    let muted = (() => { try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; } })();
    function init() {
      if (ctx) { ctx.resume?.(); return; }
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      ctx = new AC(); master = ctx.createGain(); master.gain.value = muted ? 0 : 0.5; master.connect(ctx.destination);
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    const ok = () => ctx && !muted && ctx.state !== "closed";
    function tone(type, f1, f2, dur, vol = 0.3, delay = 0) {
      if (!ok()) return;
      const t = ctx.currentTime + delay, o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type; o.frequency.setValueAtTime(f1, t); o.frequency.exponentialRampToValueAtTime(Math.max(f2, 1), t + dur);
      g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
      o.connect(g).connect(master); o.start(t); o.stop(t + dur + 0.05);
    }
    function noise(dur, { type = "lowpass", freq = 800, vol = 0.4, delay = 0, loop = false } = {}) {
      if (!ok()) return null;
      const t = ctx.currentTime + delay, src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
      src.buffer = noiseBuf; src.loop = loop; f.type = type; f.frequency.value = freq;
      g.gain.setValueAtTime(vol, t); if (!loop) g.gain.exponentialRampToValueAtTime(0.001, t + dur);
      src.connect(f).connect(g).connect(master); src.start(t); if (!loop) src.stop(t + dur + 0.05);
      return { src, g };
    }
    return {
      init,
      get muted() { return muted; },
      toggle() {
        muted = !muted; try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch {}
        if (master) master.gain.value = muted ? 0 : 0.5;
        if (muted) this.rainStop();
        return muted;
      },
      pop() { noise(0.35, { type: "bandpass", freq: 900, vol: 0.7 }); tone("sine", 160, 40, 0.35, 0.6); },
      boom() { noise(1.2, { freq: 400, vol: 0.9 }); tone("sine", 90, 30, 1, 0.7); },
      tweet() { [0, 0.16, 0.32].forEach((d) => tone("sine", 2200, 3600, 0.12, 0.18, d)); },
      roar() {
        if (!ok()) return;
        const t = ctx.currentTime, o = ctx.createOscillator(), lfo = ctx.createOscillator(), lg = ctx.createGain(), f = ctx.createBiquadFilter(), g = ctx.createGain();
        o.type = "sawtooth"; o.frequency.setValueAtTime(120, t); o.frequency.exponentialRampToValueAtTime(55, t + 1.6);
        lfo.frequency.value = 28; lg.gain.value = 18; lfo.connect(lg).connect(o.frequency);
        f.type = "lowpass"; f.frequency.value = 700; g.gain.setValueAtTime(0.001, t); g.gain.exponentialRampToValueAtTime(0.6, t + 0.15); g.gain.exponentialRampToValueAtTime(0.001, t + 1.8);
        o.connect(f).connect(g).connect(master); o.start(t); lfo.start(t); o.stop(t + 1.9); lfo.stop(t + 1.9);
        noise(1.6, { freq: 500, vol: 0.35 });
      },
      whistle() { [0, 0.55].forEach((d) => { tone("sine", 523, 520, 0.45, 0.22, d); tone("sine", 659, 655, 0.45, 0.18, d); tone("sine", 784, 780, 0.45, 0.12, d); }); },
      chug(times = 12) { for (let i = 0; i < times; i++) noise(0.12, { freq: 300, vol: 0.35, delay: i * 0.28 }); },
      thunder() { noise(2.5, { freq: 220, vol: 0.9 }); },
      splash() { noise(0.6, { type: "highpass", freq: 1500, vol: 0.4 }); },
      coin() { tone("square", 988, 990, 0.08, 0.15); tone("square", 1319, 1320, 0.25, 0.15, 0.08); },
      oops() { tone("triangle", 600, 200, 0.4, 0.3); },
      jump() { tone("square", 330, 660, 0.14, 0.08); },
      chomp() { noise(0.12, { type: "bandpass", freq: 600, vol: 0.6 }); noise(0.1, { type: "bandpass", freq: 500, vol: 0.5, delay: 0.14 }); },
      fire() { noise(0.6, { type: "bandpass", freq: 1200, vol: 0.4 }); tone("sawtooth", 200, 90, 0.5, 0.08); },
      hit() { tone("square", 220, 80, 0.12, 0.2); noise(0.08, { freq: 1500, vol: 0.3 }); },
      hurt() { tone("sawtooth", 420, 160, 0.3, 0.2); },
      cheer() { noise(1.6, { type: "bandpass", freq: 1400, vol: 0.35 }); noise(1.2, { type: "bandpass", freq: 2600, vol: 0.2, delay: 0.2 }); },
      kiss() { tone("sine", 900, 1700, 0.12, 0.2); },
      siren(times = 4) { for (let i = 0; i < times; i++) { tone("sawtooth", 700, 700, 0.3, 0.07, i * 0.6); tone("sawtooth", 950, 950, 0.3, 0.07, i * 0.6 + 0.3); } },
      fanfare() { [523, 659, 784, 1047].forEach((f, i) => tone("triangle", f, f, i === 3 ? 0.6 : 0.16, 0.2, i * 0.15)); },
      whoosh() { noise(2.2, { freq: 600, vol: 0.6 }); noise(2.2, { type: "highpass", freq: 2500, vol: 0.25, delay: 0.3 }); },
      rainStart() { if (!rainNode) rainNode = noise(0, { type: "highpass", freq: 1200, vol: 0.12, loop: true }); },
      rainStop() { if (rainNode) { try { rainNode.src.stop(); } catch {} rainNode = null; } },
      speak(text) {
        if (muted || !window.speechSynthesis) return;
        const u = new SpeechSynthesisUtterance(text); u.pitch = 0.4; u.rate = 0.9; speechSynthesis.speak(u);
      },
    };
  })();

  const front = () => document.querySelector(".fun-front");
  const back = () => document.querySelector(".fun-layer");
  const busyOverlay = () => document.querySelector(".sf-takeover, .sf-crossing");

  /* ================= button pranks ================= */
  let lastPrank = 0, bypass = false;
  const PRANK_CHANCE = 0.18, PRANK_COOLDOWN = 15000;
  const SAFE = "#funBtn, #superFunBtn, .sf-mute, #loginModal *, .rich-tools *, #logoutBtn, #loginBtn";

  function onClickCapture(e) {
    if (!on || bypass) return;
    const btn = e.target.closest?.("button.btn");
    if (!btn || btn.disabled || btn.matches(SAFE) || busyOverlay()) return;
    if (Date.now() - lastPrank < PRANK_COOLDOWN || Math.random() > PRANK_CHANCE) return;
    lastPrank = Date.now();
    e.preventDefault(); e.stopImmediatePropagation();
    prank(btn);
  }

  function prank(btn) {
    const r = btn.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const clone = btn.cloneNode(true);
    clone.removeAttribute("id"); clone.classList.add("sf-prank-clone");
    Object.assign(clone.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    document.body.appendChild(clone);
    btn.style.visibility = "hidden";
    const kind = pick(["blast", "bird", "poof", "spin"]);
    let returnAfter = 1300;
    if (kind === "blast") {
      Sound.boom();
      clone.animate([{ transform: "scale(1)" }, { transform: "scale(1.3) rotate(8deg)", opacity: 0 }], { duration: 250, fill: "forwards" });
      const b = el("sf-boom", "💥", { left: `${cx}px`, top: `${cy}px` }); document.body.appendChild(b); setTimeout(() => b.remove(), 800);
      F.burst(cx, cy, () => el("fun-confetti", "", { background: pick(["#ff4500", "#ffd635", "#1a1a1b", "#ff8717"]) }), 40, 180);
      document.body.classList.add("sf-shake"); setTimeout(() => document.body.classList.remove("sf-shake"), 600);
    } else if (kind === "bird") {
      Sound.tweet(); returnAfter = 1800;
      clone.animate([{ transform: "scale(1)" }, { transform: "scale(0)", opacity: 0 }], { duration: 300, fill: "forwards" });
      const bird = el("sf-bird", "🐦", { left: `${cx}px`, top: `${cy}px` }); document.body.appendChild(bird);
      const tx = rand(-200, 200) + (cx > innerWidth / 2 ? 400 : -400), ty = -cy - 80, frames = [];
      for (let i = 0; i <= 12; i++) frames.push({ transform: `translate(calc(-50% + ${tx * i / 12}px), calc(-50% + ${ty * i / 12 + Math.sin(i * 1.4) * 18}px)) scaleX(${tx > 0 ? -1 : 1})` });
      bird.animate(frames, { duration: 1700, easing: "ease-in" }); setTimeout(() => bird.remove(), 1700);
    } else if (kind === "poof") {
      Sound.pop();
      clone.animate([{ filter: "blur(0)", opacity: 1 }, { filter: "blur(8px)", opacity: 0, transform: "scale(1.4)" }], { duration: 400, fill: "forwards" });
      const p = el("sf-boom", "💨", { left: `${cx}px`, top: `${cy}px` }); document.body.appendChild(p); setTimeout(() => p.remove(), 800);
    } else {
      Sound.oops();
      clone.animate([{ transform: "rotate(0) scale(1)" }, { transform: "rotate(720deg) scale(0)" }], { duration: 900, easing: "ease-in", fill: "forwards" });
      const hole = el("sf-boom", "🕳️", { left: `${cx}px`, top: `${cy}px`, animation: "none", fontSize: "40px" }); document.body.appendChild(hole); setTimeout(() => hole.remove(), 1100);
    }
    S.unlock("pranked");
    setTimeout(() => {
      clone.remove();
      btn.style.visibility = "";
      btn.classList.remove("sf-return"); void btn.offsetWidth; btn.classList.add("sf-return");
      // The prank is only a delay: the original click still happens.
      bypass = true; try { btn.click(); } finally { bypass = false; }
    }, returnAfter);
  }

  /* ================= giant animal takeover (pauses clicks ~2.6s) ================= */
  const GIANTS = [["🦖", "RAAAWR!"], ["🐘", "PAWOOO!"], ["🐋", "*whale noises*"], ["🦍", "HIRE ME!"], ["🐻", "GRRR…"], ["🦁", "ROAR!"], ["🐙", "BLUB BLUB"]];
  function takeover() {
    if (busyOverlay()) return;
    const [emoji, line] = pick(GIANTS);
    const o = el("sf-takeover", `<div class="giant">${emoji}</div><div class="label">${line}</div>`);
    document.body.appendChild(o);
    Sound.roar();
    document.body.classList.add("sf-shake"); setTimeout(() => document.body.classList.remove("sf-shake"), 1500);
    setTimeout(() => o.remove(), 2650);
  }

  /* ================= train through the middle (pauses clicks ~4s) ================= */
  function train() {
    if (busyOverlay()) return;
    const c = el("sf-crossing", `<div class="sf-track"></div><div class="sf-train">🚂🚃🚃🚃🚋🚃</div><div class="label">🚧 Work paused · train crossing</div>`);
    document.body.appendChild(c);
    const t = c.querySelector(".sf-train"), w = t.getBoundingClientRect().width;
    t.animate([{ transform: `translateX(${innerWidth}px)` }, { transform: `translateX(${-w}px)` }], { duration: 4000, easing: "linear" });
    Sound.whistle(); setTimeout(() => Sound.chug(12), 300);
    for (let i = 0; i < 8; i++) setTimeout(() => {
      const head = t.getBoundingClientRect();
      const s = el("sf-smoke", "💨", { left: `${head.left + 30}px`, top: `${head.top - 40}px` }); c.appendChild(s); setTimeout(() => s.remove(), 1400);
    }, 200 + i * 420);
    setTimeout(() => c.remove(), 4100);
  }

  /* ================= hunts at the bottom ================= */
  const runners = new Set();
  function runner(html, { toRight, dur, offset = 0, big = false, role = "" }) {
    const f = front(); if (!f) return null;
    const n = el(`sf-runner ${toRight ? "flip" : ""} ${big ? "big" : ""}`, `<span class="bod">${html}</span>`);
    n.dataset.role = role;
    f.appendChild(n); runners.add(n);
    const dist = innerWidth + 400, from = toRight ? -200 - offset : innerWidth + 200 + offset, to = toRight ? from + dist + offset : from - dist - offset;
    n._anim = n.animate([{ transform: `translateX(${from}px)` }, { transform: `translateX(${to}px)` }], { duration: dur, easing: "linear" });
    n._anim.onfinish = () => { n.remove(); runners.delete(n); };
    return n;
  }
  const CHASES = [["🐅", "🦌"], ["🦁", "🦓"], ["🦊", "🐇"], ["🐈", "🐁"], ["🐊", "🦆"], ["🐺", "🐑"], ["🐆", "🐐"]];
  const caveman = () => `<span class="sf-caveman"><span class="club">🦴</span>🧔🏻</span>`;
  function hunt() {
    const toRight = Math.random() < 0.5, dur = rand(6500, 9000);
    if (Math.random() < 0.35) {
      // cavemen!
      if (Math.random() < 0.6) {
        F.banner("🦣 The cavemen are hunting!"); Sound.speak("ooga booga");
        runner("🦣", { toRight, dur, offset: 0, big: true, role: "prey" });
        for (let i = 1; i <= 3; i++) runner(caveman(), { toRight, dur, offset: 120 + i * 60, role: "predator" });
      } else {
        F.banner("😱 The mammoth fights back!"); Sound.roar();
        for (let i = 0; i < 3; i++) runner(caveman(), { toRight, dur: dur * 0.9, offset: i * 55, role: "prey" });
        runner("🦣", { toRight, dur: dur * 0.9, offset: 260, big: true, role: "predator" });
      }
      return;
    }
    const [pred, prey] = pick(CHASES);
    runner(prey, { toRight, dur, offset: 0, role: "prey" });
    runner(pred, { toRight, dur, offset: 150, role: "predator" });
  }

  /* ================= flood ================= */
  let flooding = false, lastFlood = 0;
  function flood() {
    if (flooding || Date.now() - lastFlood < 180000) return hunt();
    flooding = true; lastFlood = Date.now();
    F.banner("🌧️ It won't stop raining…");
    const storm = el("sf-storm");
    for (let i = 0; i < 90; i++) storm.appendChild(el("", "", { left: `${rand(0, 105)}vw`, animationDuration: `${rand(0.5, 0.9)}s`, animationDelay: `-${rand(0, 1)}s` }));
    document.body.appendChild(storm);
    const water = el("sf-water", `<span class="duck">🦆</span>`);
    ["🐟", "🐠", "🐡", "🦈", "🐙", "🐢"].forEach((f, i) =>
      water.appendChild(el("swimmer", f, { top: `${20 + i * 12}%`, animationDuration: `${rand(9, 18)}s`, animationDelay: `-${rand(0, 10)}s` })));
    document.body.appendChild(water);
    Sound.rainStart(); Sound.thunder();
    const flash = () => { const f = el("sf-flash"); document.body.appendChild(f); setTimeout(() => f.remove(), 500); Sound.thunder(); };
    setTimeout(flash, 3000); setTimeout(flash, 11000);
    requestAnimationFrame(() => { water.style.height = "52vh"; });   // rises over ~9s
    setTimeout(() => { F.banner("🌊 FLOOD! Your jobs are underwater!"); Sound.splash(); }, 6000);
    setTimeout(() => { water.style.height = "0"; storm.remove(); Sound.rainStop(); F.banner("☀️ The water is draining…"); }, 20000);
    setTimeout(() => { water.remove(); flooding = false; S.unlock("flood"); }, 29500);
  }

  /* ================= falling petals ================= */
  function petals(count = 14) {
    for (let i = 0; i < count; i++) setTimeout(() => {
      F.spawn(el("sf-petal", pick(["🌸", "🌸", "💮", "🌺"]), { left: `${rand(0, 100)}vw`, animationDuration: `${rand(7, 12)}s`, "--dx": `${rand(-120, 160)}px`, "--rot": `${rand(180, 720)}deg` }), 12000);
    }, i * 350);
  }

  /* ================= scheduler ================= */
  const CHAOS = [
    [hunt, 30], [petals, 15], [takeover, 10], [train, 9], [flood, 6],
    [() => S.big.money(), 8], [() => F.events.rain(), 6], [() => S.big.stampede(), 8], [() => S.big.zoomies(), 8],
  ];
  function pickWeighted() {
    const total = CHAOS.reduce((a, [, w]) => a + w, 0);
    let r = Math.random() * total;
    for (const [fn, w] of CHAOS) { if ((r -= w) <= 0) return fn; }
    return hunt;
  }
  function loop() {
    const t = setTimeout(() => { if (on && !document.hidden) pickWeighted()(); loop(); }, rand(14000, 30000));
    timers.push(t);
  }

  /* ================= lifecycle ================= */
  function start() {
    if (on) return;
    on = true;
    Sound.init();
    muteBtn = document.createElement("button");
    muteBtn.className = "btn btn-sm sf-mute"; muteBtn.type = "button";
    muteBtn.title = "Sound on/off";
    muteBtn.textContent = Sound.muted ? "🔇" : "🔊";
    muteBtn.onclick = () => { Sound.init(); muteBtn.textContent = Sound.toggle() ? "🔇" : "🔊"; };
    document.getElementById("superFunBtn").after(muteBtn);
    document.addEventListener("click", onClickCapture, true);
    setTimeout(petals, 1000);
    loop();
  }
  function stop() {
    if (!on) return;
    on = false;
    timers.forEach(clearTimeout); timers = [];
    muteBtn?.remove();
    runners.forEach((r) => r.remove()); runners.clear();
    document.querySelectorAll(".sf-takeover, .sf-crossing, .sf-storm, .sf-water, .sf-prank-clone").forEach((n) => n.remove());
    document.querySelectorAll("button.btn").forEach((b) => { if (b.style.visibility === "hidden") b.style.visibility = ""; });
    flooding = false; Sound.rainStop();
    document.removeEventListener("click", onClickCapture, true);
  }

  addEventListener("superfun:change", (e) => (e.detail.on ? start() : stop()));
  if (S.enabled()) start();
  // The dino mini-game (game.js) uses the sound engine and can fight the hunt runners.
  window.Chaos = { takeover, train, hunt, flood, petals, prank: (b) => prank(b), sound: Sound, runners };
})();
