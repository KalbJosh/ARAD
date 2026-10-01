// ARAD Bridge – Autodarts -> WebSocket für Beamer + Handy, X01-Spielstand, Kalibrierung
// Node >= 18 (>= 22 empfohlen: dann Autodarts per WebSocket statt Polling). Keine Abhängigkeiten.
// Start: node server.js
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const { spawn } = require('child_process');
const CFG = require('./config.json');

const WEB = path.join(__dirname, '..', 'web');
const CALIB_FILE = path.join(__dirname, 'calibration.json');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };

// ================= Zustand =================
const DEFAULT_CALIB = {
  // Außenkante Doppelring bei 20 / 6 / 3 / 11, normiert auf die Beamerfläche (0..1)
  pts: [[0.64, 0.15], [0.84, 0.5], [0.64, 0.85], [0.44, 0.5]],
  panel: { x: 0.01, y: 0.01, scale: 1.4, auto: true, gapMm: 30, surroundMm: 360 },   // auto = oben links, bis zum Schaumstoffring   // auto = neben der Scheibe andocken
  light: { on: true, level: 0.85, radiusMm: 226, color: '#ffffff', hud: true },
  sound: { caller: true, sfx: true, volume: 0.9 },
};
function loadCalib() {
  try {
    const c = JSON.parse(fs.readFileSync(CALIB_FILE, 'utf8'));
    return { ...DEFAULT_CALIB, ...c, panel: { ...DEFAULT_CALIB.panel, ...c.panel }, light: { ...DEFAULT_CALIB.light, ...c.light }, sound: { ...DEFAULT_CALIB.sound, ...c.sound } };
  } catch { return structuredClone(DEFAULT_CALIB); }
}
let calib = loadCalib();
let calibMode = false;

const bm = { online: null, status: null, throws: [], source: null };
let game;
let visit = [];            // Darts der laufenden Aufnahme (vom Board oder simuliert)
let visitDone = false;     // Aufnahme entschieden (3 Darts, Bust oder Checkout) -> Effekt schon gezeigt
let lastResult = null;

// ================= X01 =================
const pts = d => (d?.number || 0) * (d?.multiplier || 0);
function newGame(o = {}) {
  const players = (o.players?.length ? o.players : game?.players) || CFG.players || ['Spieler 1', 'Spieler 2'];
  const start = +(o.start || game?.start || CFG.start || 501);
  const doubleOut = o.doubleOut ?? game?.doubleOut ?? CFG.doubleOut ?? true;
  game = { players, start, doubleOut, scores: players.map(() => start), stats: players.map(() => ({ pts: 0, darts: 0 })), cur: 0, winner: null, legStart: Date.now() };
  history = [];
  visit = []; visitDone = false; lastResult = null;
  say('Game on!');
}
function evalVisit(before, darts) {
  let s = before;
  for (let i = 0; i < darts.length; i++) {
    const d = darts[i];
    s -= pts(d);
    if (s < 0 || (game.doubleOut && s === 1)) return { bust: true, rest: before, at: i };
    if (s === 0) {
      if (game.doubleOut && d.multiplier !== 2) return { bust: true, rest: before, at: i };
      return { bust: false, rest: 0, won: true, at: i };
    }
  }
  return { bust: false, rest: s };
}
let history = [];                                   // Stände vor jeder gewerteten Aufnahme (für „zurück“)
function commitVisit() {
  if (game.winner === null && visit.length) {
    history.push({ scores: [...game.scores], stats: game.stats.map(s => ({ ...s })), cur: game.cur, winner: game.winner, lastResult });
    if (history.length > 50) history.shift();
    const r = evalVisit(game.scores[game.cur], visit);
    const sum = visit.reduce((a, d) => a + pts(d), 0);
    game.stats[game.cur].pts += r.bust ? 0 : sum;
    game.stats[game.cur].darts += visit.length;
    game.scores[game.cur] = r.rest;
    lastResult = { ...r, player: game.cur, darts: visit, sum };
    if (r.won) game.winner = game.cur;
    else game.cur = (game.cur + 1) % game.scores.length;
    if (!r.won) callRequire();
  }
  visit = []; visitDone = false;
  push();
}

// ================= Caller (Piper-TTS auf dem Fujitsu, Wiedergabe am Beamer) =================
const ONES = ['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen'];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
function words(n) {
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : '');
  if (n < 1000) return ONES[Math.floor(n / 100)] + ' hundred' + (n % 100 ? ' and ' + words(n % 100) : '');
  return String(n);
}
const callScore = n => n === 0 ? 'No score!' : n === 180 ? 'One hundred and eighty!' : words(n) + '!';
const BOGEY = new Set([169, 168, 166, 165, 163, 162, 159]);
function callRequire() {
  const rest = game.scores[game.cur];
  if (game.doubleOut && rest <= 170 && !BOGEY.has(rest)) say(`${game.players[game.cur]}, you require ${words(rest)}.`, 400);
}
function say(text, delay = 0) {
  broadcast({ type: 'say', text, delay });
  tts(text, true).catch(() => {});   // vorab rendern, damit der Beamer es sofort bekommt
}

const home = p => String(p).replace(/^~(?=\/)/, os.homedir());
const TTS_DIR = path.join(__dirname, 'tts-cache');
const TC = { piper: '~/.local/opt/piper/piper', voice: '~/.local/opt/piper/voices/en_GB-northern_english_male-medium.onnx', lengthScale: 1.05, ...CFG.caller };
const ttsPending = new Map();
const ttsQueue = [];
let piper = null, piperJob = null;
function ttsKey(text) {
  return crypto.createHash('sha1').update(`${TC.voice}|${TC.lengthScale}|${text}`).digest('hex').slice(0, 20) + '.wav';
}
function tts(text, urgent = false) {
  const file = path.join(TTS_DIR, ttsKey(text));
  if (fs.existsSync(file)) return Promise.resolve(file);
  if (ttsPending.has(file)) {
    const job = ttsQueue.find(j => j.file === file);
    if (urgent && job) { ttsQueue.splice(ttsQueue.indexOf(job), 1); ttsQueue.unshift(job); }
    return ttsPending.get(file);
  }
  if (!piper) return Promise.reject(new Error('piper aus'));
  const p = new Promise((resolve, reject) => {
    const job = { text, file, resolve, reject };
    urgent ? ttsQueue.unshift(job) : ttsQueue.push(job);
    piperNext();
  }).finally(() => ttsPending.delete(file));
  ttsPending.set(file, p);
  return p;
}
function piperNext() {
  if (!piper || piperJob || !ttsQueue.length) return;
  piperJob = ttsQueue.shift();
  piper.stdin.write(JSON.stringify({ text: piperJob.text, output_file: piperJob.file + '.tmp' }) + '\n');
}
function ttsStart() {
  const bin = home(TC.piper), model = home(TC.voice);
  if (!fs.existsSync(bin) || !fs.existsSync(model)) { console.log('[TTS] Piper nicht gefunden – Caller nutzt die Browser-Stimme'); return; }
  fs.mkdirSync(TTS_DIR, { recursive: true });
  piper = spawn(bin, ['--model', model, '--json-input', '--length_scale', String(TC.lengthScale), '--sentence_silence', '0.1'],
    { stdio: ['pipe', 'pipe', 'ignore'] });
  let out = '';
  piper.stdout.on('data', d => {
    out += d;
    let i;
    while ((i = out.indexOf('\n')) >= 0) {
      out = out.slice(i + 1);
      const j = piperJob; piperJob = null;
      if (j) fs.rename(j.file + '.tmp', j.file, err => err ? j.reject(err) : j.resolve(j.file));
      piperNext();
    }
  });
  piper.on('exit', code => {
    console.warn('[TTS] Piper beendet', code);
    piper = null;
    if (piperJob) { piperJob.reject(new Error('piper exit')); piperJob = null; }
    setTimeout(ttsStart, 5000);
  });
  console.log('[TTS] Piper bereit:', path.basename(model));
  // Alle Aufnahme-Ansagen einmal vorrendern (landen im Cache, danach sofort verfügbar)
  const warm = ['Game on!', 'Bust!', 'Game shot, and the leg!'];
  for (let n = 0; n <= 180; n++) warm.push(callScore(n));
  warm.forEach(t => tts(t).catch(() => {}));
}

// ================= Effekte + optionales LED-Ringlicht =================
let fxTimer = null;
const REPLAY_STEP_MS = 420;   // Abstand der Darts in der Zusammenfassung (muss zur Beamerseite passen)
async function led(level) {
  if (!CFG.ledUrl) return;
  try { await fetch(`${CFG.ledUrl}/light?level=${level}`, { signal: AbortSignal.timeout(800) }); }
  catch (e) { console.warn('[LED] nicht erreichbar:', e.message); }
}
let fxUntil = 0;
function fx(darts, ms, kind, delay = 0, info = {}) {
  clearTimeout(fxTimer);
  fxUntil = Date.now() + delay + ms;
  led(0);
  broadcast({ type: 'fx', darts, ms, kind, delay, ...info });
  fxTimer = setTimeout(() => led(CFG.ledLevel ?? 100), delay + ms);
}

function onDart(d) {
  if (visitDone || visit.length >= 3) return;
  visit.push(d);
  const r = game.winner === null ? evalVisit(game.scores[game.cur], visit) : { bust: false };
  const decided = visit.length === 3 || r.bust || r.won;
  broadcast({ type: 'hit', dart: { ...d, i: visit.length - 1 } });   // Ton + Scoreboard sofort, Scheibenlicht bleibt ruhig
  if (CFG.fx === 'perDart') fx([{ ...d, i: visit.length - 1 }], CFG.perDartMs, 'dart');
  if (decided) {
    visitDone = true;
    // Zusammenfassung: bei perDart direkt nach der letzten Dart-Animation
    const info = { sum: visit.reduce((a, x) => a + pts(x), 0), rest: r.rest, player: game.players[game.cur] };
    // visitEnd: erst jetzt auf die Scheibe – Darts nacheinander einrasten lassen, dann die Summe
    const delay = CFG.fx === 'perDart' ? CFG.perDartMs : 0;
    const replay = CFG.fx === 'visitEnd' ? visit.length * REPLAY_STEP_MS + 250 : 0;
    if (CFG.fx === 'perDart' || CFG.fx === 'visitEnd')
      fx(visit.map((x, i) => ({ ...x, i })), CFG.visitEndMs + replay, r.won ? 'win' : r.bust ? 'bust' : 'visit', delay, { ...info, replay: replay > 0 });
    say(r.won ? 'Game shot, and the leg!' : r.bust ? 'Bust!' : callScore(info.sum), delay + replay + 250);
  }
  push();
}

// ================= Autodarts =================
// Lichtwechsel auf der Scheibe (Seite neu geladen, Kalibriermuster, Show) hält Autodarts für eine Hand
// und bleibt dann im „Takeout“ hängen. Ist dabei kein Dart gezählt, ist die Scheibe leer -> Reset ist sicher.
// Autodarts-Dienst komplett neu starten: nur so lädt er eine geänderte calibration.json (Board-Stop/Start reicht nicht)
function adServiceRestart() {
  return new Promise(res => {
    const p = spawn('systemctl', ['--user', 'restart', CFG.adService || 'autodarts'], { stdio: 'ignore' });
    p.on('exit', code => { console.log('[AD] Dienst neu gestartet ->', code); setTimeout(() => res(code === 0), 4000); });
    p.on('error', () => res(false));
  });
}

// Autodarts-Kamerakalibrierung mit Netz und doppeltem Boden
const AD_CAL_FILE = home(CFG.adCalibrationFile || '~/.config/autodarts/calibration.json');
async function adCalibrateSafe() {
  let backup = null;
  try { backup = fs.readFileSync(AD_CAL_FILE); } catch {}
  let res;
  try {
    const r = await fetch(`${CFG.boardManager}/api/config/calibration/auto`, { method: 'POST', signal: AbortSignal.timeout(90000) });
    res = { ok: r.ok, status: r.status, body: (await r.text()).slice(0, 200) };
  } catch (e) { res = { ok: false, status: e.message }; }
  console.log('[AD] Kamera-Kalibrierung ->', res.status, res.body || '');
  if (!res.ok && backup) {
    // alte Kalibrierung zurück: Datei zurückschreiben, Dienst neu starten (lädt die Datei)
    try { fs.writeFileSync(AD_CAL_FILE, backup); res.restored = true; } catch (e) { console.warn('[AD] Zurückspielen fehlgeschlagen:', e.message); }
    await adServiceRestart();
    console.log('[AD] alte Kamera-Kalibrierung zurückgespielt');
  }
  return res;
}

// Eigene Kamera-Kalibrierung in die Autodarts-Datei schreiben (Sicherung davor). cams: [{ index, homography[9], undistorted[9], error }]
async function adWriteCalibration(cams) {
  try {
    const toml = fs.readFileSync(home(CFG.adConfigFile || '~/.config/autodarts/config.toml'), 'utf8');
    const devs = [...toml.matchAll(/'(native=[^']*)'/g)].map(m => m[1]);       // Reihenfolge = Kamera-Index
    const cal = JSON.parse(fs.readFileSync(AD_CAL_FILE, 'utf8'));
    fs.copyFileSync(AD_CAL_FILE, AD_CAL_FILE + '.bak-' + new Date().toISOString().replace(/[:.]/g, '-'));
    let n = 0;
    for (const c of cams || []) {
      const key = (devs[c.index] || '').replace(/^native=[^&]*&/, '');
      const byRes = cal.cameras?.[key];
      if (!byRes) continue;
      const entry = byRes['1280x720'] || byRes[Object.keys(byRes)[0]];
      if (!entry || c.homography?.length !== 9) continue;
      entry.homography = c.homography;
      if (entry.undistorted && c.undistorted?.length === 9) { entry.undistorted.homography = c.undistorted; entry.undistorted.error = c.error ?? entry.undistorted.error; }
      n++;
    }
    if (!n) return { ok: false, status: 'keine passende Kamera in der Autodarts-Datei' };
    fs.writeFileSync(AD_CAL_FILE, JSON.stringify(cal, null, 2));
    await adServiceRestart();                                   // nur ein Dienst-Neustart lädt die Datei
    console.log(`[AD] eigene Kamera-Kalibrierung geschrieben (${n} Kamera${n > 1 ? 's' : ''})`);
    return { ok: true, written: n };
  } catch (e) { return { ok: false, status: e.message }; }
}

// „Reset“ in Autodarts setzt nur den Zähler zurück; das Referenzbild der leeren Scheibe bleibt alt.
// Stop + Start nimmt ein neues Referenzbild unter dem aktuellen Licht auf.
let lastReset = 0, stuckSince = 0, calQuietUntil = 0;   // während Kalibrierung nicht eingreifen
let calLock = null;                                        // { sock, until } – nur eine Einrichtung gleichzeitig
async function adReset(why) {
  if (Date.now() - lastReset < 10000) return;
  lastReset = Date.now();
  const put = p => fetch(`${CFG.boardManager}/api/${p}`, { method: 'PUT', signal: AbortSignal.timeout(4000) });
  try {
    await put('stop');
    await new Promise(r => setTimeout(r, 1500));
    const r = await put('start');
    console.log(`[AD] Neu gestartet (${why}) -> ${r.status}`);
  } catch (e) { console.warn('[AD] Neustart fehlgeschlagen:', e.message); }
}
let errorSince = 0;
setInterval(() => {
  // Fehlerzustand (z. B. nach gescheiterter Kalibrierung): Autodarts zählt dann nicht -> neu starten
  if (bm.status === 'Error' && Date.now() > calQuietUntil) {
    if (!errorSince) errorSince = Date.now();
    if (Date.now() - errorSince > 5000) { errorSince = 0; adReset('Fehlerzustand'); }
  } else errorSince = 0;
  const takeout = /^Takeout/.test(bm.status || '') && Date.now() > fxUntil && Date.now() > calQuietUntil && !calibMode;
  if (!takeout) { stuckSince = 0; return; }
  if (!stuckSince) stuckSince = Date.now();
  const t = Date.now() - stuckSince;
  // ohne gezählte Darts: Lichtwechsel -> sofort; mit Darts: nur wenn es ungewöhnlich lange hängt (Darts längst gezogen)
  if (bm.throws.length === 0 && visit.length === 0 && t > (CFG.autoResetMs ?? 3000)) { stuckSince = 0; adReset('Takeout ohne Darts'); }
  else if (t > (CFG.stuckTakeoutMs ?? 45000)) { stuckSince = 0; adReset('Takeout hängt'); }
}, 500);

function parseName(n) {
  n = String(n || '').toUpperCase();
  if (n === 'BULL' || n === 'DB' || n === '50') return { number: 25, multiplier: 2 };
  if (n === '25' || n === 'SB') return { number: 25, multiplier: 1 };
  const m = n.match(/^(S|SI|SO|D|T)(\d{1,2})$/);
  if (m && +m[2] >= 1 && +m[2] <= 20) return { number: +m[2], multiplier: { S: 1, SI: 1, SO: 1, D: 2, T: 3 }[m[1]] };
  return { number: 0, multiplier: 0 };
}
function mapDart(t) {
  const s = t.segment || {};
  const p = parseName(s.name);
  return {
    name: s.name ?? 'Miss',
    number: s.number ?? p.number,
    multiplier: s.multiplier ?? p.multiplier,
    bed: s.bed ?? null,
    coords: t.coords ?? null,   // normiert: 1.0 = 170 mm (Doppel-Außenkante), y nach oben
  };
}
function setOnline(v, src) {
  if (v !== bm.online || src !== bm.source) {
    bm.online = v; bm.source = src;
    console.log(`[AD] ${v ? 'online' : 'offline'}${src ? ' via ' + src : ''}`);
    push();
  }
}
function onBoardState(st) {
  const throws = (st.throws || []).map(mapDart);
  const prev = bm.throws;
  bm.throws = throws;
  if (throws.length > prev.length) throws.slice(prev.length).forEach(onDart);
  else if (throws.length === 0 && prev.length > 0) commitVisit();
  if (st.status !== bm.status) { bm.status = st.status; push(); }
}

function connectBoardWs() {
  const url = CFG.boardManager.replace(/^http/, 'ws') + '/api/events';
  let ws;
  try { ws = new WebSocket(url); } catch (e) { return setTimeout(connectBoardWs, 3000); }
  let alive = true;
  ws.onopen = () => {
    setOnline(true, 'ws');
    fetch(`${CFG.boardManager}/api/state`).then(r => r.json()).then(onBoardState).catch(() => {});
  };
  ws.onmessage = e => {
    try { const m = JSON.parse(e.data); if (m.type === 'state') onBoardState(m.data || {}); } catch {}
  };
  ws.onclose = () => {
    if (!alive) return;
    alive = false;
    setOnline(false, null);
    setTimeout(connectBoardWs, 3000);
  };
  ws.onerror = () => {};
}
async function pollBoard() {
  try {
    const r = await fetch(`${CFG.boardManager}/api/state`, { signal: AbortSignal.timeout(1000) });
    onBoardState(await r.json());
    setOnline(true, 'poll');
  } catch { setOnline(false, null); }
  setTimeout(pollBoard, CFG.pollMs);
}

// ================= Simulation ohne Kameras =================
function simulate(seg) {
  const p = parseName(seg);
  const miss = /^(MISS|M|0)$/i.test(String(seg));
  if (!p.multiplier && !miss) return 'seg ungültig (z.B. T20, D16, S5, 25, BULL, MISS)';
  if (visitDone || visit.length >= 3) return 'Aufnahme voll – erst Takeout abwarten';
  onDart({ name: miss ? 'Miss' : String(seg).toUpperCase(), ...p, bed: null, coords: null });
  const wait = CFG.fx === 'off' ? 0 : CFG.perDartMs + CFG.visitEndMs + 3 * REPLAY_STEP_MS;
  if (visitDone) setTimeout(() => { if (visitDone) commitVisit(); }, wait + 800);
  return null;
}

// ================= WebSocket-Server (RFC 6455, minimal) =================
const clients = new Set();
function wsFrame(data, op = 1) {
  const p = Buffer.isBuffer(data) ? data : Buffer.from(data);
  let h;
  if (p.length < 126) h = Buffer.from([0x80 | op, p.length]);
  else if (p.length < 65536) { h = Buffer.alloc(4); h[0] = 0x80 | op; h[1] = 126; h.writeUInt16BE(p.length, 2); }
  else { h = Buffer.alloc(10); h[0] = 0x80 | op; h[1] = 127; h.writeBigUInt64BE(BigInt(p.length), 2); }
  return Buffer.concat([h, p]);
}
function wsSend(sock, obj) { if (!sock.destroyed) sock.write(wsFrame(JSON.stringify(obj))); }
function broadcast(obj) { const f = wsFrame(JSON.stringify(obj)); for (const c of clients) if (!c.destroyed) c.write(f); }

function snapshot() {
  const pre = game.winner === null ? evalVisit(game.scores[game.cur], visit) : { bust: false, rest: game.scores[game.cur] };
  return {
    type: 'state',
    game, visit, pre, lastResult, calib, calibMode, canUndo: history.length > 0,
    board: { online: bm.online, source: bm.source, status: bm.status },
    cfg: { fx: CFG.fx, visitEndMs: CFG.visitEndMs, perDartMs: CFG.perDartMs },
  };
}
let pushQueued = false;
function push() {
  if (pushQueued) return;
  pushQueued = true;
  setImmediate(() => { pushQueued = false; broadcast(snapshot()); });
}

function onClientMsg(sock, m) {
  switch (m.type) {
    case 'test': { const err = simulate(m.seg); if (err) wsSend(sock, { type: 'error', msg: err }); break; }
    case 'newGame': newGame(m); push(); break;
    case 'next': visit = []; visitDone = false; game.cur = (game.cur + 1) % game.scores.length; push(); break;
    // Dart der laufenden Aufnahme korrigieren (Autodarts lag daneben)
    case 'correctDart': {
      const i = +m.index, p = parseName(m.seg), miss = /^(MISS|M|0)$/i.test(String(m.seg));
      if (!(i >= 0 && i < visit.length) || (!p.multiplier && !miss)) break;
      visit[i] = { ...visit[i], name: miss ? 'Miss' : String(m.seg).toUpperCase(), ...p, bed: null, coords: null, corrected: true };
      const r = game.winner === null ? evalVisit(game.scores[game.cur], visit) : { bust: false };
      visitDone = visit.length === 3 || r.bust || r.won;
      push(); break;
    }
    // letzte gewertete Aufnahme zurücknehmen
    case 'undoVisit': {
      const h = history.pop();
      if (!h) break;
      game.scores = h.scores; game.stats = h.stats; game.cur = h.cur; game.winner = h.winner; lastResult = h.lastResult;
      visit = []; visitDone = false;
      push(); break;
    }
    case 'takeout': commitVisit(); break;   // manuell, falls Autodarts nicht zurücksetzt
    case 'calibMode': calibMode = !!m.on; push(); break;
    case 'calib':
      calib = {
        pts: Array.isArray(m.calib?.pts) && m.calib.pts.length === 4 ? m.calib.pts : calib.pts,
        panel: { ...calib.panel, ...m.calib?.panel },
        light: { ...calib.light, ...m.calib?.light },
        sound: { ...calib.sound, ...m.calib?.sound },
      };
      fs.writeFile(CALIB_FILE, JSON.stringify(calib, null, 2), () => {});
      broadcast({ type: 'calib', calib, from: m.from });
      break;
    // Auto-Kalibrierung: Kalibrierseite -> Beamer (Muster zeigen) -> Kalibrierseite (Muster steht)
    case 'calPattern':
      if (calLock && calLock.sock !== sock && Date.now() < calLock.until && !calLock.sock.destroyed) break;   // fremde Muster während einer Einrichtung ignorieren
      calQuietUntil = Date.now() + (m.p ? 15000 : 4000);   // Muster = Lichtwechsel, Autodarts in Ruhe lassen
      broadcast({ type: 'calPattern', p: m.p ?? null, id: m.id });
      break;
    // Kalibrierseite: Kameras wecken bzw. nach dem Einrichten neues Referenzbild aufnehmen lassen
    case 'adWake':
      if (bm.status === 'Stopped') fetch(`${CFG.boardManager}/api/start`, { method: 'PUT' }).then(r => console.log('[AD] geweckt ->', r.status)).catch(() => {});
      break;
    case 'adRestart':
      if (calLock?.sock === sock) calLock = null;
      lastReset = 0; calQuietUntil = Date.now() + 5000; adReset(m.why || 'Kalibrierseite'); break;
    // Einrichtung beginnt: Sperre holen, Autodarts sauber neu starten, danach bis zum Ende nicht eingreifen
    case 'calBegin':
      if (calLock && calLock.sock !== sock && Date.now() < calLock.until && !calLock.sock.destroyed) { wsSend(sock, { type: 'calBusy' }); break; }
      calLock = { sock, until: Date.now() + 300000 };
      wsSend(sock, { type: 'calGranted' });
      calQuietUntil = Date.now() + 300000; lastReset = 0; adReset('vor Beamer-Einrichtung'); break;
    case 'calEnd': if (calLock?.sock === sock) calLock = null; calQuietUntil = Date.now() + 3000; break;
    case 'adWriteCalibration':
      if (calLock && calLock.sock !== sock) break;
      adWriteCalibration(m.cams).then(res => wsSend(sock, { type: 'adCalWritten', ...res }));
      break;
    // Kameras in Autodarts neu kalibrieren (wie „Calibrate“ in der Terminal-App) – nur für den Einrichtungs-Besitzer
    case 'adCalibrate':
      if (calLock && calLock.sock !== sock) break;
      calQuietUntil = Math.max(calQuietUntil, Date.now() + 120000);
      // Antwort kommt erst, wenn Autodarts fertig ist (200) bzw. es nicht geklappt hat (400 „Auto-calibration failed“).
      // Ein Fehlschlag löscht in Autodarts die bisherige Kalibrierung -> vorher sichern, danach ggf. zurückspielen.
      adCalibrateSafe().then(res => wsSend(sock, { type: 'adCalStarted', ...res }));
      break;
    // Remote: Einrichtung auf dem Beamer starten (läuft dort, unabhängig vom Handy)
    case 'runSetup':
      if (calLock && Date.now() < calLock.until && !calLock.sock.destroyed) { wsSend(sock, { type: 'setupStatus', msg: 'Einrichtung läuft bereits …' }); break; }
      broadcast({ type: 'runSetup' });
      break;
    case 'calAck': broadcast({ type: 'calAck', id: m.id }); break;
    case 'calibReset': calib = structuredClone(DEFAULT_CALIB); fs.writeFile(CALIB_FILE, JSON.stringify(calib, null, 2), () => {}); push(); break;
    case 'say': if (m.text) say(String(m.text).slice(0, 200)); break;
    case 'log':
      console.log(m.src === 'calib' ? '[Kalibrierung]' : '[Beamer]', String(m.msg).slice(0, 400));
      if (m.src === 'calib') broadcast({ type: 'setupStatus', msg: String(m.msg).slice(0, 400), cls: m.cls });
      break;
    case 'reloadBeamer': broadcast({ type: 'reload' }); break;
    case 'fxTest': fx([{ ...parseName(m.seg || 'T20'), name: m.seg || 'T20', i: 0 }], CFG.perDartMs, 'dart'); break;
  }
}

function wsUpgrade(req, sock) {
  const key = req.headers['sec-websocket-key'];
  if (!key) return sock.destroy();
  const accept = crypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  sock.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  sock.setNoDelay(true);
  clients.add(sock);
  wsSend(sock, snapshot());

  let buf = Buffer.alloc(0);
  sock.on('data', chunk => {
    buf = Buffer.concat([buf, chunk]);
    while (buf.length >= 2) {
      const op = buf[0] & 0x0f, masked = buf[1] & 0x80;
      let len = buf[1] & 0x7f, off = 2;
      if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); off = 10; }
      if (len > 1 << 20) return sock.destroy();
      const need = off + (masked ? 4 : 0) + len;
      if (buf.length < need) return;
      let payload = buf.subarray(off + (masked ? 4 : 0), need);
      if (masked) {
        const mask = buf.subarray(off, off + 4);
        payload = Buffer.from(payload.map((b, i) => b ^ mask[i & 3]));
      }
      buf = buf.subarray(need);
      if (op === 1) { try { onClientMsg(sock, JSON.parse(payload.toString())); } catch (e) { console.warn('[WS] Nachricht:', e.message); } }
      else if (op === 8) { sock.end(wsFrame(Buffer.alloc(0), 8)); }
      else if (op === 9) { sock.write(wsFrame(payload, 10)); }
    }
  });
  const drop = () => { clients.delete(sock); if (calLock?.sock === sock) { calLock = null; calQuietUntil = Date.now() + 3000; } };
  sock.on('close', drop);
  sock.on('error', drop);
}

// ================= HTTP =================
function handle(req, res) {
  const u = new URL(req.url, 'http://localhost');
  const cors = { 'Access-Control-Allow-Origin': '*' };

  if (u.pathname === '/test') {
    const err = simulate(u.searchParams.get('seg'));
    res.writeHead(err ? 400 : 200, cors);
    return res.end(err || 'ok');
  }
  if (u.pathname === '/tts') {
    const text = (u.searchParams.get('text') || '').trim().slice(0, 200);
    if (!text) { res.writeHead(400, cors); return res.end(); }
    return tts(text, true).then(f => {
      res.writeHead(200, { ...cors, 'Content-Type': 'audio/wav', 'Cache-Control': 'max-age=31536000' });
      fs.createReadStream(f).pipe(res);
    }).catch(() => { res.writeHead(503, cors); res.end('tts nicht verfügbar'); });
  }
  if (u.pathname === '/api/state') {
    res.writeHead(200, { ...cors, 'Content-Type': 'application/json' });
    return res.end(JSON.stringify(snapshot()));
  }
  // Autodarts-Kamerabilder/-Kalibrierung für die Kalibrierseite (gleiche Herkunft, kein CORS-Problem)
  const ad = u.pathname.match(/^\/ad\/((?:img|streams|cams|config\/calibration)\/[\w/.-]*)$/);
  if (ad) {
    fetch(`${CFG.boardManager}/api/${ad[1]}${u.search}`, { signal: AbortSignal.timeout(4000) })
      .then(async r => {
        res.writeHead(r.status, { 'Content-Type': r.headers.get('content-type') || 'application/octet-stream', 'Cache-Control': 'no-store' });
        res.end(Buffer.from(await r.arrayBuffer()));
      })
      .catch(() => { res.writeHead(502); res.end('Autodarts nicht erreichbar'); });
    return;
  }

  const file = u.pathname === '/' ? 'index.html' : u.pathname === '/remote' ? 'remote.html' : u.pathname === '/calib' ? 'calib.html' : u.pathname === '/focus' ? 'focus.html' : u.pathname;
  const p = path.normalize(path.join(WEB, file));
  if (!p.startsWith(WEB)) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); return res.end('404'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}
function upgrade(req, sock) {
  if (new URL(req.url, 'http://localhost').pathname === '/ws') wsUpgrade(req, sock);
  else sock.destroy();
}
const server = http.createServer(handle);
server.on('upgrade', upgrade);
server.listen(CFG.port, () => console.log(`[ARAD] Bridge: http://0.0.0.0:${CFG.port}/  (Beamer)  ·  /remote  (Handy)`));

// HTTPS (selbst signiert) – nötig, damit das Handy im Browser die Kamera freigibt (/calib)
try {
  const dir = home(CFG.tlsDir || '~/.config/arad/tls');
  const tls = { key: fs.readFileSync(path.join(dir, 'key.pem')), cert: fs.readFileSync(path.join(dir, 'cert.pem')) };
  const port = CFG.httpsPort || 8443;
  const hs = https.createServer(tls, handle);
  hs.on('upgrade', upgrade);
  hs.listen(port, () => console.log(`[ARAD] HTTPS: https://0.0.0.0:${port}/calib  (Auto-Kalibrierung)`));
} catch { console.log('[ARAD] kein TLS-Zertifikat – Handy-Kamera-Kalibrierung nicht verfügbar'); }

// Keepalive gegen WLAN-/NAT-Timeouts
setInterval(() => { const f = wsFrame(Buffer.alloc(0), 9); for (const c of clients) if (!c.destroyed) c.write(f); }, 15000);

ttsStart();
newGame();
led(CFG.ledLevel ?? 100);
if (typeof WebSocket === 'function') connectBoardWs();
else { console.log('[AD] Node ohne WebSocket-Client -> Polling'); pollBoard(); }
