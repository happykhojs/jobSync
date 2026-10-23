/* Super Fun mini-game: you are a dino on the grass. Eat small animals to stay strong, fight bigger
   ones with fire, bites and super powers, and watch out: when you're weak, predators hunt YOU.
   Keys work only when you're not typing and no panel/dialog is open. If you stop playing for a
   minute your dino naps, and hunger and attacks pause, so it never punishes you for doing real work. */
(() => {
  const F = window.Fun, S = window.SuperFun;
  if (!F || !S) return;
  const { el, rand, pick } = F;
  const snd = (name, ...a) => window.Chaos?.sound?.[name]?.(...a);

  const AVATARS = [["🦖", "Rex"], ["🦕", "Bronto"], ["🐉", "Drako"], ["🐲", "Ryu"], ["🦍", "Kong"], ["🐻", "Bruno"], ["🦁", "Leo"]];
  const RANKS = [[0, "Hatchling"], [5, "Hunter"], [15, "Raptor"], [30, "Tyrant"], [60, "Legend"]];
  const MOBS = {
    small: { list: ["🐁", "🐇", "🐿️", "🐓", "🐸", "🦆", "🐀"], hp: 1, speed: 1.2, run: 3.4, size: 26, xp: 2 },
    medium: { list: ["🐗", "🦌", "🐐", "🐑", "🦃"], hp: 3, speed: 1, run: 3, size: 36, xp: 5 },
    predator: { list: ["🐅", "🐊", "🐺", "🦁", "🐻", "🐆"], hp: 6, speed: 1.3, run: 2.7, size: 36, xp: 10, dmg: 9 },
    boss: { list: ["🦖"], hp: 18, speed: 1.1, run: 2.3, size: 80, xp: 50, dmg: 16 },
  };
  const COST = { fire: 12, dash: 20, shield: 30, giant: 50, quake: 40 };
  const IDLE_MS = 60000, WEAK = 40;

  let on = false, raf = 0, last = 0, nextSpawn = 0, playerEl, helpEl, bars = {};
  const keys = new Set();
  const P = { x: 140, y: 0, vy: 0, face: 1, hp: 100, en: 100, avatar: 0, giantUntil: 0, shieldUntil: 0, dashUntil: 0,
    dead: false, lastAction: 0, kills: 0, eaten: 0, tried: new Set([0]), dashHit: new Set() };
  let mobs = [], meats = [], fires = [];

  const now = () => performance.now();
  const active = () => now() - P.lastAction < IDLE_MS;
  const giant = () => now() < P.giantUntil;
  const width = () => (giant() ? 92 : 42);
  const rank = () => RANKS.reduce((r, [k, name]) => (P.kills >= k ? name : r), RANKS[0][1]);

  /* ---------- small visual helpers ---------- */
  function pop(text, x, cls = "") {
    const n = el(`gm-pop ${cls}`, text, { left: `${x}px`, bottom: `${80 + (giant() ? 50 : 0)}px` });
    document.body.appendChild(n); setTimeout(() => n.remove(), 900);
  }
  function puff(x, emoji = "💨") {
    const n = el("sf-boom", emoji, { left: `${x}px`, top: `${innerHeight - 50}px`, fontSize: "40px" });
    document.body.appendChild(n); setTimeout(() => n.remove(), 800);
  }

  /* ---------- player ---------- */
  function buildPlayer() {
    playerEl = el("gm-player", `<div class="gm-bars"><span class="name"></span><div class="gm-bar hp"><i></i></div><div class="gm-bar en"><i></i></div></div><span class="bod"></span>`);
    document.body.appendChild(playerEl);
    bars = { name: playerEl.querySelector(".name"), hp: playerEl.querySelector(".hp"), hpI: playerEl.querySelector(".hp i"), enI: playerEl.querySelector(".en i"), bod: playerEl.querySelector(".bod") };
    setAvatar(P.avatar, true);
  }
  function setAvatar(i, quiet = false) {
    P.avatar = i % AVATARS.length;
    bars.bod.textContent = AVATARS[P.avatar][0];
    P.tried.add(P.avatar);
    if (P.tried.size === AVATARS.length) S.unlock("shapeshifter");
    if (!quiet) { F.banner(`🎭 You are now ${AVATARS[P.avatar][1]} ${AVATARS[P.avatar][0]}`); snd("pop"); }
  }
  function hurt(dmg, by) {
    if (P.dead) return;
    if (now() < P.shieldUntil) { pop("BLOCK 🛡️", P.x + 20); snd("hit"); return; }
    P.hp -= dmg; pop(`-${dmg}`, P.x + 20); snd("hurt");
    playerEl.classList.remove("hurt"); void playerEl.offsetWidth; playerEl.classList.add("hurt");
    if (P.hp <= 0) die(by);
  }
  function heal(n, label) {
    P.hp = Math.min(100, P.hp + n); pop(`+${n} ${label || ""}`, P.x + 20, "heal");
  }
  function die(by) {
    P.dead = true; P.hp = 0;
    playerEl.classList.add("dead"); snd("chomp"); snd("roar");
    F.banner(`🍽️ You became lunch for ${by || "a predator"}! Respawning…`);
    S.unlock("lunch");
    mobs.forEach((m) => { m.angry = false; m.dir = m.x < P.x ? -1 : 1; });
    setTimeout(() => {
      if (!on) return;
      Object.assign(P, { dead: false, hp: 70, en: 100, x: innerWidth * 0.15, y: 0, vy: 0, giantUntil: 0 });
      playerEl.classList.remove("dead");
      F.banner(`🥚 ${AVATARS[P.avatar][1]} hatches again! Eat something, quick!`);
    }, 3500);
  }

  /* ---------- creatures ---------- */
  function spawn(kind) {
    const t = MOBS[kind], fromLeft = Math.random() < 0.5;
    const m = { kind, emoji: pick(t.list), hp: t.hp, max: t.hp, x: fromLeft ? -60 : innerWidth + 60, dir: fromLeft ? 1 : -1,
      angry: false, scaredUntil: 0, nextBite: 0, hitUntil: 0 };
    m.el = el(`gm-mob ${kind === "small" ? "small" : ""} ${kind === "boss" ? "boss" : ""}`, `<div class="mhp"><i></i></div><span class="bod">${m.emoji}</span>`);
    m.hpI = m.el.querySelector(".mhp i");
    if (kind === "small") m.el.querySelector(".mhp").remove();
    document.body.appendChild(m.el);
    mobs.push(m);
    if (kind === "boss") { F.banner("👑 A rival T-Rex wants your territory!"); snd("roar"); }
    return m;
  }
  function damage(m, dmg, how) {
    if (m.dead) return;
    m.hp -= dmg; m.hitUntil = now() + 150; snd("hit");
    if (m.kind === "medium") m.scaredUntil = now() + 2500;
    if (m.kind === "predator" || m.kind === "boss") m.angry = true;
    if (m.hp <= 0) kill(m, how);
  }
  function kill(m, how) {
    m.dead = true; m.el.remove();
    P.kills++;
    puff(m.x + 15, how === "fire" ? "🔥" : "💥");
    if (how === "fire") S.unlock("pyro");
    const t = MOBS[m.kind];
    S.bonus(t.xp, m.kind === "boss" ? `👑 You defeated the rival T-Rex! +${t.xp} XP` : null);
    if (m.kind === "boss") { S.unlock("apex"); S.fireworks?.(4); snd("fanfare"); }
    const drops = m.kind === "boss" ? 3 : 1;
    for (let i = 0; i < drops; i++) {
      const meat = { x: m.x + i * 30, value: m.kind === "small" ? 10 : 25, emoji: m.kind === "small" ? "🍗" : "🍖" };
      meat.el = el("gm-meat", meat.emoji, { transform: `translateX(${meat.x}px)` });
      document.body.appendChild(meat.el); meats.push(meat);
      setTimeout(() => { meat.el.remove(); meats = meats.filter((x) => x !== meat); }, 20000);
    }
  }

  /* ---------- powers ---------- */
  function spend(cost) {
    if (P.en < cost) { pop("No energy ⚡", P.x + 20); snd("oops"); return false; }
    P.en -= cost; return true;
  }
  const powers = {
    fire() {
      if (!spend(COST.fire)) return;
      snd("fire");
      for (let i = 0; i < 4; i++) setTimeout(() => {
        const f = { x: P.x + (P.face > 0 ? width() : -10), dir: P.face, travelled: 0, dmg: giant() ? 4 : 2 };
        f.el = el("gm-fire", pick(["🔥", "🔥", "💥"]), { fontSize: `${giant() ? 44 : 26}px`, bottom: `${28 + P.y + (giant() ? 30 : 0)}px` });
        document.body.appendChild(f.el); fires.push(f);
      }, i * 70);
    },
    bite() {
      const reach = giant() ? 110 : 60;
      const target = mobs.filter((m) => !m.dead && Math.sign(m.x - P.x || 1) === P.face && Math.abs(m.x - P.x) < reach)
        .sort((a, b) => Math.abs(a.x - P.x) - Math.abs(b.x - P.x))[0];
      snd("chomp");
      if (!target) { pop("chomp!", P.x + 20); return; }
      if (target.kind === "small") {
        target.dead = true; target.el.remove(); P.eaten++; P.kills++;
        heal(15, "yum"); S.bonus(3);
        if (P.eaten >= 10) S.unlock("glutton");
      } else damage(target, giant() ? 3 : 1.5, "bite");
    },
    dash() { if (spend(COST.dash)) { P.dashUntil = now() + 320; P.dashHit.clear(); snd("whoosh"); } },
    shield() {
      if (!spend(COST.shield)) return;
      P.shieldUntil = now() + 3500; snd("coin");
      const s = el("gm-shield"); playerEl.appendChild(s); setTimeout(() => s.remove(), 3500);
    },
    giant() {
      if (!spend(COST.giant)) return;
      P.giantUntil = now() + 7000; snd("roar"); F.banner(`⬆️ GIANT ${AVATARS[P.avatar][1].toUpperCase()}!`);
    },
    quake() {
      if (P.y > 0 || !spend(COST.quake)) return;
      snd("boom"); document.body.classList.add("sf-shake"); setTimeout(() => document.body.classList.remove("sf-shake"), 700);
      const q = el("gm-quake"); q.style.setProperty("--x", `${(P.x / innerWidth) * 100}%`); document.body.appendChild(q); setTimeout(() => q.remove(), 700);
      const range = giant() ? 460 : 320;
      mobs.forEach((m) => {
        if (m.dead || Math.abs(m.x - P.x) > range) return;
        m.x += Math.sign(m.x - P.x || 1) * 70;
        damage(m, giant() ? 5 : 3, "quake");
      });
    },
    avatar() { setAvatar(P.avatar + 1); },
  };

  /* ---------- keyboard ---------- */
  const KEYMAP = { f: "fire", a: "bite", d: "dash", s: "shield", g: "giant", q: "quake", c: "avatar" };
  function playable(e) {
    return on && !e.metaKey && !e.ctrlKey && !e.altKey
      && !e.target.closest("input, textarea, select, [contenteditable]")
      && !document.querySelector(".drawer.open, .modal.open");
  }
  function onKeyDown(e) {
    if (!playable(e)) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (k === "?") { toggleHelp(); return; }
    const isMove = ["ArrowLeft", "ArrowRight", "ArrowUp"].includes(k);
    if (!isMove && !KEYMAP[k]) return;
    if (isMove) e.preventDefault();  // arrows steer the dino instead of scrolling while Super Fun is on
    if (!active()) F.banner(`👀 ${AVATARS[P.avatar][1]} wakes up!`);
    P.lastAction = now();
    if (P.dead) return;
    if (isMove) {
      keys.add(k);
      if (k === "ArrowUp" && P.y === 0) { P.vy = giant() ? 15 : 13; snd("jump"); }
      return;
    }
    if (!e.repeat) powers[KEYMAP[k]]();
  }
  function onKeyUp(e) { keys.delete(e.key); }

  function toggleHelp(show) {
    if (helpEl && show !== true) { helpEl.remove(); helpEl = null; return; }
    if (helpEl) return;
    helpEl = el("gm-help", `<b>🦖 Dino controls</b><br>
      <kbd>←</kbd><kbd>→</kbd>move · <kbd>↑</kbd>jump<br>
      <kbd>F</kbd>fire breath · <kbd>A</kbd>bite / eat<br>
      <kbd>D</kbd>dash · <kbd>S</kbd>shield · <kbd>G</kbd>giant<br>
      <kbd>Q</kbd>earthquake · <kbd>C</kbd>change avatar<br>
      <span style="color:#c9c9cc">Eat small animals to stay strong. Below ${WEAK}% HP, predators hunt you! <kbd>?</kbd>hide</span>`);
    document.body.appendChild(helpEl);
  }

  /* ---------- main loop ---------- */
  function frame(t) {
    const dt = Math.min(50, t - (last || t)) / 1000; last = t;
    const playing = active();

    // player movement
    if (!P.dead) {
      const dashing = now() < P.dashUntil;
      let vx = (keys.has("ArrowRight") ? 1 : 0) - (keys.has("ArrowLeft") ? 1 : 0);
      if (vx) P.face = vx;
      vx = dashing ? P.face * 16 : vx * (giant() ? 7 : 5.5);
      P.x = Math.max(0, Math.min(innerWidth - width(), P.x + vx));
      P.vy -= 0.8; P.y = Math.max(0, P.y + P.vy); if (P.y === 0) P.vy = 0;
      playerEl.classList.toggle("walking", vx !== 0);
      // energy refills; hunger only while you're actually playing
      P.en = Math.min(100, P.en + 12 * dt);
      if (playing) { P.hp -= 0.8 * dt; if (P.hp <= 0) die("hunger 🦴"); }
    }
    playerEl.style.transform = `translate(${P.x}px, ${-P.y}px)`;
    playerEl.classList.toggle("right", P.face > 0);
    playerEl.classList.toggle("giant", giant());
    playerEl.classList.toggle("sleep", !playing && !P.dead);
    if (!playing && !P.dead && !playerEl.querySelector(".gm-zzz")) playerEl.appendChild(el("gm-zzz", "💤"));
    if (playing) playerEl.querySelector(".gm-zzz")?.remove();
    bars.name.textContent = `${AVATARS[P.avatar][1]} · ${rank()}`;
    bars.hpI.style.width = `${Math.max(0, P.hp)}%`; bars.enI.style.width = `${P.en}%`;
    bars.hp.classList.toggle("low", P.hp < WEAK);

    // spawning (fewer creatures while you're away)
    if (t > nextSpawn) {
      nextSpawn = t + rand(4500, 8500) * (playing ? 1 : 2);
      if (mobs.length < 7) {
        const r = Math.random();
        const kind = r < 0.45 ? "small" : r < 0.7 ? "medium" : r < 0.95 || !playing || mobs.some((m) => m.kind === "boss") ? "predator" : "boss";
        spawn(kind);
      }
    }

    // creatures
    const pw = width();
    for (const m of mobs) {
      if (m.dead) continue;
      const t0 = MOBS[m.kind], dist = (P.x + pw / 2) - (m.x + t0.size / 2), adist = Math.abs(dist);
      let speed = t0.speed, dir = m.dir;
      const hunter = m.kind === "predator" || m.kind === "boss";
      const wantsYou = hunter && !P.dead && playing && (m.angry || P.hp < WEAK);
      if (m.kind === "small" && playing && adist < 170) { dir = -Math.sign(dist) || 1; speed = t0.run; }
      else if (m.kind === "medium" && now() < m.scaredUntil) { dir = -Math.sign(dist) || 1; speed = t0.run; }
      else if (wantsYou && giant() && m.kind !== "boss") { dir = -Math.sign(dist) || 1; speed = t0.run; }  // scared of giants
      else if (wantsYou) {
        dir = Math.sign(dist) || 1; speed = t0.run;
        if (adist < (pw + t0.size) / 2 && P.y < 30 && now() > m.nextBite) { m.nextBite = now() + 900; hurt(t0.dmg, m.emoji); }
      } else if (Math.random() < 0.004) dir = -dir;
      m.dir = dir;
      // dashing through creatures hurts them
      if (now() < P.dashUntil && adist < (pw + t0.size) / 2 && !P.dashHit.has(m)) { P.dashHit.add(m); damage(m, 2, "dash"); }
      if (adist > 2 || !wantsYou) m.x += dir * speed * (dt * 60);
      m.el.style.transform = `translateX(${m.x}px)`;
      m.el.classList.toggle("right", dir > 0);
      m.el.classList.toggle("moving", true);
      m.el.classList.toggle("angry", wantsYou);
      m.el.classList.toggle("hit", now() < m.hitUntil);
      if (m.hpI) m.hpI.style.width = `${(m.hp / m.max) * 100}%`;
      if ((m.x < -160 || m.x > innerWidth + 160) && !wantsYou) { m.dead = true; m.el.remove(); }
    }
    mobs = mobs.filter((m) => !m.dead);

    // fire
    for (const f of fires) {
      f.x += f.dir * 10 * (dt * 60); f.travelled += 10 * (dt * 60);
      f.el.style.transform = `translateX(${f.x}px)`;
      const hit = mobs.find((m) => !m.dead && Math.abs((m.x + MOBS[m.kind].size / 2) - f.x) < MOBS[m.kind].size / 2 + 8);
      if (hit) { damage(hit, f.dmg, "fire"); f.done = true; }
      // fire also scares off the hunters in the background chases
      window.Chaos?.runners?.forEach((r) => {
        if (f.done || r.dataset.role !== "predator") return;
        const b = r.getBoundingClientRect();
        if (f.x > b.left && f.x < b.right) { r.remove(); window.Chaos.runners.delete(r); puff(b.left, "🔥"); S.unlock("hero"); S.bonus(10); f.done = true; }
      });
      if (f.done || f.travelled > (giant() ? 600 : 420)) { f.el.remove(); f.done = true; }
    }
    fires = fires.filter((f) => !f.done);

    // eat meat by walking over it
    for (const meat of meats) {
      if (!P.dead && Math.abs(meat.x - (P.x + pw / 2)) < pw / 2 + 10 && P.y < 20) {
        meat.el.remove(); meat.eaten = true; heal(meat.value, meat.emoji); snd("chomp"); P.eaten++;
        if (P.eaten >= 10) S.unlock("glutton");
      }
    }
    meats = meats.filter((m) => !m.eaten);

    // catch coins from money rain
    document.querySelectorAll(".fun-front .fun-flake").forEach((c) => {
      if (c.dataset.caught || !/[🪙💰💸💵]/u.test(c.textContent)) return;
      const b = c.getBoundingClientRect();
      if (b.bottom > innerHeight - 70 - P.y && b.left < P.x + pw && b.right > P.x) {
        c.dataset.caught = "1"; c.style.visibility = "hidden"; snd("coin"); S.bonus(5);
        P.coins = (P.coins || 0) + 1; if (P.coins >= 10) S.unlock("collector");
      }
    });

    raf = requestAnimationFrame(frame);
  }

  /* ---------- lifecycle ---------- */
  function start() {
    if (on || F.reduced) return;
    on = true; last = 0; nextSpawn = now() + 2500;
    Object.assign(P, { x: innerWidth * 0.12, y: 0, vy: 0, hp: 100, en: 100, dead: false, lastAction: now() });
    buildPlayer();
    addEventListener("keydown", onKeyDown); addEventListener("keyup", onKeyUp);
    // Controls card shows automatically only the first time; afterwards press "?".
    let seen = false;
    try { seen = localStorage.getItem("dinoHelpSeen") === "1"; localStorage.setItem("dinoHelpSeen", "1"); } catch {}
    if (!seen) { toggleHelp(true); setTimeout(() => { if (helpEl) toggleHelp(); }, 9000); }
    setTimeout(() => F.banner(`🦖 You're ${AVATARS[P.avatar][1]}! Eat small animals, fight the big ones. Press ? for controls`), 2000);
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    if (!on) return;
    on = false; cancelAnimationFrame(raf);
    [playerEl, helpEl, ...mobs.map((m) => m.el), ...meats.map((m) => m.el), ...fires.map((f) => f.el)].forEach((n) => n?.remove());
    playerEl = helpEl = null; mobs = []; meats = []; fires = []; keys.clear();
    removeEventListener("keydown", onKeyDown); removeEventListener("keyup", onKeyUp);
  }

  addEventListener("superfun:change", (e) => (e.detail.on ? start() : stop()));
  if (S.enabled()) start();
  window.DinoGame = { state: () => ({ hp: Math.round(P.hp), en: Math.round(P.en), kills: P.kills, eaten: P.eaten, mobs: mobs.map((m) => m.kind), dead: P.dead, avatar: AVATARS[P.avatar][1] }), spawn, powers, P };
})();
