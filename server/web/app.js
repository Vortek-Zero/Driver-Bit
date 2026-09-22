/* Painel de teste: só visualiza o estado calculado no backend Python. */
(() => {
  const $ = (id) => document.getElementById(id);
  const els = {
    conn: $("conn"), track: $("track"), marker: $("marker"),
    steer: $("steer"), steer2: $("steer2"), raw: $("raw"), center: $("center"),
    rel: $("rel"), up: $("up"), down: $("down"), upc: $("upc"), downc: $("downc"),
    port: $("port"), transport: $("transport"), msg: $("msg"),
    cfgMax: $("cfg-max"), cfgDz: $("cfg-dz"), cfgSm: $("cfg-sm"),
    capwrap: $("capwrap"), capfill: $("capfill"), captext: $("captext"),
    markL: $("mark-l"), markR: $("mark-r"),
    brakeFill: $("brake-fill"), brakeV: $("brake-v"),
    accelFill: $("accel-fill"), accelV: $("accel-v"),
    clutchFill: $("clutch-fill"), clutchV: $("clutch-v"),
    shup: $("shup"), shdown: $("shdown"), shupc: $("shupc"), shdownc: $("shdownc"),
    mode: $("mode"), hb: $("hb"),
  };
  let capTotal = 2.0, wasCapturing = false;
  const fmt = (v, d = 1) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));

  async function loadConfig() {
    try {
      const r = await fetch("/api/config");
      const c = await r.json();
      els.cfgMax.value = c.max_angle_deg;
      els.cfgDz.value = c.deadzone;
      els.cfgSm.value = c.smoothing;
    } catch { /* backend ainda subindo */ }
  }

  function render(s) {
    els.raw.textContent = fmt(s.raw_angle);
    els.center.textContent = fmt(s.center);
    els.rel.textContent = fmt(s.relative_angle);
    els.steer.textContent = fmt(s.steering, 3);
    els.steer2.textContent = fmt(s.steering, 3);
    els.marker.style.left = `${((Number(s.steering) + 1) / 2 * 100).toFixed(2)}%`;
    els.up.textContent = s.gear_up ? "PRESSIONADO" : "solto";
    els.down.textContent = s.gear_down ? "PRESSIONADO" : "solto";
    els.up.classList.toggle("on", !!s.gear_up);
    els.down.classList.toggle("on", !!s.gear_down);
    els.upc.textContent = `×${s.gear_up_count}`;
    els.downc.textContent = `×${s.gear_down_count}`;
    els.port.textContent = s.port || "—";
    const on = !!s.connected;
    els.conn.textContent = on ? `conectado (${s.port || "?"})` : "desconectado";
    els.brakeFill.style.width = (Number(s.brake || 0) * 100).toFixed(1) + "%";
    els.brakeV.textContent = (Number(s.brake || 0) * 100).toFixed(0) + "%";
    els.accelFill.style.width = (Number(s.accel || 0) * 100).toFixed(1) + "%";
    els.accelV.textContent = (Number(s.accel || 0) * 100).toFixed(0) + "%";
    els.clutchFill.style.width = (Number(s.clutch || 0) * 100).toFixed(1) + "%";
    els.clutchV.textContent = (Number(s.clutch || 0) * 100).toFixed(0) + "%";
    els.shup.textContent = s.shift_up ? "PRESSIONADO" : "solto";
    els.shdown.textContent = s.shift_down ? "PRESSIONADO" : "solto";
    els.shup.classList.toggle("on", !!s.shift_up);
    els.shdown.classList.toggle("on", !!s.shift_down);
    els.shupc.textContent = `×${s.shift_up_count}`;
    els.shdownc.textContent = `×${s.shift_down_count}`;
    els.mode.textContent = s.auto_mode ? "AUTOMÁTICO" : "MANUAL";
    els.mode.classList.toggle("on", !!s.auto_mode);
    els.hb.textContent = s.handbrake ? "PUXADO" : "solto";
    els.hb.classList.toggle("on", !!s.handbrake);
    els.conn.className = "badge " + (on ? "online" : "offline");
    // progresso da captura de centro
    if (s.capture && s.capture.active) {
      wasCapturing = true;
      els.capwrap.hidden = false;
      const pct = Math.min(100, Math.max(0, (1 - s.capture.remaining_s / capTotal) * 100));
      els.capfill.style.width = pct.toFixed(0) + "%";
      els.captext.textContent = `capturando centro… ${s.capture.remaining_s.toFixed(1)}s (${s.capture.samples} amostras) — segure parado`;
    } else {
      els.capwrap.hidden = true;
      if (wasCapturing) {
        wasCapturing = false;
        if (s.last_capture && s.last_capture.ok) {
          els.msg.textContent = `Centro = ${Number(s.last_capture.center).toFixed(1)}° (média de ${s.last_capture.samples} amostras)`;
        } else if (s.last_capture && !s.last_capture.ok) {
          els.msg.textContent = `Captura falhou: ${s.last_capture.error}`;
        }
      }
    }
    // marcas trava-a-trava
    if (s.locks) {
      els.markL.textContent = s.locks.LEFT !== undefined ? Number(s.locks.LEFT).toFixed(0) + "°" : "—";
      els.markR.textContent = s.locks.RIGHT !== undefined ? Number(s.locks.RIGHT).toFixed(0) + "°" : "—";
    }
  }

  async function poll() {
    try {
      const r = await fetch("/api/state");
      render(await r.json());
    } catch { /* tenta de novo no próximo tick */ }
  }

  function connectWS() {
    let ws;
    try {
      ws = new WebSocket(`ws://${location.host}/ws`);
    } catch {
      return connectSSE();
    }
    ws.onopen = () => { els.transport.textContent = "websocket"; };
    ws.onmessage = (ev) => { try { render(JSON.parse(ev.data)); } catch {} };
    ws.onclose = () => connectSSE();
    ws.onerror = () => { try { ws.close(); } catch {} };
  }

  function connectSSE() {
    els.transport.textContent = "sse (fallback)";
    try {
      const es = new EventSource("/events");
      es.onmessage = (ev) => { try { render(JSON.parse(ev.data)); } catch {} };
      es.onerror = () => {
        es.close();
        els.transport.textContent = "polling (fallback)";
        setInterval(poll, 150);
      };
    } catch {
      els.transport.textContent = "polling (fallback)";
      setInterval(poll, 150);
    }
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  $("btn-cal").onclick = async () => {
    try {
      const d = await post("/api/calibrate", { mode: "hold", seconds: 2.0 });
      capTotal = d.duration_s || 2.0;
      els.msg.textContent = "Segure o volante parado no centro…";
    } catch (e) { els.msg.textContent = `Calibração falhou: ${e.message}`; }
  };
  $("btn-capcancel").onclick = () => post("/api/calibrate/cancel").catch(() => {});
  $("btn-lock-l").onclick = async () => {
    try { const d = await post("/api/lock", { side: "LEFT" }); els.msg.textContent = `Esquerda marcada em ${Number(d.angle).toFixed(0)}°`; }
    catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-lock-r").onclick = async () => {
    try { const d = await post("/api/lock", { side: "RIGHT" }); els.msg.textContent = `Direita marcada em ${Number(d.angle).toFixed(0)}°`; }
    catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-lock-go").onclick = async () => {
    try {
      const d = await post("/api/lock/finish");
      els.msg.textContent = `Trava-a-trava OK: centro ${Number(d.center).toFixed(1)}°, curso ±${Number(d.max_angle_deg).toFixed(0)}°`;
      loadConfig();
    } catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-lock-clear").onclick = () => post("/api/lock/clear").catch(() => {});
  $("btn-reset").onclick = async () => { await post("/api/reset"); els.msg.textContent = "Calibração limpa."; };
  $("btn-up").onclick = () => post("/api/gear", { gear: "UP" }).catch((e) => { els.msg.textContent = e.message; });
  $("btn-down").onclick = () => post("/api/gear", { gear: "DOWN" }).catch((e) => { els.msg.textContent = e.message; });
  $("btn-shup").onclick = async () => {
    try {
      const d = await post("/api/shift", { shift: "UP" });
      if (!d.accepted) els.msg.textContent = "SHIFT ignorado (embreagem solta ou modo AUTO)";
    } catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-shdown").onclick = async () => {
    try {
      const d = await post("/api/shift", { shift: "DOWN" });
      if (!d.accepted) els.msg.textContent = "SHIFT ignorado (embreagem solta ou modo AUTO)";
    } catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-mode").onclick = async () => {
    const cur = els.mode.textContent === "AUTOMÁTICO";
    try { await post("/api/mode", { auto: !cur }); }
    catch (e) { els.msg.textContent = e.message; }
  };
  $("btn-hb").onclick = async () => {
    const cur = els.hb.textContent === "PUXADO";
    try { await post("/api/handbrake", { on: !cur }); }
    catch (e) { els.msg.textContent = e.message; }
  };
  $("cfg").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await post("/api/config", {
        max_angle_deg: Number(els.cfgMax.value),
        deadzone: Number(els.cfgDz.value),
        smoothing: Number(els.cfgSm.value),
      });
      els.msg.textContent = "Configuração aplicada.";
    } catch (e) { els.msg.textContent = `Config inválida: ${e.message}`; }
  };

  loadConfig();
  connectWS();
})();
