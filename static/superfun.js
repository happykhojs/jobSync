/* Super Fun: disco sky, recruiter XP/levels, achievements and secret words.
   Builds on Fun Zone (fun.js); the wilder chaos (pranks, takeovers, floods, the dino) lives in chaos.js.
   Listens to "jobsync:*" events from the app; never changes job data. */
(() => {
  const F = window.Fun;
  if (!F) return;
  const KEY = "superFun", STATS = "superFunStats";
  const { el, rand, pick } = F;
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };

  const LEVELS = [
    [0, "Intern Recruiter"], [100, "Junior Recruiter"], [300, "Recruiter"], [600, "Senior Recruiter"],
    [1000, "Talent Wizard 🧙"], [1600, "Hiring Legend 🏆"], [2500, "Job Overlord 👑"], [4000, "Ascended HR Being ✨"],
  ];
  const XP = { posted: 50, improved: 20, saved: 5, skipped: 1 };
  const ACHIEVEMENTS = {
    first: ["🩸", "First Blood", "Posted your first job"],
    ten: ["🔟", "Double Digits", "10 jobs posted"],
    fifty: ["🚀", "Job Machine", "50 jobs posted"],
    combo3: ["🔥", "On Fire", "3 posts in a row"],
    combo5: ["🌋", "Unstoppable", "5 posts in a row"],
    owl: ["🦉", "Night Owl", "Posted a job after 10 pm"],
    bird: ["🐦", "Early Bird", "Posted a job before 8 am"],
    intern: ["🎓", "Intern Hunter", "Posted an internship"],
    ai: ["🤖", "AI Whisperer", "Improved 10 jobs with AI"],
    meow: ["🐈", "Cat Summoner", "Found a secret word"],
    konami: ["🕹️", "Old School", "Entered the Konami code"],
    hero: ["🦸", "Wildlife Hero", "Saved an animal from a hunter"],
    collector: ["🪙", "Coin Collector", "Caught 10 coins with your dino"],
    flood: ["🌊", "Flood Survivor", "Kept working through a flood"],
    pranked: ["🤡", "Pranked", "A button ran away from you"],
  };

  let stats = load(STATS, { xp: 0, posted: 0, improved: 0, unlocked: {}, lastPost: 0, combo: 0 });
  let on = false, disco, ball, hud, timers = [];
  let lastTrail = 0;

  const level = (xp = stats.xp) => {
    let i = 0;
    while (i + 1 < LEVELS.length && xp >= LEVELS[i + 1][0]) i++;
    return { n: i + 1, name: LEVELS[i][1], from: LEVELS[i][0], to: LEVELS[i + 1]?.[0] ?? LEVELS[i][0] + 2000 };
  };

  /* ---------- HUD, combo text, badges, fireworks ---------- */
  function renderHud() {
    if (!hud) return;
    const l = level(), pct = Math.min(100, ((stats.xp - l.from) / (l.to - l.from)) * 100);
    hud.innerHTML = `<div class="lvl"><span>Lv ${l.n} · ${l.name}</span><span>${stats.combo > 1 ? `🔥x${stats.combo}` : ""}</span></div>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="meta"><span>${stats.xp} / ${l.to} XP</span><span>💼 ${stats.posted} posted</span></div>`;
    hud.classList.remove("bump"); void hud.offsetWidth; hud.classList.add("bump");
  }
  function comboText(text) {
    const n = el("sf-combo", text);
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 1300);
  }
  function unlock(id) {
    if (stats.unlocked[id]) return;
    stats.unlocked[id] = Date.now(); save(STATS, stats);
    const [ico, name, desc] = ACHIEVEMENTS[id];
    const n = el("sf-badge", `<span class="ico">${ico}</span><span><small>Achievement unlocked</small><b>${name}</b><small>${desc}</small></span>`);
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 4600);
  }
  function fireworks(times = 3) {
    if (F.reduced) return;
    const colors = ["#ff4500", "#ffd635", "#46d160", "#0079d3", "#ff66ac", "#a855f7"];
    for (let t = 0; t < times; t++) setTimeout(() => {
      const x = rand(innerWidth * 0.15, innerWidth * 0.85), y = rand(innerHeight * 0.15, innerHeight * 0.45), c = pick(colors);
      for (let i = 0; i < 36; i++) {
        const p = el("sf-firework", "", { left: `${x}px`, top: `${y}px`, color: c, background: c });
        const a = (i / 36) * Math.PI * 2, d = rand(70, 150);
        p.style.setProperty("--dx", `${Math.cos(a) * d}px`); p.style.setProperty("--dy", `${Math.sin(a) * d + 40}px`); p.style.setProperty("--rot", "0deg");
        document.body.appendChild(p); setTimeout(() => p.remove(), 1400);
      }
    }, t * 450);
  }

  function addXp(kind, detail = {}) {
    if (!on) return;
    const before = level();
    stats.xp += XP[kind] || 0;
    if (kind === "posted") {
      stats.posted++;
      const now = Date.now();
      stats.combo = now - stats.lastPost < 90_000 ? stats.combo + 1 : 1;
      stats.lastPost = now;
      if (stats.combo > 1) comboText(stats.combo >= 5 ? `MEGA COMBO x${stats.combo}!` : `COMBO x${stats.combo}!`);
      if (stats.posted === 1) unlock("first");
      if (stats.posted === 10) unlock("ten");
      if (stats.posted === 50) unlock("fifty");
      if (stats.combo === 3) unlock("combo3");
      if (stats.combo === 5) unlock("combo5");
      const h = new Date().getHours();
      if (h >= 22 || h < 4) unlock("owl");
      if (h >= 5 && h < 8) unlock("bird");
      if (/intern|trainee|apprentice/i.test(detail.title || "")) unlock("intern");
    }
    if (kind === "improved") { stats.improved += detail.count || 1; if (stats.improved >= 10) unlock("ai"); }
    save(STATS, stats);
    renderHud();
    const after = level();
    if (after.n > before.n) {
      fireworks(4);
      F.banner(`⬆️ LEVEL UP! You're now a ${after.name}`);
    }
  }

  /* ---------- bonus XP from chaos.js (saving animals, catching coins) ---------- */
  function bonus(xp, message) {
    if (!on) return;
    const before = level();
    stats.xp += xp; save(STATS, stats); renderHud();
    if (message) F.banner(message);
    const after = level();
    if (after.n > before.n) { fireworks(4); F.banner(`⬆️ LEVEL UP! You're now a ${after.name}`); }
  }

  /* ---------- sparkle trail ---------- */
  function onMove(e) {
    if (!F.reduced && Date.now() - lastTrail > 45) {
      lastTrail = Date.now();
      const t = el("sf-trail", pick(["✨", "⭐", "💫", "·"]), { left: `${e.clientX}px`, top: `${e.clientY}px` });
      document.body.appendChild(t); setTimeout(() => t.remove(), 800);
    }
  }
  /* ---------- big surprises ---------- */
  const BIG = {
    stampede() { F.banner("🐈🐈🐈 CAT STAMPEDE!"); for (let i = 0; i < 10; i++) setTimeout(() => F.walker(pick(["🐈", "🐈‍⬛", "🐆", "🐅"]), false), i * 250); },
    meteors() {
      F.banner("☄️ Meteor shower!");
      for (let i = 0; i < 16; i++) setTimeout(() => F.spawn(el("sf-meteor", "☄️", { left: `${rand(30, 110)}vw` }), 1700), i * 220);
    },
    fireworks() { F.banner("🎆 Fireworks!"); fireworks(6); },
    money() {
      F.banner("💸 Hiring budget approved!");
      for (let i = 0; i < 30; i++) setTimeout(() => F.spawn(el("fun-flake", pick(["💸", "💰", "🪙", "💵"]), { left: `${rand(0, 100)}vw`, animationDuration: `${rand(3, 6)}s`, "--dx": `${rand(-60, 60)}px` }), 6000), i * 120);
    },
    zoomies() { F.banner("🐕💨 ZOOMIES"); for (let i = 0; i < 3; i++) setTimeout(() => F.flyAcross("🐕", { top: innerHeight - rand(60, 120), dur: 2500, wobble: 30, size: 34 }), i * 600); },
  };

  /* ---------- secret words ---------- */
  const KONAMI = ["arrowup", "arrowup", "arrowdown", "arrowdown", "arrowleft", "arrowright", "arrowleft", "arrowright", "b", "a"];
  let typed = "", keys = [];
  function onKey(e) {
    if (!on || e.target.closest("input, textarea, select, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    keys = [...keys, k].slice(-KONAMI.length);
    if (keys.join() === KONAMI.join()) {
      unlock("konami"); F.banner("🕹️ +30 lives. Do a barrel roll!");
      document.body.classList.add("sf-roll"); setTimeout(() => document.body.classList.remove("sf-roll"), 1200);
      fireworks(3); keys = [];
    }
    if (k.length !== 1) return;
    typed = (typed + k).slice(-10);
    const word = ["meow", "party", "hire", "rain", "boom"].find((w) => typed.endsWith(w));
    if (!word) return;
    typed = "";
    ({ meow: () => { unlock("meow"); BIG.stampede(); }, party: () => { BIG.fireworks(); F.events.balloons(); },
       hire: () => BIG.money(), rain: () => F.events.rain(), boom: () => BIG.meteors() })[word]();
  }

  /* ---------- lifecycle ---------- */
  function start() {
    if (on) return;
    on = true; F.start();
    document.body.classList.add("superfun");
    const back = document.querySelector(".fun-layer");
    disco = el("", `<div class="sf-beam" style="animation-delay:-1s"></div><div class="sf-beam" style="animation-delay:-3s;animation-direction:alternate-reverse"></div>`);
    back.appendChild(disco);
    ball = el("sf-disco", `<div class="string"></div><span class="ball">🪩</span>`);
    document.querySelector("header .brand").appendChild(ball);
    hud = el("sf-hud");
    // HUD lives in the header next to the fun buttons.
    document.getElementById("superFunBtn").after(hud);
    renderHud();
    addEventListener("mousemove", onMove, { passive: true });
    addEventListener("keydown", onKey);
    timers.push(setInterval(() => { if (!document.hidden) pick(Object.values(BIG))(); }, rand(45000, 75000)));
    setTimeout(() => F.banner("🤫 Psst… try typing meow, party, hire or boom"), 9000);
    fireworks(2);
    dispatchEvent(new CustomEvent("superfun:change", { detail: { on: true } }));
  }
  function stop() {
    if (!on) return;
    on = false;
    document.body.classList.remove("superfun");
    [disco, ball, hud].forEach((n) => n?.remove());
    removeEventListener("mousemove", onMove); removeEventListener("keydown", onKey);
    timers.forEach(clearInterval); timers = [];
    dispatchEvent(new CustomEvent("superfun:change", { detail: { on: false } }));
  }

  // Signals from the app (dispatched in index.html).
  addEventListener("jobsync:posted", (e) => addXp("posted", e.detail));
  addEventListener("jobsync:improved", (e) => addXp("improved", e.detail));
  addEventListener("jobsync:saved", () => addXp("saved"));
  addEventListener("jobsync:skipped", () => addXp("skipped"));

  window.SuperFun = {
    enabled: () => on,
    toggle() { on ? stop() : start(); save(KEY, on); return on; },
    stopIfOn() { if (on) { stop(); save(KEY, false); } },
    init() { if (load(KEY, false)) start(); },
    big: BIG, stats: () => stats, unlock, bonus, fireworks,
  };
})();
