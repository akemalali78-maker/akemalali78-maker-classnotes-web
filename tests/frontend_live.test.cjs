// Dependency-free behavioral regression tests. Run: node tests/frontend_live.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function harness(customFetch) {
  const elements = new Map(), timers = new Map(), storage = new Map();
  const records = [], recorders = [], windowEvents = {};
  let timerId = 0;
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const classes = new Set(["hidden"]), listeners = {};
    const el = {
      id, value: "", textContent: "", innerHTML: "", disabled: false,
      dataset: {}, style: {}, width: 600, height: 120, listeners,
      classList: {
        add: (name) => classes.add(name), remove: (name) => classes.delete(name),
        contains: (name) => classes.has(name),
        toggle: (name, force) => {
          const add = force === undefined ? !classes.has(name) : force;
          if (add) classes.add(name); else classes.delete(name);
        },
      },
      addEventListener: (event, fn) => (listeners[event] ||= []).push(fn),
      setAttribute: (name, value) => { el[name] = value; },
      getAttribute: (name) => el[name], removeAttribute: (name) => { delete el[name]; },
      querySelector: () => null, appendChild: () => {},
      getContext: () => ({ clearRect() {}, beginPath() {}, arc() {}, fillRect() {}, roundRect() {}, fill() {} }),
    };
    elements.set(id, el);
    return el;
  }
  const tabs = [element("login-tab"), element("register-tab")];
  tabs[0].dataset.tab = "login"; tabs[1].dataset.tab = "register";
  const streams = [];
  class Recorder {
    static isTypeSupported(mime) { return mime === "audio/webm"; }
    constructor(stream, options) {
      this.stream = stream; this.mimeType = options?.mimeType || "audio/webm";
      this.state = "inactive"; this.id = recorders.length;
      recorders.push(this);
    }
    start(timeslice) { this.timeslice = timeslice; this.state = "recording"; }
    stop() { this.state = "inactive"; this.stopPending = true; }
    flushStop() {
      assert.ok(this.stopPending, "stop must precede the final recorder events");
      this.stopPending = false;
      this.ondataavailable?.({ data: new Blob(["independent-header-" + this.id, "x".repeat(4096)], { type: this.mimeType }) });
      this.onstop?.();
    }
  }
  class AudioContext {
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() { return { frequencyBinCount: 128, getByteFrequencyData() {} }; }
    close() { return Promise.resolve(); }
  }
  const context = {
    console, Blob, FormData, URL, Date, Promise, MediaRecorder: Recorder, AudioContext,
    document: {
      documentElement: element("root"),
      getElementById: element,
      querySelectorAll: (selector) => selector === ".auth-tab" ? tabs : [],
      querySelector: (selector) => element(selector),
      createElement: (tag) => element("created-" + tag),
    },
    localStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, val) => storage.set(key, String(val)), removeItem: (key) => storage.delete(key),
    },
    location: { hash: "" }, history: { back() {} },
    navigator: { mediaDevices: { getUserMedia: async () => {
      const track = { stops: 0, stop() { this.stops++; } };
      const stream = { track, getTracks: () => [track] };
      streams.push(stream); return stream;
    } } },
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms, interval: true }); return id; },
    clearInterval: (id) => timers.delete(id),
    fetch: async (url, opts = {}) => {
      records.push({ url, opts });
      const custom = customFetch?.(url, opts);
      if (custom !== undefined) return custom;
      let data = {};
      if (url === "/api/courses") data = [{ id: 1, name: "测试课程", mode: "考试" }];
      if (url === "/api/live/sessions") data = { id: "abc123", title: "测试实时课堂" };
      if (url.includes("/feed?")) data = { status: "live", title: "测试实时课堂", after_seq: -1, chunks: [], questions: [] };
      if (url.endsWith("/end")) data = { note_id: 42 };
      if (url.includes("/api/auth/")) data = { token: "test-token" };
      return { ok: true, json: async () => data };
    },
  };
  context.window = context;
  context.addEventListener = (event, fn) => (windowEvents[event] ||= []).push(fn);
  context.scrollTo = () => {};
  const source = fs.readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8").replace(
    "/* ---------- 启动 ---------- */",
    `globalThis.testHooks = { route, openLiveLobby, stopLive, openRecord, stopRecTracks,
      state: () => ({ liveSessionId, liveRecorder, liveCapturing, liveEnding, liveUploadQueue, liveFailedChunks }) };
     /* ---------- 启动 ---------- */`
  );
  vm.runInNewContext(source, context, { filename: "app.js" });
  const click = async (id) => { for (const fn of element(id).listeners.click || []) await fn(); };
  const runTimer = (ms) => {
    const found = [...timers].find(([, timer]) => timer.ms === ms && !timer.interval);
    assert.ok(found, "expected timer " + ms);
    timers.delete(found[0]); found[1].fn();
  };
  return { context, element, tabs, click, runTimer, records, recorders, streams, storage, timers };
}

async function start(h) {
  h.storage.set("cn_token", "test-token");
  h.context.location.hash = "#/live/1";
  await h.context.testHooks.openLiveLobby(1);
  await h.click("btn-live-start");
  await flush();
}

(async () => {
  const registration = harness();
  registration.element("auth-username").value = "new-user";
  registration.element("auth-password").value = "unchanged-password";
  registration.element("reg-code").value = " invite-test ";
  await registration.click("register-tab");
  assert.equal(registration.element("reg-code-field").classList.contains("hidden"), false);
  await registration.click("btn-auth");
  const payload = JSON.parse(registration.records.find((r) => r.url === "/api/auth/register").opts.body);
  assert.equal(payload.registration_code, "invite-test");
  assert.equal(payload.password, "unchanged-password");
  await registration.click("login-tab");
  assert.equal(registration.element("reg-code-field").classList.contains("hidden"), true);
  await registration.click("btn-auth");
  assert.equal(JSON.parse(registration.records.find((r) => r.url === "/api/auth/login").opts.body).registration_code, undefined);
  console.log("PASS: registration invitation visibility/payload; login omits invitation");

  const ordinary = harness();
  ordinary.storage.set("cn_token", "test-token");
  ordinary.context.location.hash = "#/record/1";
  await ordinary.context.testHooks.openRecord(1);
  await ordinary.click("rec-btn");
  assert.equal(ordinary.recorders[0].state, "recording");
  await ordinary.click("rec-btn");
  assert.doesNotThrow(() => ordinary.recorders[0].flushStop());
  await flush();
  const normalRequest = ordinary.records.find((r) => r.url === "/api/courses/1/recordings");
  assert.ok(normalRequest, "normal stop still uploads the captured audio");
  assert.equal(normalRequest.opts.body.get("audio").type, "audio/webm");
  console.log("PASS: ordinary stop uses the captured recorder and uploads without a null dereference");

  const leaving = harness();
  leaving.storage.set("cn_token", "test-token");
  leaving.context.location.hash = "#/record/1";
  await leaving.context.testHooks.openRecord(1);
  await leaving.click("rec-btn");
  leaving.context.testHooks.stopRecTracks(); // Route cleanup clears the global recorder before onstop.
  assert.doesNotThrow(() => leaving.recorders[0].flushStop());
  await flush();
  assert.ok(leaving.records.some((r) => r.url === "/api/courses/1/recordings"));
  console.log("PASS: ordinary route cleanup followed by late onstop does not dereference the cleared global recorder");

  const replaced = harness();
  replaced.storage.set("cn_token", "test-token");
  replaced.context.location.hash = "#/record/1";
  await replaced.context.testHooks.openRecord(1);
  await replaced.click("rec-btn");
  replaced.context.testHooks.stopRecTracks();
  await replaced.click("rec-btn");
  replaced.recorders[0].flushStop(); await flush();
  assert.equal(replaced.recorders[1].state, "recording");
  assert.equal(replaced.streams[1].track.stops, 0, "old onstop must not stop the next recorder");
  const oldAudio = replaced.records.find((r) => r.url === "/api/courses/1/recordings").opts.body.get("audio");
  assert.ok((await oldAudio.text()).startsWith("independent-header-0"));
  await replaced.click("rec-btn"); replaced.recorders[1].flushStop(); await flush();
  const newAudio = replaced.records.filter((r) => r.url === "/api/courses/1/recordings")[1].opts.body.get("audio");
  assert.ok((await newAudio.text()).startsWith("independent-header-1"));
  assert.equal((await newAudio.text()).includes("independent-header-0"), false);
  console.log("PASS: late ordinary onstop does not stop the next recorder or mix their audio buffers");

  const denied = harness(), permission = deferred();
  denied.context.navigator.mediaDevices.getUserMedia = () => permission.promise;
  denied.storage.set("cn_token", "test-token");
  denied.context.location.hash = "#/live/1";
  await denied.context.testHooks.openLiveLobby(1);
  const firstStart = denied.click("btn-live-start");
  await denied.click("btn-live-start");
  assert.equal(denied.element("btn-live-start").disabled, true);
  permission.reject(new Error("permission denied"));
  await firstStart;
  assert.equal(denied.records.some((r) => r.url === "/api/live/sessions"), false);
  assert.equal(denied.element("btn-live-start").disabled, false);
  console.log("PASS: double start is locked; denied microphone permission creates no empty session");

  const uploads = [];
  const h = harness((url, opts) => {
    if (url !== "/api/live/chunk") return;
    const d = deferred(); uploads.push({ ...d, form: opts.body }); return d.promise;
  });
  await start(h);
  const first = h.recorders[0];
  assert.equal(first.state, "recording");
  assert.equal(first.timeslice, undefined, "segments must be independently recorded files");
  await h.context.testHooks.route(); // Automatic hashchange immediately after starting.
  assert.equal(first.state, "recording", "route must not stop the newly started capture");
  assert.equal(h.streams[0].track.stops, 0);
  assert.equal(h.element("view-live").classList.contains("hidden"), false);
  assert.equal(h.element("view-courses").classList.contains("hidden"), true);
  h.runTimer(30000); first.flushStop(); await flush();
  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].form.get("seq"), "0");
  assert.equal(uploads[0].form.get("session_id"), "abc123");
  assert.equal(h.recorders.length, 2, "next independent recorder starts after the first stops");
  await h.click("btn-live-end");
  const ending = h.click("modal-ok");
  await flush();
  assert.equal(h.recorders[1].stopPending, true);
  assert.equal(h.records.some((r) => r.url.endsWith("/end")), false);
  h.recorders[1].flushStop(); await flush();
  assert.equal(uploads.length, 1, "second upload waits for first to complete");
  uploads[0].resolve({ ok: true, json: async () => ({}) }); await flush();
  assert.equal(uploads.length, 2);
  assert.equal(uploads[1].form.get("seq"), "1");
  assert.equal(h.records.some((r) => r.url.endsWith("/end")), false, "summary waits for final upload");
  uploads[1].resolve({ ok: true, json: async () => ({}) }); await ending;
  assert.equal(h.records.filter((r) => r.url.endsWith("/end")).length, 1);
  assert.equal(h.context.location.hash, "#/note/42");
  assert.equal(h.streams[0].track.stops, 1);
  console.log("PASS: start/hash race, independent files, ordered uploads, final flush before summary");

  const nav = harness(); await start(nav);
  const stopping = nav.context.testHooks.stopLive();
  assert.equal(nav.context.testHooks.state().liveSessionId, null);
  nav.recorders[0].flushStop(); await stopping; await flush();
  assert.equal(nav.records.find((r) => r.url === "/api/live/chunk").opts.body.get("session_id"), "abc123");
  assert.equal(nav.recorders.length, 1);
  assert.equal(nav.streams[0].track.stops, 1);
  console.log("PASS: navigation cleanup keeps the final chunk bound to its original session");

  const oldFeed = deferred();
  const stale = harness((url) => url.startsWith("/api/live/abc123/feed?") ? oldFeed.promise : undefined);
  await start(stale);
  const oldStop = stale.context.testHooks.stopLive();
  stale.recorders[0].flushStop(); await oldStop;
  stale.context.location.hash = "#/live/s/def456";
  await stale.context.testHooks.route(); await flush();
  oldFeed.resolve({ ok: true, json: async () => ({ status: "ended", title: "旧场次", chunks: [], questions: [], after_seq: -1 }) });
  await flush();
  assert.equal(stale.context.testHooks.state().liveSessionId, "def456");
  assert.equal(stale.element("btn-live-end").disabled, false);
  assert.notEqual(stale.element("live-title").textContent, "旧场次");
  console.log("PASS: stale feed from an old session cannot overwrite or stop a newer session");

  let failedCalls = 0;
  const failure = harness((url) => {
    if (url !== "/api/live/chunk") return;
    failedCalls++;
    return { ok: false, status: 503, json: async () => ({ detail: "network unavailable" }) };
  });
  await start(failure); await failure.click("btn-live-end");
  let finished = false;
  const failedEnd = failure.click("modal-ok").then(() => { finished = true; });
  failure.recorders[0].flushStop();
  for (let i = 0; i < 30 && !finished; i++) {
    await flush();
    const timer = [...failure.timers].find(([, t]) => !t.interval && (t.ms === 1500 || t.ms === 3000));
    if (timer) { failure.timers.delete(timer[0]); timer[1].fn(); }
  }
  await failedEnd;
  assert.equal(failedCalls, 6, "three upload attempts plus three final recovery attempts");
  assert.equal(failure.records.some((r) => r.url.endsWith("/end")), false);
  assert.equal(failure.element("btn-live-end").disabled, false);
  assert.equal(failure.context.testHooks.state().liveFailedChunks.length, 1);
  console.log("PASS: unrecoverable final chunk prevents silent incomplete summary; retry remains available");
})().catch((error) => { console.error(error); process.exitCode = 1; });
