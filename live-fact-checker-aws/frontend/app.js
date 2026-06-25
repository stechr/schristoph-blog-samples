"use strict";
// Live Fact Checker — minimal vanilla-JS client.
// After Check, the submitted text is rendered as a transcript with each claim highlighted inline
// (grey=identified -> green/red/amber as verdicts resolve). Click a highlight for a detail overlay.
// Auth (PoC): paste a Cognito JWT. Production would use the Cognito Hosted UI / Amplify.

const CONFIG = window.CONFIG || { apiBase: "" };
const MAX_CLAIMS = 30;          // cost guardrail: cap total claims verified per run
const MAX_CONCURRENT = 6;       // bounded parallel verification
const CHUNK_WORDS = 150;        // extract chunk size

const $ = (id) => document.getElementById(id);
const claims = new Map();       // id -> {id, claim, summary, status, verdict, confidence, explanation, sources}
let claimSeq = 0;

// ---------- API helpers ----------
function apiUrl(path) {
  return `${(CONFIG.apiBase || "").replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}
// ---------- auth (Cognito USER_PASSWORD_AUTH + transparent refresh) ----------
const auth = { idToken: "", refreshToken: "", exp: 0, email: "" };

async function cognito(target, body) {
  const r = await fetch(`https://cognito-idp.${CONFIG.region || "us-east-1"}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService." + target },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d.message || d.__type || `Cognito ${r.status}`).replace(/^.*#/, ""));
  return d;
}
function persistAuth() { localStorage.setItem("fc_auth", JSON.stringify({ refreshToken: auth.refreshToken, email: auth.email })); }
function restoreAuth() {
  try { const s = JSON.parse(localStorage.getItem("fc_auth") || "{}"); if (s.refreshToken) { auth.refreshToken = s.refreshToken; auth.email = s.email || ""; } } catch (e) {}
}
async function login(email, password) {
  const d = await cognito("InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", ClientId: CONFIG.clientId, AuthParameters: { USERNAME: email, PASSWORD: password } });
  const r = d.AuthenticationResult;
  auth.idToken = r.IdToken; auth.refreshToken = r.RefreshToken; auth.exp = Date.now() + (r.ExpiresIn || 3600) * 1000; auth.email = email;
  persistAuth();
}
async function refresh() {
  if (!auth.refreshToken) throw new Error("Not signed in");
  const d = await cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: CONFIG.clientId, AuthParameters: { REFRESH_TOKEN: auth.refreshToken } });
  const r = d.AuthenticationResult;
  auth.idToken = r.IdToken; auth.exp = Date.now() + (r.ExpiresIn || 3600) * 1000;   // refresh flow returns no new refresh token
}
async function getToken() {
  if (!auth.idToken && auth.refreshToken) await refresh();
  if (!auth.idToken && !auth.refreshToken) throw new Error("Please sign in.");
  if (Date.now() > auth.exp - 60000) await refresh();   // transparently refresh ~1 min before expiry
  return auth.idToken;
}
function logout() { auth.idToken = ""; auth.refreshToken = ""; auth.exp = 0; auth.email = ""; localStorage.removeItem("fc_auth"); updateAuthUI(); }
function signedIn() { return !!(auth.idToken || auth.refreshToken); }
function updateAuthUI() {
  $("loginRow").classList.toggle("hidden", signedIn());
  $("sessionRow").classList.toggle("hidden", !signedIn());
  $("cardActions").classList.toggle("hidden", !signedIn());
  if (signedIn()) $("who").textContent = "Signed in as " + (auth.email || "user");
}
function context() {
  return { speaker: $("speaker").value.trim(), event: $("event").value.trim(), language: "en" };
}
async function postJSON(path, body) {
  const token = await getToken();
  const resp = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(`${data?.error?.code || resp.status}: ${data?.error?.message || resp.statusText}`);
  return data;
}

// ---------- utils ----------
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function setStatus(msg, kind = "") { $("status").textContent = msg; $("status").className = "status " + kind; }

// ---------- transcript + highlighting ----------
function renderTranscript(text) {
  const t = $("transcript");
  t.textContent = text;                 // single text node; marks get wrapped into it
  $("chips").innerHTML = "";
  $("transcriptPanel").classList.remove("hidden");
  $("statsBar").classList.remove("hidden");
}

// Wrap the first occurrence of claimText (case-insensitive) in a clickable mark. Returns true if
// located inline; if not found, adds a clickable chip instead so the claim is still reachable.
function highlightClaim(id, claimText) {
  const container = $("transcript");
  const re = new RegExp(escapeRegExp(claimText), "i");
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement.classList.contains("claim-mark")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) {
    const m = node.textContent.match(re);
    if (!m) continue;
    const i = m.index;
    const before = node.textContent.slice(0, i);
    const matched = node.textContent.slice(i, i + m[0].length);
    const after = node.textContent.slice(i + m[0].length);
    const mark = document.createElement("mark");
    mark.className = "claim-mark claim-pending";
    mark.dataset.claimId = id;
    mark.textContent = matched;
    const frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    frag.appendChild(mark);
    if (after) frag.appendChild(document.createTextNode(after));
    node.parentNode.replaceChild(frag, node);
    return true;
  }
  // Fallback: chip
  const chip = document.createElement("span");
  chip.className = "chip claim-pending";
  chip.dataset.claimId = id;
  chip.textContent = claimText.length > 60 ? claimText.slice(0, 57) + "…" : claimText;
  $("chips").appendChild(chip);
  return false;
}

function setClaimStatus(id) {
  const c = claims.get(id);
  const v = (c.verdict || "uncertain").toLowerCase();
  const cls = v === "true" ? "claim-true" : v === "false" ? "claim-false" : "claim-uncertain";
  document.querySelectorAll(`mark[data-claim-id="${id}"], .chip[data-claim-id="${id}"]`).forEach((el) => {
    el.classList.remove("claim-pending");
    el.classList.add(cls);
  });
  updateTile(id);
  updateStats();
}

// ---------- claim tiles (one card per claim, below the transcript) ----------
function tileInner(c) {
  const verified = c.status === "verified";
  const v = (c.verdict || "uncertain").toLowerCase();
  const badge = verified ? v.toUpperCase() : "VERIFYING…";
  const conf = (verified && c.confidence) ? `<span class="tile-conf">${Math.round(c.confidence * 100)}%</span>` : "";
  const expl = c.explanation
    ? `<p class="tile-expl">${escapeHtml(c.explanation)}</p>`
    : (verified ? "" : `<p class="tile-expl muted">Verifying…</p>`);
  const srcs = c.sources || [];
  const srcHtml = srcs.length
    ? `<div class="tile-sources"><strong>Sources</strong><ul>` + srcs.map((s) => {
        const date = s.publishedDate ? ` <span class="date">(${escapeHtml(s.publishedDate)})</span>` : "";
        const title = escapeHtml(s.title || s.url || "source");
        return s.url ? `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${title}</a>${date}</li>` : `<li>${title}${date}</li>`;
      }).join("") + "</ul></div>"
    : "";
  return `<div class="tile-head"><span class="tile-badge ${v}">${badge}</span>${conf}</div>` +
    `<blockquote class="tile-claim">${escapeHtml(c.claim)}</blockquote>${expl}${srcHtml}`;
}

function renderTile(id) {
  const c = claims.get(id);
  if (!c || document.getElementById("tile-" + id)) return;
  const tile = document.createElement("div");
  tile.className = "tile claim-pending";
  tile.id = "tile-" + id;
  tile.dataset.claimId = id;
  tile.innerHTML = tileInner(c);
  $("tiles").appendChild(tile);
  $("tilesPanel").classList.remove("hidden");
}

function updateTile(id) {
  const c = claims.get(id);
  const tile = document.getElementById("tile-" + id);
  if (!c || !tile) return;
  const v = (c.verdict || "uncertain").toLowerCase();
  const cls = c.status === "verified"
    ? (v === "true" ? "claim-true" : v === "false" ? "claim-false" : "claim-uncertain")
    : "claim-pending";
  tile.className = "tile " + cls;
  tile.innerHTML = tileInner(c);
}

function updateStats() {
  let t = 0, f = 0, u = 0;
  for (const c of claims.values()) {
    if (c.status !== "verified") continue;
    if (c.verdict === "TRUE") t++; else if (c.verdict === "FALSE") f++; else u++;
  }
  $("statClaims").textContent = claims.size;
  $("statTrue").textContent = t; $("statFalse").textContent = f; $("statUncertain").textContent = u;
}

// ---------- modal ----------
function openModal(id) {
  const c = claims.get(id);
  if (!c) return;
  const v = (c.verdict || "uncertain").toLowerCase();
  $("modalVerdict").className = "modal-verdict " + v;
  $("modalVerdict").textContent = c.status === "verified" ? v.toUpperCase() : "VERIFYING…";
  $("modalClaim").textContent = c.claim;
  $("modalExplanation").textContent = c.explanation || (c.status === "verified" ? "" : "Verification in progress…");
  $("modalConfidence").textContent = c.confidence ? `Confidence: ${Math.round(c.confidence * 100)}%` : "";
  const srcs = c.sources || [];
  $("modalSources").innerHTML = srcs.length
    ? "<strong>Sources</strong><ul>" + srcs.map((s) => {
        const date = s.publishedDate ? ` <span class="date">(${escapeHtml(s.publishedDate)})</span>` : "";
        const title = escapeHtml(s.title || s.url || "source");
        return s.url ? `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${title}</a>${date}</li>` : `<li>${title}${date}</li>`;
      }).join("") + "</ul>"
    : "";
  $("modal").classList.remove("hidden");
}
function closeModal() { $("modal").classList.add("hidden"); }

// ---------- verification pool ----------
function makePool() {
  const queue = [];
  let active = 0;
  const tasks = [];
  async function run(item) {
    try {
      const data = await postJSON("v1/verify", { claim: item.claim, summary: item.summary, context: context() });
      const c = claims.get(item.id);
      Object.assign(c, { status: "verified", verdict: (data.verdict || "UNCERTAIN").toUpperCase(),
        confidence: data.confidence || 0, explanation: data.explanation || "", sources: data.sources || [] });
      setClaimStatus(item.id);
    } catch (err) {
      const c = claims.get(item.id);
      Object.assign(c, { status: "verified", verdict: "UNCERTAIN", explanation: "Error: " + String(err.message || err) });
      setClaimStatus(item.id);
    } finally { active--; pump(); }
  }
  function pump() { while (active < MAX_CONCURRENT && queue.length) { active++; tasks.push(run(queue.shift())); } }
  return {
    add(item) { queue.push(item); pump(); },
    async drain() {
      while (active > 0 || queue.length) { await Promise.allSettled(tasks.slice()); if (active > 0 || queue.length) await new Promise((r) => setTimeout(r, 30)); }
      await Promise.allSettled(tasks);
    },
  };
}

function addClaim(claimText, summary, id) {
  if (claims.size >= MAX_CLAIMS) return null;
  id = id || ("c-" + (++claimSeq));
  claims.set(id, { id, claim: claimText, summary: summary || claimText, status: "pending", verdict: null, confidence: 0, explanation: "", sources: [] });
  highlightClaim(id, claimText);
  renderTile(id);
  updateStats();
  return id;
}

// ---------- run modes ----------
async function runVerify(text) {
  renderTranscript(text);
  const pool = makePool();
  const id = addClaim(text, "");
  setStatus("Verifying…", "busy");
  pool.add({ id, claim: text, summary: text });
  await pool.drain();
  setStatus("Done.", "ok");
}

async function runExtract(text) {
  renderTranscript(text);
  const words = text.split(/\s+/).filter(Boolean);
  const chunks = [];
  for (let i = 0; i < words.length; i += CHUNK_WORDS) chunks.push(words.slice(i, i + CHUNK_WORDS).join(" "));
  const seen = new Set();
  const pool = makePool();
  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, " ").trim();
  let capped = false;
  let failed = false;

  for (const chunk of chunks) {
    let ext;
    try { ext = await postJSON("v1/extract", { text: chunk, context: context() }); }
    catch (err) { setStatus("Extract error: " + String(err.message || err), "err"); failed = true; break; }
    for (const c of ext.claims || []) {
      const key = norm(c.claim);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      if (claims.size >= MAX_CLAIMS) { capped = true; break; }
      const id = addClaim(c.claim, c.summary);
      if (id) pool.add({ id, claim: c.claim, summary: c.summary });
    }
    setStatus(`Extracting + verifying — ${claims.size} claim(s)…`, "busy");
    if (capped) break;
  }
  await pool.drain();
  if (failed && !claims.size) return;   // keep the surfaced error, don't mask it
  const note = capped ? ` (capped at ${MAX_CLAIMS} to limit cost)` : "";
  setStatus(claims.size ? `Done — ${claims.size} claim(s) verified${note}.` : "No verifiable claims found.", "ok");
}

async function onCheck() {
  const text = $("input").value.trim();
  claims.clear(); claimSeq = 0;
  $("transcript").innerHTML = ""; $("chips").innerHTML = "";
  $("tiles").innerHTML = ""; $("tilesPanel").classList.add("hidden");
  if (!text) { setStatus("Enter a claim or some text.", "err"); return; }
  if (!signedIn()) { setStatus("Please sign in first.", "err"); return; }
  const mode = document.querySelector('input[name="mode"]:checked').value;
  if (mode === "verify") {
    const sentences = (text.match(/[.!?](\s|$)/g) || []).length;
    const wc = text.split(/\s+/).filter(Boolean).length;
    if (sentences > 1 && wc > 40) {
      setStatus('That looks like multiple claims — switch to "Extract claims from text".', "err");
      return;
    }
  }
  $("check").disabled = true; $("export").disabled = true;
  try {
    if (mode === "verify") await runVerify(text); else await runExtract(text);
    if (claims.size) $("export").disabled = false;
  } catch (err) {
    setStatus(String(err.message || err), "err");
  } finally { $("check").disabled = false; }
}

// ---------- export ----------
function exportReport() {
  const rows = [...claims.values()].map((c) => {
    const v = (c.verdict || "uncertain").toLowerCase();
    const srcs = (c.sources || []).map((s) => `<li><a href="${escapeHtml(s.url || "#")}">${escapeHtml(s.title || s.url || "source")}</a>${s.publishedDate ? " (" + escapeHtml(s.publishedDate) + ")" : ""}</li>`).join("");
    return `<div class="r ${v}"><span class="b">${(c.verdict || "PENDING").toUpperCase()}</span> ${c.confidence ? Math.round(c.confidence * 100) + "%" : ""}
      <blockquote>${escapeHtml(c.claim)}</blockquote><p>${escapeHtml(c.explanation || "")}</p>${srcs ? "<ul>" + srcs + "</ul>" : ""}</div>`;
  }).join("");
  const html = `<!doctype html><meta charset="utf-8"><title>Fact Check Report</title>
<style>body{font:15px/1.6 -apple-system,sans-serif;max-width:760px;margin:30px auto;padding:0 16px;color:#1a1a1a}
.r{border-left:4px solid #999;padding:8px 14px;margin:12px 0;background:#f7f7f8;border-radius:6px}
.true{border-color:#2ecc71}.false{border-color:#e74c3c}.uncertain{border-color:#f1c40f}
.b{font-weight:700}blockquote{margin:6px 0;color:#333}a{color:#2563eb}</style>
<h1>Fact Check Report</h1><p>Generated ${new Date().toLocaleString()} · ${claims.size} claims</p>${rows}`;
  const blob = new Blob([html], { type: "text/html" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "fact-check-report-" + new Date().toISOString().slice(0, 10) + ".html";
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus("Report exported.", "ok");
}

// ---------- live recording (mic -> WebSocket -> Transcribe -> live fact-check) ----------
const rec = { active: false, ws: null, ac: null, proc: null, src: null, stream: null };

function onWsEvent(m) {
  if (m.type === "transcript") {
    if (m.partial) {
      $("partial").textContent = m.text ? " " + m.text : "";
    } else {
      const t = $("transcript");
      t.appendChild(document.createTextNode((t.textContent ? " " : "") + m.text));
      $("partial").textContent = "";
    }
  } else if (m.type === "claim.identified") {
    addClaim(m.claim, m.claim, m.id);
  } else if (m.type === "claim.verified") {
    const c = claims.get(m.id);
    if (c) {
      Object.assign(c, { status: "verified", verdict: (m.verdict || "UNCERTAIN").toUpperCase(),
        confidence: m.confidence || 0, explanation: m.explanation || "", sources: m.sources || [] });
      setClaimStatus(m.id);
    }
  } else if (m.type === "status") {
    setStatus("Live: " + m.message, "busy");
  }
}

async function startRecording() {
  if (!CONFIG.wsBase) { setStatus("wsBase not set in config.js.", "err"); return; }
  try { rec.stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { setStatus("Microphone access denied.", "err"); return; }

  // reset UI for a fresh live session
  claims.clear(); claimSeq = 0;
  $("transcript").innerHTML = ""; $("chips").innerHTML = ""; $("partial").textContent = "";
  $("tiles").innerHTML = ""; $("tilesPanel").classList.add("hidden");
  $("transcriptPanel").classList.remove("hidden"); $("statsBar").classList.remove("hidden");
  $("export").disabled = true; updateStats();

  rec.ac = new AudioContext({ sampleRate: 16000 });
  rec.src = rec.ac.createMediaStreamSource(rec.stream);
  rec.proc = rec.ac.createScriptProcessor(4096, 1, 1);
  rec.ws = new WebSocket(CONFIG.wsBase);
  rec.ws.binaryType = "arraybuffer";
  rec.ws.onopen = () => setStatus("Recording — speak now…", "busy");
  rec.ws.onerror = () => setStatus("Streaming server not reachable — start backend/streaming/server.py.", "err");
  rec.ws.onclose = () => { if (rec.active) stopRecording(); };
  rec.ws.onmessage = (ev) => { try { onWsEvent(JSON.parse(ev.data)); } catch (e) {} };
  rec.proc.onaudioprocess = (e) => {
    if (!rec.ws || rec.ws.readyState !== 1) return;
    const f32 = e.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) { const s = Math.max(-1, Math.min(1, f32[i])); i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
    rec.ws.send(i16.buffer);
  };
  rec.src.connect(rec.proc); rec.proc.connect(rec.ac.destination);
  rec.active = true;
  $("record").textContent = "■ Stop"; $("record").classList.add("recording");
}

function stopRecording() {
  rec.active = false;
  try { if (rec.ws && rec.ws.readyState === 1) rec.ws.send("stop"); } catch (e) {}
  try { rec.proc && rec.proc.disconnect(); } catch (e) {}
  try { rec.src && rec.src.disconnect(); } catch (e) {}
  try { rec.ac && rec.ac.close(); } catch (e) {}
  try { rec.stream && rec.stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
  setTimeout(() => { try { rec.ws && rec.ws.close(); } catch (e) {} }, 800);
  $("record").textContent = "● Record"; $("record").classList.remove("recording");
  if (claims.size) $("export").disabled = false;
  setStatus("Stopped recording.", "ok");
}

function toggleRecord() { rec.active ? stopRecording() : startRecording(); }

// ---------- login handler ----------
async function onLogin() {
  const email = $("email").value.trim();
  const pw = $("password").value;
  if (!email || !pw) { setStatus("Enter email and password.", "err"); return; }
  setStatus("Signing in…", "busy");
  $("login").disabled = true;
  try {
    await login(email, pw);
    await getToken();
    $("password").value = "";
    updateAuthUI();
    setStatus("Signed in.", "ok");
  } catch (e) {
    setStatus("Sign-in failed: " + String(e.message || e), "err");
  } finally { $("login").disabled = false; }
}

// ---------- wire up ----------
document.addEventListener("DOMContentLoaded", () => {
  $("check").addEventListener("click", onCheck);
  $("export").addEventListener("click", exportReport);
  $("login").addEventListener("click", onLogin);
  $("logout").addEventListener("click", logout);
  $("record").addEventListener("click", toggleRecord);
  $("password").addEventListener("keydown", (e) => { if (e.key === "Enter") onLogin(); });
  $("modalClose").addEventListener("click", closeModal);
  $("modal").querySelector(".modal-backdrop").addEventListener("click", closeModal);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  // Event-delegated clicks on marks/chips/tiles open the modal (but let source links work).
  document.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const el = e.target.closest("[data-claim-id]");
    if (el) openModal(el.dataset.claimId);
  });
  // Restore a previous session (refresh token in localStorage) and get a fresh id token.
  restoreAuth();
  updateAuthUI();
  if (auth.refreshToken) {
    refresh().then(() => { updateAuthUI(); setStatus(`Signed in as ${auth.email}.`, "ok"); })
             .catch(() => { logout(); });
  }
  if (!CONFIG.apiBase || !CONFIG.clientId) setStatus("Set apiBase + clientId in config.js (copy config.sample.js).", "err");
});
