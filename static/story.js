/* Super Fun story mode: while Super Fun is on, a story is always playing. Episodes (war, love,
   politics, tsunami, sunny days, rain, interviews, aliens, heists, dragons) are acted out by emoji
   actors on the grass with narration, speech bubbles, weather and sound. Purely decorative. */
(() => {
  const F = window.Fun, S = window.SuperFun;
  if (!F || !S) return;
  const { el, rand, pick } = F;
  const sound = () => window.Chaos?.sound;
  const CANCEL = Symbol("cancel");
  let on = false, run = 0, episode = 0, caption, sky, cast = new Set(), forced = null;

  /* ================= stage helpers ================= */
  const front = () => document.querySelector(".fun-front");
  const W = (p) => innerWidth * p;  // horizontal position as a fraction of the screen
  const sfx = (name, ...a) => sound()?.[name]?.(...a);

  function director(token) {
    const alive = () => on && token === run;
    const wait = (ms) => new Promise((res, rej) => setTimeout(() => (alive() ? res() : rej(CANCEL)), ms));
    // Each episode tracks its own nodes, so an interrupted episode never cleans up the next one's actors.
    const mine = new Set();
    const track = (n) => { cast.add(n); mine.add(n); return n; };
    const cleanup = () => { mine.forEach((n) => { n.remove(); cast.delete(n); }); mine.clear(); };

    function actor(emoji, x, { size, flip = false } = {}) {
      const n = track(el(`st-actor ${flip ? "flip" : ""}`, `<span class="bod">${emoji}</span>`, size ? { fontSize: `${size}px` } : {}));
      n.style.transform = `translateX(${x}px)`;
      front()?.appendChild(n);
      const a = {
        x, n,
        async move(to, ms = 2000) {
          n.classList.add("walking");
          n.classList.toggle("flip", to > a.x);  // emoji face left; flip to walk right
          const anim = n.animate([{ transform: `translateX(${a.x}px)` }, { transform: `translateX(${to}px)` }], { duration: ms, easing: "ease-in-out", fill: "forwards" });
          a.x = to;
          // Walks are often fired without await, so a cancelled walk just stops instead of throwing.
          try { await wait(ms); } catch { return; }
          anim.commitStyles?.(); anim.cancel(); n.style.transform = `translateX(${to}px)`;
          n.classList.remove("walking");
        },
        say(text, ms = 2200) {
          n.querySelector(".fun-bubble")?.remove();
          const b = el("fun-bubble", text); n.appendChild(b);
          setTimeout(() => b.remove(), ms);
        },
        face(right) { n.classList.toggle("flip", right); },
        become(emoji) { n.querySelector(".bod").textContent = emoji; },
        fall() { n.classList.add("fallen"); },
        rise() { n.classList.remove("fallen"); },
        jump() { n.animate([{ translate: "0 0" }, { translate: "0 -40px" }, { translate: "0 0" }], { duration: 450 }); },
        leave() { n.remove(); cast.delete(n); mine.delete(n); },
      };
      return a;
    }
    function prop(emoji, x, size = 54) {
      const n = track(el("st-prop", emoji, { fontSize: `${size}px`, transform: `translateX(${x}px)` }));
      front()?.appendChild(n);
      return { n, swap: (e) => { n.textContent = e; }, remove: () => { n.remove(); cast.delete(n); mine.delete(n); } };
    }
    // Something flying in an arc between two points (arrows, votes, cannonballs, hearts).
    function fly(emoji, x1, x2, { arc = 120, ms = 900, y = innerHeight - 60, size = 28 } = {}) {
      const n = track(el("st-fly", emoji, { fontSize: `${size}px` }));
      front()?.appendChild(n);
      const frames = [];
      for (let i = 0; i <= 10; i++) frames.push({ transform: `translate(${x1 + (x2 - x1) * i / 10}px, ${y - Math.sin(Math.PI * i / 10) * arc}px)` });
      n.animate(frames, { duration: ms, easing: "linear" });
      setTimeout(() => { n.remove(); cast.delete(n); }, ms);
    }
    function burst(x, emoji = "💥", count = 1) {
      for (let i = 0; i < count; i++) {
        const n = track(el("sf-boom", emoji, { left: `${x + rand(-20, 20)}px`, top: `${innerHeight - 60 + rand(-20, 10)}px`, fontSize: "48px" }));
        document.body.appendChild(n); setTimeout(() => { n.remove(); cast.delete(n); }, 800);
      }
    }
    function hearts(x, count = 6) {
      for (let i = 0; i < count; i++) setTimeout(() => fly(pick(["💕", "💖", "💗", "❤️"]), x, x + rand(-60, 60), { arc: rand(80, 160), ms: 1400, size: 22 }), i * 150);
    }
    function weather(mood) { if (sky) sky.className = `st-sky ${mood || ""}`; }
    let rainEl = null;
    function rain(onOff) {
      if (onOff && !rainEl) {
        rainEl = track(el("st-rain"));
        for (let i = 0; i < 60; i++) rainEl.appendChild(el("", "", { left: `${rand(0, 105)}vw`, animationDuration: `${rand(0.6, 1)}s`, animationDelay: `-${rand(0, 1)}s` }));
        document.body.appendChild(rainEl); sfx("rainStart");
      } else if (!onOff && rainEl) { rainEl.remove(); cast.delete(rainEl); rainEl = null; sfx("rainStop"); }
    }
    function flash() { const f = el("sf-flash"); document.body.appendChild(f); setTimeout(() => f.remove(), 500); sfx("thunder"); }
    return { alive, wait, actor, prop, fly, burst, hearts, weather, rain, flash, cleanup };
  }

  function narrate(title, text) {
    if (!caption) return;
    caption.classList.add("swap");
    setTimeout(() => { caption.innerHTML = `<b>📖 Ep ${episode} · ${title}</b> — ${text}`; caption.classList.remove("swap"); }, 250);
  }

  /* ================= episodes ================= */
  const L = 0.12, R = 0.88;  // stage edges
  const EPISODES = {
    async war(d, T) {
      d.weather("war"); narrate(T, "Two kingdoms, one last slice of pizza 🍕");
      const castleL = d.prop("🏰", W(0.03), 60), castleR = d.prop("🏯", W(0.92), 60), pizza = d.prop("🍕", W(0.5), 34);
      const left = [d.actor("🤺", W(0.06)), d.actor("💂", W(0.02)), d.actor("🏇", W(-0.03))];
      const right = [d.actor("🥷", W(0.94)), d.actor("🧌", W(0.98)), d.actor("🏹", W(1.02))];
      await Promise.all([...left.map((a, i) => a.move(W(0.2 + i * 0.06), 2600)), ...right.map((a, i) => a.move(W(0.8 - i * 0.06), 2600))]);
      left[0].say("That pizza is OURS! ⚔️"); await d.wait(1400); right[0].say("Over my dead crust! 🗡️"); await d.wait(1500);
      narrate(T, "The battle begins!"); sfx("roar");
      for (let i = 0; i < 6; i++) {
        d.fly(pick(["➶", "🏹", "💣", "🪨"]), W(0.25), W(0.7), { arc: 180 }); d.fly(pick(["➶", "💣", "🔥"]), W(0.75), W(0.3), { arc: 160 });
        await d.wait(450); if (i % 2) { d.burst(W(rand(0.3, 0.7))); sfx("boom"); }
      }
      left[2].fall(); right[2].fall(); sfx("oops"); await d.wait(900);
      narrate(T, "Then a dove arrived with a better idea 🕊️");
      d.fly("🕊️", W(0), W(1), { arc: 60, ms: 3000, y: innerHeight - 160, size: 32 }); await d.wait(1600);
      left[0].move(W(0.46), 1500); await right[0].move(W(0.54), 1500);
      left[0].say("Share it? 🤝"); await d.wait(1200); right[0].say("Half-half 🍕🍕"); sfx("cheer");
      pizza.swap("🤝"); left[2].rise(); right[2].rise(); d.hearts(W(0.5), 4); await d.wait(2500);
      narrate(T, "…and the Pizza Treaty lasted forever. Mostly."); await d.wait(2500);
      castleL.remove(); castleR.remove();
    },

    async love(d, T) {
      d.weather("love"); narrate(T, "Two strangers. One coffee machine ☕");
      const coffee = d.prop("☕", W(0.5), 40);
      const a = d.actor("🧑", W(L)), b = d.actor("👩", W(R));
      await Promise.all([a.move(W(0.44), 3000), b.move(W(0.56), 3000)]);
      a.face(true); b.face(false);
      a.say("Oh! Sorry, after you 😳"); await d.wait(1500); b.say("No no, after YOU 🙈"); await d.wait(1500);
      narrate(T, "Their hands touched the same cup…"); sfx("kiss"); d.hearts(W(0.5), 8); await d.wait(2000);
      coffee.swap("💐"); narrate(T, "Six months later…"); await d.wait(1600);
      const church = d.prop("💒", W(0.5), 64); coffee.remove();
      a.become("🤵"); b.become("👰"); sfx("fanfare");
      F.celebrate(W(0.5), innerHeight - 120); await d.wait(2200);
      narrate(T, "And then came a tiny new teammate 👶");
      d.fly("🎈", W(0.9), W(0.52), { arc: 220, ms: 2200, y: innerHeight - 90 });
      await d.wait(2200); const baby = d.actor("👶", W(0.5), { size: 28 }); baby.say("Goo goo (hire me) 🍼"); sfx("tweet");
      await d.wait(2600); church.remove();
    },

    async politics(d, T) {
      d.weather("sunny"); narrate(T, "Election day in Jobland 🗳️");
      const box = d.prop("🗳️", W(0.5), 48), micL = d.prop("🎤", W(0.24), 30), micR = d.prop("🎤", W(0.74), 30);
      const c1 = d.actor("🧑‍💼", W(0.2)), c2 = d.actor("👩‍💼", W(0.8));
      c1.face(true); c2.face(false);
      const crowd = [d.actor("🧑", W(0.4)), d.actor("👵", W(0.45)), d.actor("👨‍🦱", W(0.55)), d.actor("🧕", W(0.6))];
      const promises = [
        [c1, "Free coffee for all! ☕"], [c2, "4-day work week! 📅"], [c1, "Unlimited snacks! 🍩"],
        [c2, "Remote work forever! 🏠"], [c1, "…and a pony 🐴"], [c2, "Bigger salaries! 💸"],
      ];
      for (const [who, line] of promises) { who.say(line, 1800); sfx("cheer"); await d.wait(1700); }
      narrate(T, "The people vote…");
      for (const v of crowd) { d.fly("📄", v.x, W(0.5), { arc: 90, ms: 800 }); await d.wait(400); }
      await d.wait(900); sfx("whistle");
      const winner = Math.random() < 0.5 ? c1 : c2, loser = winner === c1 ? c2 : c1;
      narrate(T, `${winner === c1 ? "🧑‍💼" : "👩‍💼"} wins by 3 votes!`); winner.say("Thank you, Jobland! 🎉"); winner.jump();
      F.celebrate(winner.x, innerHeight - 120); await d.wait(1800);
      loser.say("RECOUNT!!! 😤"); await d.wait(1500);
      narrate(T, "The protest begins ✊");
      crowd.forEach((c) => c.become(pick(["🪧", "✊", "📢"])));
      await Promise.all(crowd.map((c) => c.move(c.x + W(rand(-0.1, 0.1)), 1500)));
      await d.wait(1800); box.remove(); micL.remove(); micR.remove();
    },

    async tsunami(d, T) {
      d.weather("sunny"); narrate(T, "A perfect beach day ⛱️");
      const umb = d.prop("⛱️", W(0.35), 56), castle = d.prop("🏖️", W(0.6), 44);
      const p = [d.actor("🧘", W(0.3)), d.actor("🏊", W(0.5)), d.actor("🧒", W(0.62)), d.actor("🏄", W(0.15))];
      p[0].say("Ahh, no emails 😌"); await d.wait(2200);
      narrate(T, "Wait… why is the sea going backwards?"); document.body.classList.add("sf-shake"); setTimeout(() => document.body.classList.remove("sf-shake"), 1400);
      sfx("thunder"); await d.wait(1500);
      p.forEach((a) => a.say(pick(["RUN!! 😱", "WAVE!!!", "MY LAPTOP! 💻"]), 1500));
      await Promise.all(p.slice(0, 3).map((a) => a.move(W(1.1), 1600)));
      narrate(T, "🌊 TSUNAMI!");
      const wave = el("st-wave", "🌊<br>🌊<br>🌊<br>🌊<br>🌊"); cast.add(wave); document.body.appendChild(wave);
      wave.animate([{ transform: "translateX(-75vw)" }, { transform: "translateX(110vw)" }], { duration: 4200, easing: "ease-in" });
      sfx("whoosh"); sfx("splash");
      p[3].say("COWABUNGA 🤙"); p[3].move(W(1.1), 4000);
      await d.wait(4300); wave.remove(); cast.delete(wave); umb.remove(); castle.remove();
      narrate(T, "Everyone's okay. Time to rebuild together 💪");
      const builders = [d.actor("👷", W(L)), d.actor("👷‍♀️", W(R)), d.actor("🚜", W(-0.05))];
      await Promise.all([builders[0].move(W(0.4), 2000), builders[1].move(W(0.6), 2000), builders[2].move(W(0.25), 2400)]);
      const site = d.prop("🏗️", W(0.5), 56); await d.wait(1800); site.swap("🏠"); sfx("fanfare");
      builders[0].say("Good as new! 🏠"); await d.wait(2200); site.remove();
    },

    async sunny(d, T) {
      d.weather("sunny"); narrate(T, "Sunday in the park ☀️");
      const basket = d.prop("🧺", W(0.3), 38), tree = d.prop("🌳", W(0.7), 70);
      const fam = [d.actor("👨", W(0.27)), d.actor("👩", W(0.33)), d.actor("🐕", W(0.4))];
      const kid = d.actor("🧒", W(0.5)); kid.say("Look, my kite! 🪁");
      d.fly("🪁", W(0.5), W(0.8), { arc: 300, ms: 4000, y: innerHeight - 120, size: 34 }); await d.wait(2000);
      narrate(T, "The ice-cream truck arrives 🍦"); sfx("tweet");
      const truck = d.actor("🚚", W(1.05)); await truck.move(W(0.6), 2000); truck.say("Ice cream! 🍦");
      kid.become("🍦"); await d.wait(1200); kid.become("🧒"); kid.say("Best. Day. Ever. 😋");
      fam[2].say("Woof! Throw the ball! ⚽"); d.fly("⚽", W(0.27), W(0.6), { arc: 140, ms: 1200 });
      await fam[2].move(W(0.6), 1200); await fam[2].move(W(0.3), 1200);
      narrate(T, "The sun sets slowly 🌇"); d.weather("dusk"); await d.wait(2600);
      basket.remove(); tree.remove(); truck.leave();
    },

    async rainy(d, T) {
      d.weather("rain"); narrate(T, "Dark clouds roll in ⛈️"); d.flash();
      d.rain(true); await d.wait(1000);
      const a = d.actor("🚶", W(L)), b = d.actor("🚶‍♀️", W(R)), kid = d.actor("🧒", W(0.5)), frog = d.actor("🐸", W(0.42), { size: 28 });
      a.say("No umbrella?! 😩"); a.move(W(0.35), 2500); await b.move(W(0.65), 2500);
      a.become("☂️"); b.become("☂️"); narrate(T, "Umbrellas up!");
      kid.say("PUDDLES!!! 🤩"); for (let i = 0; i < 3; i++) { kid.jump(); sfx("splash"); await d.wait(600); }
      frog.say("Best weather ever 🐸"); await d.wait(1600); d.flash();
      narrate(T, "Then the clouds part…"); await d.wait(1200); d.rain(false); d.weather("sunny");
      const bow = el("fun-rainbow"); cast.add(bow); document.querySelector(".fun-layer")?.appendChild(bow); setTimeout(() => { bow.remove(); cast.delete(bow); }, 9000);
      kid.say("A RAINBOW 🌈"); sfx("fanfare"); await d.wait(3000);
    },

    async interview(d, T) {
      d.weather(""); narrate(T, "A candidate walks into an office 🏢");
      const office = d.prop("🏢", W(0.62), 66), desk = d.prop("🪑", W(0.55), 34);
      const boss = d.actor("🧐", W(0.58)), cand = d.actor("🧑‍💻", W(L));
      await cand.move(W(0.48), 2600); cand.face(true); boss.face(false);
      const qa = [
        [boss, "Where do you see yourself in 5 years?"], [cand, "In your chair 😎"],
        [boss, "Biggest weakness?"], [cand, "Honesty."], [boss, "I don't think that's a weakness."], [cand, "I don't care what you think."],
      ];
      for (const [who, line] of qa) { who.say(line, 1900); await d.wait(1900); }
      narrate(T, "Awkward silence… 🦗"); sfx("tweet"); await d.wait(1600);
      boss.say("…YOU'RE HIRED! 💼"); sfx("fanfare"); cand.jump(); F.celebrate(W(0.5), innerHeight - 120);
      await d.wait(1600); narrate(T, "Every job you post is someone's story. Keep posting! 🚀"); await d.wait(2600);
      office.remove(); desk.remove();
    },

    async aliens(d, T) {
      d.weather("night"); narrate(T, "A strange light in the sky… 🛸");
      F.flyAcross("🛸", { top: innerHeight - 220, dur: 2500, wobble: 8, size: 46 }); await d.wait(1500);
      const ship = d.prop("🛸", W(0.5), 60); sfx("whoosh"); await d.wait(800);
      const alien = d.actor("👽", W(0.5)); alien.say("Take me to your recruiter 👽"); await d.wait(2000);
      const hr = d.actor("🧑‍💼", W(R)); await hr.move(W(0.6), 2000); hr.face(false);
      hr.say("We have openings! Remote OK? 🌍"); await d.wait(1800);
      alien.say("Is Mars remote enough? 🔴"); await d.wait(1800); hr.say("…Benefits include oxygen."); await d.wait(1800);
      alien.say("DEAL 🤝"); sfx("fanfare"); d.hearts(W(0.55), 3);
      narrate(T, "Our first intergalactic hire 🚀"); await d.wait(1800);
      alien.leave(); ship.n.animate([{ transform: `translateX(${W(0.5)}px)` }, { transform: `translate(${W(0.5)}px, -100vh)` }], { duration: 1500, fill: "forwards" });
      await d.wait(1500); ship.remove(); d.weather("");
    },

    async heist(d, T) {
      d.weather("night"); narrate(T, "Midnight at the Bank of Jobs 🏦");
      const bank = d.prop("🏦", W(0.62), 64), loot = d.prop("💰", W(0.56), 34);
      const thief = d.actor("🦹", W(L)); await thief.move(W(0.5), 3000);
      thief.say("Shhh… 🤫"); await d.wait(1400); loot.remove(); thief.become("🦹"); thief.say("Got the bonuses! 💰");
      narrate(T, "🚨 The alarm goes off!"); sfx("siren", 5);
      const cop = d.actor("👮", W(1.05)), car = d.actor("🚓", W(1.15));
      thief.move(W(-0.1), 3200); cop.move(W(0.05), 3000); await car.move(W(0.1), 3000);
      narrate(T, "…and the chase continues off-screen 🏃💨"); await d.wait(1000);
      const t2 = d.actor("🦹", W(-0.08)), c2 = d.actor("👮", W(-0.15));
      t2.move(W(1.1), 3500); await c2.move(W(1.1), 3700);
      narrate(T, "Caught! The bonuses go back to the employees 💸"); sfx("cheer"); await d.wait(2400); bank.remove();
    },

    async dragon(d, T) {
      d.weather("dusk"); narrate(T, "A dragon guards the tower 🐉");
      const tower = d.prop("🏰", W(0.75), 70), princess = d.actor("👸", W(0.75)), dragon = d.actor("🐉", W(0.62), { size: 56 });
      const knight = d.actor("🤺", W(L)); knight.say("I shall rescue the princess! ⚔️");
      await knight.move(W(0.45), 2600); dragon.say("ROOOAR 🔥"); sfx("roar");
      for (let i = 0; i < 3; i++) { d.fly("🔥", W(0.6), W(0.46), { arc: 30, ms: 500 }); await d.wait(350); }
      knight.become("🫠"); knight.fall(); narrate(T, "The knight did not go as planned…"); await d.wait(1800);
      princess.say("Ugh. Fine. I'll do it myself 💅"); await princess.move(W(0.66), 1500);
      princess.become("🦸‍♀️"); sfx("boom"); d.burst(W(0.63), "💥", 2);
      dragon.become("🐲"); dragon.say("…can we be friends? 🥺"); await d.wait(1800);
      narrate(T, "The dragon became the kingdom's best HR manager 🐲💼"); dragon.become("🐲"); sfx("fanfare");
      knight.rise(); knight.become("🤺"); d.hearts(W(0.64), 4); await d.wait(2800); tower.remove();
    },
  };
  const TITLES = {
    war: "The Great Pizza War", love: "Love at the Coffee Machine", politics: "Election Day", tsunami: "The Big Wave",
    sunny: "A Sunny Sunday", rainy: "Rainy Day Blues", interview: "The Interview", aliens: "Close Encounters of the Hiring Kind",
    heist: "The Bonus Heist", dragon: "The Princess and the Dragon",
  };

  /* ================= the endless show ================= */
  async function show(token) {
    let queue = [];
    while (on && token === run) {
      if (!queue.length) queue = Object.keys(EPISODES).sort(() => Math.random() - 0.5);
      const key = forced || queue.shift();
      forced = null;
      episode++;
      const d = director(token);
      try {
        await EPISODES[key](d, TITLES[key]);
        await d.wait(1500);
      } catch (e) {
        if (e !== CANCEL) console.warn("story episode failed:", e);
      } finally {
        if (token === run) { d.rain(false); d.weather(""); }
        d.cleanup();
      }
    }
  }

  function start() {
    if (on) return;
    on = true; run++;
    caption = el("st-caption", "📖 The story begins…");
    document.body.appendChild(caption);
    sky = el("st-sky"); document.querySelector(".fun-layer")?.appendChild(sky);
    if (!F.reduced) setTimeout(() => show(run), 1200);
  }
  function stop() {
    if (!on) return;
    on = false; run++;
    cast.forEach((n) => n.remove()); cast.clear();
    caption?.remove(); sky?.remove(); caption = sky = null;
    sound()?.rainStop?.();
  }

  addEventListener("superfun:change", (e) => (e.detail.on ? start() : stop()));
  if (S.enabled()) start();
  window.Story = {
    episodes: Object.keys(EPISODES),
    // Jump to a specific episode; the endless show continues after it.
    play(key) {
      if (!on || !EPISODES[key]) return;
      forced = key; run++;
      cast.forEach((n) => n.remove()); cast.clear();
      show(run);
    },
  };
})();
