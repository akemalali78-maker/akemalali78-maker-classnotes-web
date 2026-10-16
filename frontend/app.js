/* 课堂纪要 · 前端逻辑（无构建，纯原生 JS） */
(function () {
  "use strict";

  /* ---------- 登录页背景：滚动位置驱动视频进度 ---------- */
  const hero = document.getElementById("hero-video");
  hero.src = "/static/media/ocean-" + (innerWidth < 700 ? 720 : 1280) + ".mp4";
  hero.play().then(() => hero.pause()).catch(() => {}); // iOS 需先 play 一次才能 seek
  addEventListener("touchstart", () => hero.play().then(() => hero.pause()).catch(() => {}), { once: true });
  (function scrub() {
    requestAnimationFrame(scrub);
    if (document.getElementById("view-auth").classList.contains("hidden") || !hero.duration || hero.seeking) return;
    const max = document.documentElement.scrollHeight - innerHeight;
    const goal = hero.duration * Math.min(1, scrollY / Math.max(1, max));
    if (Math.abs(goal - hero.currentTime) > .02) hero.currentTime += (goal - hero.currentTime) * .2;
  })();

  /* ---------- 工具 ---------- */
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  let toastTimer = null;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2400);
  }

  /* ---------- 网络层 ---------- */
  const token = () => localStorage.getItem("cn_token") || "";
  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    if (token()) headers["Authorization"] = "Bearer " + token();
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || ("请求失败 " + res.status));
    return data;
  }

  /* ---------- 路由（hash） ---------- */
  const views = ["view-auth", "view-courses", "view-course", "view-record", "view-live", "view-note"];
  let currentCourse = null;
  let currentNote = null;

  function show(viewId, title, showBack) {
    views.forEach((v) => $(v).classList.add("hidden"));
    $(viewId).classList.remove("hidden");
    $("topbar").classList.toggle("hidden", viewId === "view-auth");
    $("topbar-title").textContent = title || "";
    $("btn-back").classList.toggle("hidden", !showBack);
    window.scrollTo(0, 0);
  }

  function isLanding(h) {
    return h === "#/courses" || h === "#" || h === "#/";
  }

  // 只在本次打开后的第一次落到首页时，向服务器找未结束的场次。
  // 用户主动离开后不再拉回；整页重载会重新武装。
  let liveRestoreArmed = true;

  function route() {
    const h = location.hash || "#/courses";
    const mCourse = h.match(/^#\/course\/(\d+)$/);
    const mRecord = h.match(/^#\/record(?:\/(\d+))?$/);
    const mNote = h.match(/^#\/note\/(\d+)$/);
    const mLiveLobby = h.match(/^#\/live\/(\d+)$/);
    const mLiveSess = h.match(/^#\/live\/s\/([a-f0-9]+)$/);
    if (!mLiveSess && !mLiveLobby && liveSessionId) {
      liveRestoreArmed = false; // 主动离开后不要立刻被拉回这场
      stopLive().catch(() => {});
    }
    if (!token()) return show("view-auth");
    if (mLiveSess) return openLiveSession(mLiveSess[1]);
    if (mLiveLobby) return openLiveLobby(+mLiveLobby[1]);
    if (mRecord) return openRecord(mRecord[1] ? +mRecord[1] : null);
    if (mNote) return openNote(+mNote[1]);
    if (mCourse) return openCourse(+mCourse[1]);
    if (isLanding(h)) {
      const ck = readCheckpoint();
      if (ck && /^[a-f0-9]+$/.test(ck.sid)) {
        const target = "#/live/s/" + ck.sid;
        if (location.hash !== target) location.hash = target;
        return openLiveSession(ck.sid);
      }
      if (liveRestoreArmed) {
        liveRestoreArmed = false;
        return Promise.resolve(openCourses()).then(seekActiveLive);
      }
    }
    return openCourses();
  }
  window.addEventListener("hashchange", route);
  $("btn-back").addEventListener("click", () => history.back());

  /* ---------- 登录 / 注册 ---------- */
  let authTab = "login";
  document.querySelectorAll(".auth-tab").forEach((t) => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".auth-tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      authTab = t.dataset.tab;
      $("btn-auth").textContent = authTab === "login" ? "登录" : "注册";
      $("reg-code-field").classList.toggle("hidden", authTab !== "register");
      $("auth-password").autocomplete = authTab === "register" ? "new-password" : "current-password";
      $("auth-error").classList.add("hidden");
    });
  });
  async function doAuth() {
    const u = $("auth-username").value.trim(), p = $("auth-password").value;
    const err = $("auth-error");
    err.classList.add("hidden");
    if (!u || p.length < 4) { err.textContent = "用户名不能为空，密码至少 4 位"; err.classList.remove("hidden"); return; }
    try {
      const payload = { username: u, password: p };
      if (authTab === "register") payload.registration_code = $("reg-code").value.trim();
      const r = await api("/api/auth/" + authTab, { method: "POST", json: payload });
      localStorage.setItem("cn_token", r.token);
      clearMemoryCache();
      location.hash = "#/courses";
      route();
    } catch (e) { err.textContent = e.message; err.classList.remove("hidden"); }
  }
  $("btn-auth").addEventListener("click", doAuth);
  [$("auth-username"), $("auth-password"), $("reg-code")].forEach((el) =>
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") doAuth(); }));

  /* ---------- Markdown 渲染（纪要详情美化） ---------- */
  function renderMarkdown(md) {
    const lines = String(md || "").split("\n");
    let html = "", listOpen = false, olOpen = false;

    const inline = (s) => {
      s = esc(s);
      s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      // ★★★ → 视觉标签（先替换三颗星，避免被单颗星误匹配）
      s = s.replace(/★★★/g, '<span class="star-tag s3">必考</span>');
      s = s.replace(/★★/g, '<span class="star-tag s2">很可能考</span>');
      s = s.replace(/★/g, '<span class="star-tag s1">了解</span>');
      return s;
    };
    // 老师原话："……" 或 "……" 开头的列表项 → 引用块
    const isQuote = (s) => /^[“"]/.test(s.trim());

    const closeLists = () => {
      if (listOpen) { html += "</ul>"; listOpen = false; }
      if (olOpen) { html += "</ol>"; olOpen = false; }
    };

    for (const raw of lines) {
      const line = raw.trim();
      if (/^##\s+/.test(line)) {
        closeLists();
        html += "<h2>" + inline(line.replace(/^##\s+/, "")) + "</h2>";
      } else if (/^[-•]\s+/.test(line)) {
        const body = line.replace(/^[-•]\s+/, "");
        if (isQuote(body)) {
          closeLists();
          const q = esc(body).replace(/^[“"]/, "").replace(/[”"]$/, "");
          html += '<div class="teacher-quote"><p>' + q + "</p></div>";
        } else {
          if (!listOpen) { closeLists(); html += "<ul>"; listOpen = true; }
          html += "<li>" + inline(body) + "</li>";
        }
      } else if (/^\d+[.、]\s+/.test(line)) {
        if (!olOpen) { closeLists(); html += "<ol>"; olOpen = true; }
        html += "<li>" + inline(line.replace(/^\d+[.、]\s+/, "")) + "</li>";
      } else if (line === "") {
        closeLists();
      } else {
        closeLists();
        html += "<p>" + inline(line) + "</p>";
      }
    }
    closeLists();
    return html;
  }

  /* ---------- 课程列表 ---------- */
  // 内存缓存：返回首页时先画上次的课表，网络只在后台刷新。
  let coursesCache = null;
  const notesCache = new Map();
  const noteCache = new Map();
  let navGen = 0;

  function clearMemoryCache() {
    coursesCache = null;
    notesCache.clear();
    noteCache.clear();
  }
  function skelCards(n) {
    return Array.from({ length: n }, () =>
      '<div class="skel-card"><div class="skel line w40"></div><div class="skel line w70"></div></div>').join("");
  }
  function rememberCourse(course) {
    if (!course || course.id == null || !Array.isArray(coursesCache)) return;
    coursesCache = coursesCache.some((c) => c.id === course.id)
      ? coursesCache.map((c) => c.id === course.id ? course : c)
      : [course].concat(coursesCache);
  }
  function forgetCourse(id) {
    if (Array.isArray(coursesCache)) coursesCache = coursesCache.filter((c) => c.id !== id);
    notesCache.delete(id);
  }

  function paintCourses(courses) {
    const box = $("course-list");
    const sig = courses.map((c) => [c.id, c.name, c.schedule_text, c.mode].join("\u0001")).join("\u0002") || "empty";
    $("course-count").textContent = courses.length;
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig;
    if (!courses.length) {
      box.innerHTML =
        '<div class="empty">' +
        "<h3>还没有课程</h3><p>把这学期的课加进来，<br>下次上课就能一键记录了。</p>" +
        '<button class="btn primary" id="empty-add">添加第一门课</button></div>';
      $("empty-add").addEventListener("click", () => openSheet());
      return;
    }
    box.innerHTML = courses.map((c) =>
      '<div class="course-card" data-id="' + c.id + '">' +
      '<div class="course-ink">' + esc((c.name || "").slice(0, 1)) + "</div>" +
      '<div class="course-info"><h3>' + esc(c.name) + "</h3><p>" +
      esc(c.schedule_text || "未设置上课时间") + "</p></div>" +
      '<span class="mode-pill">' + esc(c.mode) + "</span>" +
      '<svg class="chev" width="18" height="18" viewBox="0 0 20 20" fill="none"><path d="M7.5 4.5 12.5 10l-5 5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
      "</div>").join("");
    document.querySelectorAll(".course-card").forEach((el) =>
      el.addEventListener("click", () => { location.hash = "#/course/" + el.dataset.id; }));
  }

  async function openCourses() {
    const gen = ++navGen;
    show("view-courses", "课堂纪要", false);
    $("greet").textContent = greeting();
    if (Array.isArray(coursesCache)) paintCourses(coursesCache);
    else {
      delete $("course-list").dataset.sig;
      $("course-list").innerHTML = skelCards(3);
    }
    try {
      const courses = await api("/api/courses");
      if (gen !== navGen) return;
      coursesCache = courses;
      paintCourses(courses);
    } catch (e) {
      if (gen !== navGen) return;
      if (/未登录|过期/.test(e.message)) {
        localStorage.removeItem("cn_token");
        clearMemoryCache();
        location.hash = "";
        route();
      } else toast(e.message);
    }
  }

  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return "夜深了";
    if (h < 12) return "上午好";
    if (h < 14) return "中午好";
    if (h < 18) return "下午好";
    return "晚上好";
  }

  $("fab-add").addEventListener("click", () => openSheet());
  $("btn-quick-record").addEventListener("click", () => { location.hash = "#/record"; });

  /* ---------- 课程表单（底部弹窗） ---------- */
  let editingId = null;
  function openSheet(course) {
    editingId = course ? course.id : null;
    $("sheet-title").textContent = course ? "编辑课程" : "新建课程";
    $("f-name").value = course ? course.name : "";
    $("f-weekday").value = course && course.weekday != null ? String(course.weekday) : "";
    $("f-start-time").value = course ? (course.start_time || "") : "";
    $("f-end-time").value = course ? (course.end_time || "") : "";
    $("f-mode").value = course ? course.mode : "考试";
    $("f-start").value = course ? course.start_date : "";
    $("scrim").classList.remove("hidden");
    $("sheet").classList.remove("hidden");
  }
  function closeSheet() { $("scrim").classList.add("hidden"); $("sheet").classList.add("hidden"); }
  $("scrim").addEventListener("click", () => { closeSheet(); closePickSheet(); closeImportSheet(); });

  $("btn-save-course").addEventListener("click", async () => {
    const wd = $("f-weekday").value;
    const payload = {
      name: $("f-name").value.trim(),
      weekday: wd === "" ? null : +wd,
      start_time: $("f-start-time").value,
      end_time: $("f-end-time").value,
      mode: $("f-mode").value,
      start_date: $("f-start").value,
    };
    if (!payload.name) return toast("课程名不能为空");
    try {
      let created = null;
      if (editingId) created = await api("/api/courses/" + editingId, { method: "PUT", json: payload });
      else created = await api("/api/courses", { method: "POST", json: payload });
      rememberCourse(created);
      closeSheet();
      if (created && createForRecord) {
        // 从录音页新建事项：直接选为本次录音归属，不跳走
        createForRecord = false;
        allCourses = await api("/api/courses");
        coursesCache = allCourses;
        const c = allCourses.find((x) => x.id === created.id) || created;
        setRecordCourse(c.id, "已创建《" + c.name + "》", "自定义事项 · 手动创建");
        toast("已创建并选中");
        return;
      }
      toast("已保存");
      route();
    } catch (e) { toast(e.message); }
  });

  /* ---------- 截图导入课表 ---------- */
  const IMP_WD_NAMES = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]; // 下标 1-7
  const IMP_MODES = ["考试", "论文", "PRE展示"];

  function openImportSheet() {
    showImpStep("imp-step-upload");
    $("imp-file").value = "";
    $("scrim").classList.remove("hidden");
    $("import-sheet").classList.remove("hidden");
  }
  function closeImportSheet() {
    $("scrim").classList.add("hidden");
    $("import-sheet").classList.add("hidden");
  }
  function showImpStep(id) {
    ["imp-step-upload", "imp-step-loading", "imp-step-result", "imp-step-error"]
      .forEach((s) => $(s).classList.toggle("hidden", s !== id));
  }
  function showImpError(msg) {
    $("imp-err-msg").textContent = msg || "识别失败，请重试。";
    showImpStep("imp-step-error");
  }

  $("btn-import-img").addEventListener("click", openImportSheet);
  $("imp-close").addEventListener("click", closeImportSheet);
  $("imp-cancel").addEventListener("click", closeImportSheet);
  $("imp-retry").addEventListener("click", () => showImpStep("imp-step-upload"));
  $("imp-manual").addEventListener("click", () => { closeImportSheet(); openSheet(); });

  $("imp-file").addEventListener("change", async () => {
    const f = $("imp-file").files[0];
    if (!f) return;
    showImpStep("imp-step-loading");
    try {
      const fd = new FormData();
      fd.append("image", f);
      const r = await api("/api/courses/import-image", { method: "POST", body: fd });
      if (!r.courses || !r.courses.length) {
        showImpError("没有识别出课程，请换一张更清晰的课表截图重试。");
        return;
      }
      renderImpRows(r.courses);
      showImpStep("imp-step-result");
    } catch (e) {
      showImpError(e.message);
    }
  });

  function renderImpRows(courses) {
    $("imp-count").textContent = courses.length;
    $("imp-list").innerHTML = courses.map((c, i) =>
      '<div class="imp-row" data-i="' + i + '">' +
      '<label class="field" style="margin-bottom:10px"><span>课程名</span>' +
      '<input class="imp-name" type="text" value="' + esc(c.name) + '"></label>' +
      '<div class="imp-grid">' +
      '<label class="field"><span>星期</span><select class="imp-wd">' +
      IMP_WD_NAMES.map((n, w) => w === 0 ? "" :
        '<option value="' + w + '"' + (w === c.weekday ? " selected" : "") + ">" + n + "</option>").join("") +
      "</select></label>" +
      '<label class="field"><span>考核方式</span><select class="imp-mode">' +
      IMP_MODES.map((m) => '<option' + (m === "考试" ? " selected" : "") + ">" + m + "</option>").join("") +
      "</select></label>" +
      '<label class="field"><span>开始</span><input class="imp-start" type="time" value="' + esc(c.start_time || "") + '"></label>' +
      '<label class="field"><span>结束</span><input class="imp-end" type="time" value="' + esc(c.end_time || "") + '"></label>' +
      "</div>" +
      '<button class="btn ghost danger small imp-del">删除这门</button>' +
      "</div>").join("");
    document.querySelectorAll(".imp-del").forEach((b) =>
      b.addEventListener("click", () => {
        b.closest(".imp-row").remove();
        const n = document.querySelectorAll(".imp-row").length;
        $("imp-count").textContent = n;
        $("imp-confirm").textContent = "确认导入 " + n + " 门课程";
        if (!n) showImpError("已全部删除，请重新上传或改为手动添加。");
      }));
    $("imp-confirm").textContent = "确认导入 " + courses.length + " 门课程";
  }

  $("imp-confirm").addEventListener("click", async () => {
    const rows = Array.from(document.querySelectorAll(".imp-row"));
    if (!rows.length) return toast("没有可导入的课程");
    const btn = $("imp-confirm");
    btn.disabled = true;
    btn.textContent = "导入中…";
    let ok = 0, fail = 0;
    for (const row of rows) {
      const name = row.querySelector(".imp-name").value.trim();
      if (!name) { fail++; continue; }
      try {
        await api("/api/courses", {
          method: "POST",
          json: {
            name: name,
            // 后端星期 0=周一，识别结果 1=周一，此处转换
            weekday: +row.querySelector(".imp-wd").value - 1,
            start_time: row.querySelector(".imp-start").value,
            end_time: row.querySelector(".imp-end").value,
            mode: row.querySelector(".imp-mode").value,
            start_date: "",
          },
        });
        ok++;
      } catch (e) { fail++; }
    }
    btn.disabled = false;
    closeImportSheet();
    toast("成功导入 " + ok + " 门课程" + (fail ? "，" + fail + " 门失败" : ""));
    route();
  });

  /* ---------- 确认弹窗 ---------- */
  let modalOk = null;
  function confirmDlg(title, desc, okText, fn) {
    $("modal-title").textContent = title;
    $("modal-desc").textContent = desc || "";
    $("modal-ok").textContent = okText || "删除";
    modalOk = fn;
    $("modal").classList.remove("hidden");
  }
  $("modal-cancel").addEventListener("click", () => $("modal").classList.add("hidden"));
  $("modal-ok").addEventListener("click", async () => {
    $("modal").classList.add("hidden");
    if (modalOk) await modalOk();
  });

  /* ---------- 课程详情 ---------- */
  function courseMetaLine(course) {
    return (course.schedule_text || "未设置上课时间") +
      (course.start_date ? " · 开学 " + course.start_date : "");
  }
  function paintCourseHead(course) {
    currentCourse = course;
    $("topbar-title").textContent = course.name;
    $("course-name").textContent = course.name;
    $("course-meta").textContent = courseMetaLine(course);
    $("course-mode").textContent = course.mode || "";
  }
  function paintNotes(notes) {
    const box = $("note-list");
    const sig = notes.map((n) => [n.id, n.title, n.recorded_at].join("\u0001")).join("\u0002") || "empty";
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig;
    if (!notes.length) {
      box.innerHTML =
        '<div class="empty">' +
        "<h3>还没记过这门课</h3><p>下课铃响之前，点「开始记录」，<br>重点、考点、论文素材都帮你整理好。</p></div>";
      return;
    }
    box.innerHTML = notes.map((n) => {
      const plain = (n.content || "").replace(/[#*>-]/g, "").replace(/\n+/g, " ").slice(0, 60);
      return '<div class="note-card" data-id="' + n.id + '">' +
        "<h4>" + esc(n.title) + "</h4>" +
        '<div class="meta">' + esc(n.recorded_at || "") + "</div>" +
        (plain ? '<p class="peek">' + esc(plain) + "…</p>" : "") +
        "</div>";
    }).join("");
    document.querySelectorAll(".note-card").forEach((el) =>
      el.addEventListener("click", () => { location.hash = "#/note/" + el.dataset.id; }));
  }
  async function openCourse(id) {
    const gen = ++navGen;
    show("view-course", "", true);
    const cachedCourse = (coursesCache || []).find((c) => c.id === id);
    const cachedNotes = notesCache.get(id);
    if (cachedCourse) paintCourseHead(cachedCourse);
    else {
      $("course-name").textContent = "";
      $("course-meta").textContent = "";
      $("course-mode").textContent = "";
    }
    if (cachedNotes) paintNotes(cachedNotes);
    else {
      delete $("note-list").dataset.sig;
      $("note-list").innerHTML = skelCards(2);
    }
    try {
      const [courses, notes] = await Promise.all([
        api("/api/courses"),
        api("/api/courses/" + id + "/notes"),
      ]);
      if (gen !== navGen) return;
      coursesCache = courses;
      const course = courses.find((c) => c.id === id);
      if (!course) { location.hash = "#/courses"; return; }
      const list = Array.isArray(notes) ? notes : [];
      notesCache.set(id, list);
      paintCourseHead(course);
      paintNotes(list);
    } catch (e) {
      if (gen !== navGen) return;
      toast(e.message);
    }
  }

  $("btn-record").addEventListener("click", () => {
    if (currentCourse) location.hash = "#/record/" + currentCourse.id;
  });
  $("btn-edit-course").addEventListener("click", () => { if (currentCourse) openSheet(currentCourse); });
  $("btn-del-course").addEventListener("click", () => {
    if (!currentCourse) return;
    confirmDlg("删除这门课？", "《" + currentCourse.name + "》的全部纪要和录音都会被删除。", "删除", async () => {
      await api("/api/courses/" + currentCourse.id, { method: "DELETE" });
      forgetCourse(currentCourse.id);
      toast("已删除");
      location.hash = "#/courses";
    });
  });

  /* ---------- 录音页 ---------- */
  let mediaRecorder = null, audioChunks = [], recStart = 0, recTimerId = null;
  let audioCtx = null, analyser = null, rafId = null;
  let recordCourseId = null;   // 本次录音归属的课程（自动识别，可手动切换）
  let allCourses = [];
  let createForRecord = false; // 从录音页"新建事项"进入课程表单时为 true，保存后自动选为本次录音归属
  const wave = $("wave"), wctx = wave.getContext("2d");

  function fmtTime(ms) {
    const s = Math.floor(ms / 1000);
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  function drawWaveIdle() {
    cancelAnimationFrame(rafId);
    wctx.clearRect(0, 0, wave.width, wave.height);
    wctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--border").trim() || "#E9E9E3";
    const n = 48, gap = wave.width / n;
    for (let i = 0; i < n; i++) {
      const h = 6 + Math.abs(Math.sin(i * 0.55)) * 8;
      const x = i * gap + gap / 2;
      wctx.beginPath();
      wctx.arc(x, wave.height / 2, 0, 0, 0);
      wctx.fillRect(x - 2, wave.height / 2 - h / 2, 4, h);
    }
  }

  function drawWaveLive() {
    const data = new Uint8Array(analyser.frequencyBinCount);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2F4A63";
    const draw = () => {
      rafId = requestAnimationFrame(draw);
      analyser.getByteFrequencyData(data);
      wctx.clearRect(0, 0, wave.width, wave.height);
      const n = 48, gap = wave.width / n;
      wctx.fillStyle = accent;
      for (let i = 0; i < n; i++) {
        const v = data[Math.floor(i * data.length / n / 1.6)] / 255;
        const h = 4 + v * 84;
        const x = i * gap + gap / 2;
        const alpha = 0.35 + v * 0.65;
        wctx.globalAlpha = alpha;
        wctx.beginPath();
        wctx.roundRect(x - 3, wave.height / 2 - h / 2, 6, h, 3);
        wctx.fill();
      }
      wctx.globalAlpha = 1;
    };
    draw();
  }

  function pickMime() {
    const cands = ["audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
    for (const m of cands) { if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m; }
    return "";
  }

  const WD_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  function courseTimeText(c) {
    if (c.weekday == null || !c.start_time) return "未设置上课时间";
    return WD_NAMES[c.weekday] + " " + c.start_time + (c.end_time ? "–" + c.end_time : "");
  }

  async function openRecord(preselectId) {
    stopRecTracks();
    show("view-record", "记录课堂", true);
    $("topbar-title").textContent = "记录课堂";
    resetRecUI();
    $("rec-match").classList.add("hidden");
    recordCourseId = null;
    try {
      allCourses = await api("/api/courses");
      coursesCache = allCourses;
      if (!allCourses.length) {
        toast("先添加一门课程吧");
        openSheet();
        location.hash = "#/courses";
        return;
      }
      if (preselectId && allCourses.some((c) => c.id === preselectId)) {
        // 从课程页点进来：直接用这门课
        setRecordCourse(preselectId, "手动选择", "从课程页进入");
      } else {
        // 自动识别：按当前时间匹配
        const now = new Date();
        const iso = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" +
          String(now.getDate()).padStart(2, "0") + "T" +
          String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0") + ":00";
        const m = await api("/api/courses/match?at=" + encodeURIComponent(iso));
        if (m.selected) {
          const sub = m.mode === "window" ? courseTimeText(m.selected) + " · 已按上课时间自动匹配"
                                          : "当前不在上课时间，为你选中了最近的一门";
          setRecordCourse(m.selected.id, m.label, sub);
        } else {
          setRecordCourse(allCourses[0].id, "请选择课程", "还没有设置上课时间的课程，点「换一门」选择");
        }
      }
    } catch (e) { toast(e.message); }
    // 预检转写服务
    api("/api/config").then((cfg) => {
      if (!cfg.asr_configured && !cfg.mock) {
        $("rec-hint").textContent = "提示：管理员尚未配置语音转写服务，录音将无法生成纪要";
      }
    }).catch(() => {});
  }

  function setRecordCourse(id, label, sub) {
    recordCourseId = id;
    $("match-label").textContent = label;
    $("match-sub").textContent = sub || "";
    $("rec-match").classList.remove("hidden");
  }

  /* 录音页"新建事项"：不在课表上的讲座/组会/临时课，随手命名即记 */
  $("btn-new-event").addEventListener("click", () => {
    closePickSheet();
    createForRecord = true;
    openSheet();
    $("sheet-title").textContent = "新建事项";
    $("f-name").value = "";
    $("f-name").placeholder = "例如：学术讲座-人工智能";
  });

  /* 换一门：课程选择器 */
  $("btn-switch-course").addEventListener("click", () => {
    $("pick-list").innerHTML = allCourses.map((c) =>
      '<button class="pick-item' + (c.id === recordCourseId ? " selected" : "") + '" data-id="' + c.id + '">' +
      '<span class="course-ink">' + esc(c.name.slice(0, 1)) + "</span>" +
      '<span class="pick-name">' + esc(c.name) + "</span>" +
      '<span class="pick-time">' + esc(courseTimeText(c)) + "</span>" +
      (c.id === recordCourseId
        ? '<svg class="pick-check" width="18" height="18" viewBox="0 0 20 20" fill="none"><path d="m6 10.5 3 3 5-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : "") +
      "</button>").join("");
    document.querySelectorAll(".pick-item").forEach((el) =>
      el.addEventListener("click", () => {
        const c = allCourses.find((x) => x.id === +el.dataset.id);
        setRecordCourse(c.id, "已切换为《" + c.name + "》", courseTimeText(c) + " · 手动选择");
        closePickSheet();
      }));
    $("scrim").classList.remove("hidden");
    $("sheet-course").classList.remove("hidden");
  });
  function closePickSheet() {
    $("sheet-course").classList.add("hidden");
    if ($("sheet").classList.contains("hidden")) $("scrim").classList.add("hidden");
  }

  function resetRecUI() {
    $("rec-processing").classList.add("hidden");
    $("rec-btn").classList.remove("recording");
    $("rec-icon-mic").classList.remove("hidden");
    $("rec-icon-stop").classList.add("hidden");
    $("rec-timer").textContent = "00:00";
    $("rec-hint").textContent = "轻点开始，把手机放在离老师近一点的地方";
    drawWaveIdle();
  }

  function stopRecTracks() {
    cancelAnimationFrame(rafId);
    clearInterval(recTimerId);
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try { mediaRecorder.stop(); } catch (e) {}
    }
    if (mediaRecorder && mediaRecorder.stream) {
      mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    }
    mediaRecorder = null;
    if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  }

  $("rec-btn").addEventListener("click", async () => {
    if (mediaRecorder && mediaRecorder.state === "recording") return stopRecording();
    // 开始
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      return toast("当前浏览器不支持页内录音，请用「上传音频文件」");
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickMime();
      mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      audioChunks = [];
      const capturedRecorder = mediaRecorder, capturedChunks = audioChunks;
      capturedRecorder.ondataavailable = (e) => { if (e.data.size) capturedChunks.push(e.data); };
      capturedRecorder.onstop = () => onRecStopped(capturedRecorder, capturedChunks);
      // 波形
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      drawWaveLive();
      mediaRecorder.start(500);
      recStart = Date.now();
      recTimerId = setInterval(() => { $("rec-timer").textContent = fmtTime(Date.now() - recStart); }, 500);
      $("rec-btn").classList.add("recording");
      $("rec-icon-mic").classList.add("hidden");
      $("rec-icon-stop").classList.remove("hidden");
      $("rec-hint").textContent = "正在记录… 讲重点的时候别碰手机";
    } catch (e) {
      toast("无法使用麦克风，请检查浏览器权限");
    }
  });

  function stopRecording() {
    clearInterval(recTimerId);
    cancelAnimationFrame(rafId);
    if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
  }

  function onRecStopped(capturedRecorder, capturedChunks) {
    const mime = capturedRecorder.mimeType || "audio/webm";
    const ext = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
    const blob = new Blob(capturedChunks, { type: mime });
    if (mediaRecorder === capturedRecorder) stopRecTracks();
    else capturedRecorder.stream.getTracks().forEach((t) => t.stop());
    if (blob.size < 2000) { resetRecUI(); return toast("录音太短了，再录一段吧"); }
    uploadAudio(blob, "课堂录音." + ext);
  }

  $("file-input").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) uploadAudio(f, f.name);
    e.target.value = "";
  });

  function setStep(n) {
    document.querySelectorAll(".step").forEach((el) => {
      const s = +el.dataset.s;
      el.classList.toggle("active", s === n);
      el.classList.toggle("done", s < n);
    });
  }

  async function uploadAudio(blob, filename) {
    if (!recordCourseId) return toast("请先选择一门课程");
    const courseName = (allCourses.find((c) => c.id === recordCourseId) || {}).name || "";
    show("view-record", "记录课堂", true);
    $("rec-match").classList.add("hidden");
    $("rec-stage").style.display = "none";
    document.querySelector(".rec-upload").style.display = "none";
    $("rec-processing").classList.remove("hidden");
    setStep(1);
    const fd = new FormData();
    fd.append("audio", blob, filename);
    try {
      const headers = {};
      if (token()) headers["Authorization"] = "Bearer " + token();
      setStep(2);
      // 用 fetch 的流式无法得知后端阶段，这里按时间推进步骤示意
      const stepTimer = setInterval(() => {
        const active = document.querySelector(".step.active");
        if (active && +active.dataset.s < 3) setStep(+active.dataset.s + 1);
      }, 9000);
      const res = await fetch("/api/courses/" + recordCourseId + "/recordings", {
        method: "POST", headers, body: fd,
      });
      clearInterval(stepTimer);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || ("失败 " + res.status));
      setStep(4);
      toast("纪要生成好了");
      setTimeout(() => {
        $("rec-stage").style.display = "";
        document.querySelector(".rec-upload").style.display = "";
        location.hash = "#/note/" + data.id;
      }, 600);
    } catch (e) {
      $("rec-stage").style.display = "";
      document.querySelector(".rec-upload").style.display = "";
      $("rec-processing").classList.add("hidden");
      if (recordCourseId) $("rec-match").classList.remove("hidden");
      resetRecUI();
      toast(e.message);
    }
  }

  /* ---------- 纪要详情 ---------- */
  function paintNote(n) {
    const prev = currentNote;
    const same = prev && prev.id === n.id && prev.title === n.title &&
      prev.content === n.content && prev.transcript === n.transcript;
    currentNote = n;
    $("topbar-title").textContent = "课堂纪要";
    $("note-title").textContent = n.title || "";
    $("note-meta").textContent = (n.recorded_at || "") + " · 第" + n.session_no + "次课";
    if (!same) $("note-content").innerHTML = renderMarkdown(n.content);
    $("note-transcript").textContent = n.transcript || "（无转写文本）";
    const hasAudio = !!n.audio_path;
    $("btn-play").style.display = hasAudio ? "" : "none";
    if (!same) {
      $("note-audio").classList.add("hidden");
      $("note-audio").removeAttribute("src");
    }
  }
  async function openNote(id) {
    const gen = ++navGen;
    show("view-note", "", true);
    const cached = noteCache.get(id);
    if (cached) paintNote(cached);
    else {
      $("note-title").textContent = "";
      $("note-meta").textContent = "";
      $("note-content").innerHTML = "";
      $("note-transcript").textContent = "";
    }
    try {
      const n = await api("/api/notes/" + id);
      if (gen !== navGen) return;
      noteCache.set(id, n);
      paintNote(n);
    } catch (e) {
      if (gen !== navGen) return;
      toast(e.message);
    }
  }

  $("btn-copy").addEventListener("click", async () => {
    if (!currentNote) return;
    const text = currentNote.title + "\n\n" + currentNote.content;
    try {
      await navigator.clipboard.writeText(text);
      toast("已复制，去粘贴吧");
    } catch (e) {
      // 降级：选中复制
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); toast("已复制"); }
      catch (err) { toast("复制失败，请手动选择复制"); }
      ta.remove();
    }
  });

  $("btn-play").addEventListener("click", () => {
    if (!currentNote) return;
    const a = $("note-audio");
    if (a.classList.contains("hidden")) {
      a.src = "/api/notes/" + currentNote.id + "/audio";
      // 音频接口需要鉴权：用 fetch 取 blob 再播放
      fetch(a.src, { headers: { "Authorization": "Bearer " + token() } })
        .then((r) => { if (!r.ok) throw new Error(); return r.blob(); })
        .then((b) => { a.src = URL.createObjectURL(b); a.classList.remove("hidden"); a.play(); })
        .catch(() => toast("音频加载失败"));
    } else {
      a.classList.add("hidden"); a.pause();
    }
  });

  $("btn-del-note").addEventListener("click", () => {
    if (!currentNote) return;
    confirmDlg("删除这篇纪要？", "《" + currentNote.title + "》及录音都会被删除。", "删除", async () => {
      const gone = currentNote;
      await api("/api/notes/" + gone.id, { method: "DELETE" });
      noteCache.delete(gone.id);
      if (gone.course_id != null && notesCache.has(gone.course_id)) {
        notesCache.set(gone.course_id, notesCache.get(gone.course_id).filter((n) => n.id !== gone.id));
      }
      toast("已删除");
      history.back();
    });
  });

  $("btn-live").addEventListener("click", () => {
    if (currentCourse) location.hash = "#/live/" + currentCourse.id;
  });

  /* ---------- 实时问答模式 ---------- */
  let liveSessionId = null, liveCourseId = null, liveSeq = 0, liveAfterSeq = -1;
  let liveRecorder = null, livePollId = null, liveTimerId = null, liveStartTs = 0;
  let liveStream = null, liveChunkTimerId = null, liveRecorderDone = null;
  let liveCapturing = false, liveStarting = false, liveEnding = false;
  let liveShownSessionId = null, livePollGeneration = 0;
  let liveUploadQueue = Promise.resolve();
  const liveFailedChunks = [];
  const CHUNK_MS = 30000; // 每 30 秒一个切片
  const QUESTION_WAIT_MS = 75 * 1000; // 超时未识别到讲解就收起，避免卡片一直占屏
  const LIVE_KEY = "cn_live";
  let liveRecordSegment = null, livePageLeaving = false, liveUseKeepalive = false;
  let lastQuestions = [], qTick = null, qArchiveOpen = false;
  const qDraft = new Map(), qLocal = new Map(), qDismissed = new Set();

  function readCheckpoint() {
    try {
      const data = JSON.parse(localStorage.getItem(LIVE_KEY) || "null");
      if (!data || !data.sid) return null;
      return data;
    } catch (e) { return null; }
  }
  function clearLiveCheckpoint() { localStorage.removeItem(LIVE_KEY); }
  function saveLiveCheckpoint() {
    if (!liveSessionId) return;
    const drafts = {};
    qDraft.forEach((v, k) => { if (v) drafts[k] = v; });
    try {
      localStorage.setItem(LIVE_KEY, JSON.stringify({
        sid: liveSessionId, courseId: liveCourseId,
        startTs: liveStartTs || Date.now(), seq: liveSeq, drafts: drafts,
      }));
    } catch (e) {}
  }
  function applyCheckpoint(sid) {
    const ck = readCheckpoint();
    if (!ck || ck.sid !== sid) return;
    if (ck.courseId) liveCourseId = ck.courseId;
    if (ck.startTs) liveStartTs = ck.startTs;
    if (typeof ck.seq === "number" && ck.seq > liveSeq) liveSeq = ck.seq;
    if (ck.drafts) Object.keys(ck.drafts).forEach((k) => qDraft.set(String(k), ck.drafts[k]));
  }
  function showWeChatTip() {
    const wechat = /MicroMessenger/i.test(navigator.userAgent || "");
    ["wechat-tip-lobby", "wechat-tip-live"].forEach((id) => $(id).classList.toggle("hidden", !wechat));
  }
  function ensureLiveTimer() {
    if (!liveStartTs) return;
    $("live-timer").textContent = fmtTime(Math.max(0, Date.now() - liveStartTs));
    if (liveTimerId) return;
    liveTimerId = setInterval(() => {
      $("live-timer").textContent = fmtTime(Math.max(0, Date.now() - liveStartTs));
    }, 1000);
  }
  function liveMicAlive() {
    if (!liveStream || !liveStream.getTracks) return false;
    return liveStream.getTracks().some((t) => t.readyState === "live");
  }
  function syncLiveMicUi() {
    const btn = $("btn-live-resume"), note = $("live-mic-status"), endBtn = $("btn-live-end");
    const ended = !!(endBtn && endBtn.disabled && /已结束/.test(endBtn.textContent || ""));
    const active = $("live-active") && !$("live-active").classList.contains("hidden");
    const show = !!(liveSessionId && active && !liveCapturing && !liveStarting && !liveEnding && !ended);
    btn.classList.toggle("hidden", !show);
    if (!show) { note.classList.add("hidden"); return; }
    note.textContent = "麦克风已暂停。切到后台或分屏时系统通常会停掉录音；已上传的内容还在，点「继续录音」接着记。";
    note.classList.remove("hidden");
  }
  function flushLiveCapture(opts) {
    opts = opts || {};
    if (!liveSessionId && !liveCapturing) return;
    if (opts.leaving) livePageLeaving = true;
    if (opts.keepalive) liveUseKeepalive = true;
    saveLiveCheckpoint();
    const recorder = liveRecorder;
    if (recorder && recorder.state === "recording") {
      try { recorder.stop(); } catch (e) {}
    }
  }
  function onLiveVisible() {
    livePageLeaving = false;
    if (!liveSessionId) return;
    if (liveCapturing && !liveMicAlive()) {
      liveCapturing = false;
      const recorder = liveRecorder;
      if (recorder && recorder.state !== "inactive") {
        try { recorder.stop(); } catch (e) {}
      }
      if (liveStream) {
        liveStream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
        liveStream = null;
      }
    } else if (liveCapturing && liveMicAlive() && liveRecordSegment &&
               (!liveRecorder || liveRecorder.state !== "recording")) {
      try { liveRecordSegment(); }
      catch (e) { liveCapturing = false; }
    }
    syncLiveMicUi();
  }
  function seekActiveLive() {
    if (!token() || !isLanding(location.hash || "#/courses")) return;
    return api("/api/live/sessions").then((list) => {
      if (!Array.isArray(list) || !isLanding(location.hash || "#/courses") || readCheckpoint()) return;
      const active = list.filter((s) => s && s.status === "live")
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))[0];
      if (!active || !/^[a-f0-9]+$/.test(active.id || "")) return;
      liveCourseId = active.course_id || liveCourseId;
      liveSessionId = active.id;
      if (active.created_at) liveStartTs = active.created_at * 1000;
      saveLiveCheckpoint();
      const target = "#/live/s/" + active.id;
      if (location.hash !== target) location.hash = target;
      return openLiveSession(active.id);
    }).catch(() => {});
  }

  function paintLiveLobby(course) {
    show("view-live", "实时问答", true);
    $("topbar-title").textContent = "实时问答";
    $("live-lobby").classList.remove("hidden");
    $("live-active").classList.add("hidden");
    $("live-course-name").textContent = "《" + course.name + "》";
    $("live-course-meta").textContent = courseTimeText(course) + " · " + course.mode + "考核";
    showWeChatTip();
  }
  async function openLiveLobby(courseId) {
    // 停录在后台进行。有缓存就先把大厅画出来，不等尾段上传。
    stopLive().catch(() => {});
    const cached = (coursesCache || []).find((c) => c.id === courseId);
    if (cached) {
      liveCourseId = courseId;
      paintLiveLobby(cached);
    }
    try {
      const courses = await api("/api/courses");
      coursesCache = courses;
      const course = courses.find((c) => c.id === courseId);
      if (!course) { location.hash = "#/courses"; return; }
      liveCourseId = courseId;
      paintLiveLobby(course);
    } catch (e) { toast(e.message); }
  }

  async function openLiveSession(sid) {
    // 开始录音后的 hashchange 会再进入这里，不能因此停掉刚开的麦克风。
    // 换场次时停录放后台：同步解开旧场次，尾段仍按原 session 上传。
    // 没有进行中的场次时 stopLive 不会清检查点，刷新恢复仍可读到它。
    if (sid !== liveSessionId) {
      stopLive().catch(() => {});
      liveSessionId = sid;
      liveSeq = 0;
      liveStartTs = 0;
      liveShownSessionId = null;
    }
    show("view-live", "实时问答", true);
    $("topbar-title").textContent = "实时问答";
    $("live-lobby").classList.add("hidden");
    $("live-active").classList.remove("hidden");
    if (liveShownSessionId !== sid) {
      liveShownSessionId = sid;
      qDraft.clear();
      qLocal.clear();
      qDismissed.clear();
      applyCheckpoint(sid);
      $("q-list").innerHTML = "";
      delete $("q-list").dataset.hash;
      $("stream").innerHTML = '<p class="stream-empty">正在连接…</p>';
      liveAfterSeq = -1;
      $("live-timer").textContent = liveStartTs ? fmtTime(Math.max(0, Date.now() - liveStartTs)) : "00:00";
      $("btn-live-end").disabled = false;
      $("btn-live-end").textContent = "下课，结束并生成纪要";
    }
    ensureLiveTimer();
    if (!livePollId) startPoll();
    showWeChatTip();
    syncLiveMicUi();
    saveLiveCheckpoint();
  }

  $("btn-live-start").addEventListener("click", async () => {
    if (!liveCourseId || liveStarting || liveCapturing || liveEnding) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      return toast("当前浏览器不支持页内录音");
    }
    const courseId = liveCourseId, lobbyHash = location.hash;
    const btn = $("btn-live-start");
    liveStarting = true;
    btn.disabled = true;
    let stream = null;
    try {
      // 先获得麦克风许可，避免拒绝权限后在服务器留下空场次。
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (location.hash !== lobbyHash) return;
      const s = await api("/api/live/sessions", { method: "POST", json: { course_id: courseId } });
      if (location.hash !== lobbyHash) return;
      liveSessionId = s.id;
      liveSeq = 0;
      liveCourseId = courseId;
      liveStartTs = Date.now();
      saveLiveCheckpoint();
      await openLiveSession(s.id);
      $("live-title").textContent = s.title;
      startLiveCapture(stream, s.id);
      stream = null; // 由实时录音状态持有，结束时释放。
      // 盖掉大厅历史，返回时一步回到进来之前的页面，不再卡在大厅。
      if (typeof location.replace === "function") location.replace("#/live/s/" + s.id);
      else location.hash = "#/live/s/" + s.id;
      ensureLiveTimer();
      syncLiveMicUi();
    } catch (e) {
      await stopLive(false);
      toast(e.message || "无法使用麦克风，请检查浏览器权限");
    } finally {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      liveStarting = false;
      btn.disabled = false;
      syncLiveMicUi();
    }
  });

  $("btn-live-resume").addEventListener("click", async () => {
    if (!liveSessionId || liveCapturing || liveStarting || liveEnding) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) return toast("当前浏览器不支持页内录音");
    const btn = $("btn-live-resume");
    liveStarting = true;
    btn.disabled = true;
    syncLiveMicUi();
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!liveSessionId) return;
      startLiveCapture(stream, liveSessionId);
      stream = null;
      if (!liveStartTs) liveStartTs = Date.now();
      ensureLiveTimer();
      saveLiveCheckpoint();
    } catch (e) {
      toast(e.message || "无法使用麦克风，请检查浏览器权限");
    } finally {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      liveStarting = false;
      btn.disabled = false;
      syncLiveMicUi();
    }
  });

  function enqueueLiveChunk(chunk) {
    const keepalive = liveUseKeepalive;
    liveUseKeepalive = false;
    const fail = () => {
      liveFailedChunks.push(chunk);
      toast("第 " + (chunk.seq + 1) + " 段上传失败，结束时将重试；该段暂未计入纪要");
    };
    saveLiveCheckpoint();
    if (keepalive) {
      const fd = new FormData();
      fd.append("session_id", chunk.sid);
      fd.append("seq", String(chunk.seq));
      fd.append("audio", chunk.blob, chunk.filename);
      const headers = {};
      if (token()) headers["Authorization"] = "Bearer " + token();
      // 页面即将被丢掉时，普通请求可能发不出去；keepalive 只用于这一段。
      liveUploadQueue = liveUploadQueue.then(() =>
        fetch("/api/live/chunk", { method: "POST", headers: headers, body: fd, keepalive: true })
          .then((res) => { if (!res.ok) throw new Error("upload failed"); })
      ).catch(fail);
      return;
    }
    liveUploadQueue = liveUploadQueue.then(async () => {
      try { await uploadChunkWithRetry(chunk); }
      catch (e) { fail(); }
    });
  }

  function startLiveCapture(stream, sid) {
    const mime = pickMime();
    liveStream = stream;
    liveCapturing = true;
    const recordSegment = () => {
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : { audioBitsPerSecond: 32000 });
      const parts = [];
      let resolveStopped;
      liveRecorder = recorder;
      liveRecorderDone = new Promise((resolve) => { resolveStopped = resolve; });
      recorder.ondataavailable = (e) => { if (e.data && e.data.size) parts.push(e.data); };
      recorder.onstop = () => {
        clearTimeout(liveChunkTimerId);
        liveChunkTimerId = null;
        const wasCurrent = liveRecorder === recorder;
        if (wasCurrent) liveRecorder = null;
        const actualMime = recorder.mimeType || mime || "audio/webm";
        const blob = new Blob(parts, { type: actualMime });
        if (blob.size) {
          const seq = liveSeq++;
          const ext = actualMime.includes("mp4") ? "m4a" : actualMime.includes("ogg") ? "ogg" : "webm";
          enqueueLiveChunk({ blob: blob, filename: "chunk" + seq + "." + ext, seq: seq, sid: sid });
        }
        resolveStopped();
        // 过期 recorder 的 onstop 不能再开下一段，否则会顶掉已经恢复的录音。
        if (wasCurrent && liveCapturing && liveSessionId === sid && !livePageLeaving) {
          try { recordSegment(); }
          catch (e) {
            liveCapturing = false;
            stream.getTracks().forEach((t) => t.stop());
            syncLiveMicUi();
            toast("麦克风录制中断，请结束本场并检查浏览器权限");
          }
        }
      };
      recorder.onerror = () => {
        liveCapturing = false;
        clearTimeout(liveChunkTimerId);
        stream.getTracks().forEach((t) => t.stop());
        syncLiveMicUi();
        toast("麦克风录制中断，请结束本场并检查浏览器权限");
      };
      // 每段停止并重新创建 recorder，保证每个文件包含独立媒体头。
      // MediaRecorder timeslice 后续分片通常不是可独立解码的音频文件。
      try { recorder.start(); }
      catch (e) { resolveStopped(); throw e; }
      liveChunkTimerId = setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, CHUNK_MS);
    };
    liveRecordSegment = recordSegment;
    recordSegment();
    syncLiveMicUi();
  }

  async function uploadChunkWithRetry(chunk) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const fd = new FormData();
      fd.append("session_id", chunk.sid);
      fd.append("seq", String(chunk.seq));
      fd.append("audio", chunk.blob, chunk.filename);
      try {
        await api("/api/live/chunk", { method: "POST", body: fd });
        return;
      } catch (e) {
        if (attempt === 2) throw e;
        await new Promise((resolve) => setTimeout(resolve, (attempt + 1) * 1500));
      }
    }
  }

  function startPoll() {
    clearInterval(livePollId);
    const sid = liveSessionId, generation = ++livePollGeneration;
    let polling = false;
    const poll = async () => {
      if (!sid || sid !== liveSessionId || polling) return;
      polling = true;
      try {
        const f = await api("/api/live/" + sid + "/feed?after_seq=" + liveAfterSeq);
        if (sid !== liveSessionId || generation !== livePollGeneration) return;
        if (typeof f.after_seq === "number" && f.after_seq + 1 > liveSeq) liveSeq = f.after_seq + 1;
        $("live-title").textContent = f.title || "实时问答";
        if (f.after_seq > liveAfterSeq) {
          liveAfterSeq = f.after_seq;
          appendStream(f.chunks);
        }
        renderQuestions(f.questions || []);
        if (f.status === "ended") {
          clearLiveCheckpoint();
          stopLive(false).catch(() => {});
          $("btn-live-end").disabled = true;
          $("btn-live-end").textContent = "本场记录已结束";
        }
        syncLiveMicUi();
      } catch (e) {
        if (sid === liveSessionId && e && /场次不存在/.test(e.message || "")) {
          clearLiveCheckpoint();
          liveSessionId = null;
          location.hash = "#/courses";
          openCourses();
        } else if (sid === liveSessionId && e && /过期|未登录/.test(e.message || "")) {
          localStorage.removeItem("cn_token");
          clearMemoryCache();
          clearLiveCheckpoint();
          liveSessionId = null;
          location.hash = "";
          show("view-auth");
        }
      }
      finally { polling = false; }
    };
    poll();
    livePollId = setInterval(poll, 3000);
  }

  function appendStream(chunks) {
    const box = $("stream");
    const empty = box.querySelector(".stream-empty");
    if (empty) empty.remove();
    chunks.forEach((c) => {
      const p = document.createElement("p");
      if (c.status === "skipped") {
        p.className = "skipped";
        p.textContent = "（第 " + (c.seq + 1) + " 段转写失败，已跳过）";
      } else {
        p.textContent = c.text;
      }
      box.appendChild(p);
    });
    box.scrollTop = box.scrollHeight;
  }

  function classifyQuestion(q, now) {
    const id = String(q.id);
    const local = qLocal.get(id) || {};
    const status = local.status || q.status || "open";
    const serverAnswer = local.answer != null ? local.answer : (q.answer || "");
    const text = qDraft.has(id) ? qDraft.get(id) : serverAnswer;
    const createdAt = q.created_at ? q.created_at * 1000 : 0;
    const timedOut = status === "open" && createdAt && now - createdAt >= QUESTION_WAIT_MS;
    let phase = "open";
    if (status === "dismissed" || qDismissed.has(id)) phase = "dismissed";
    else if (status === "answered") phase = "answered";
    else if (timedOut) phase = "timeout";
    return {
      id: id, question: q.question || "", ai_answer: q.ai_answer || "",
      text: text, serverAnswer: serverAnswer, phase: phase, status: status, createdAt: createdAt,
    };
  }
  function questionCardHtml(q) {
    const open = q.phase === "open";
    const badge = open ? "老师提问" : (q.phase === "timeout" ? "未识别到讲解" : (q.phase === "dismissed" ? "已收起" : "已解答"));
    const ai = q.ai_answer
      ? '<div class="q-ai-answer"><span class="q-ai-label">AI 先行作答 · 基于本节课已讲内容</span>' + esc(q.ai_answer) + "</div>"
      : "";
    const placeholder = open ? "等待老师讲解，也可以自己写"
      : (q.phase === "timeout" ? "没识别到老师讲解，可以自己写" : "补记老师的讲解");
    const dismiss = (open || q.phase === "timeout")
      ? '<button type="button" class="q-btn" data-act="dismiss" data-qid="' + q.id + '">收起</button>' : "";
    return '<div class="q-card ' + (open ? "open" : "answered") + '" data-qid="' + q.id + '">' +
      '<div class="q-head"><span class="q-badge">' + badge + "</span>" +
      '<span class="q-ai">AI 识别，仅供参考</span></div>' +
      '<p class="q-question">' + esc(q.question) + "</p>" + ai +
      '<textarea class="q-answer-input" data-qid="' + q.id + '" placeholder="' + placeholder + '">' +
      esc(q.text) + "</textarea>" +
      (open ? '<p class="q-wait">识别到讲解会自动填上，也可以直接改</p>' : "") +
      '<div class="q-actions"><button type="button" class="q-btn" data-act="save" data-qid="' + q.id + '">记下讲解</button>' +
      dismiss + "</div></div>";
  }
  function nextQuestionDelay(rows) {
    const now = Date.now();
    let wait = 0;
    rows.forEach((q) => {
      if (q.phase !== "open" || !q.createdAt) return;
      const remain = q.createdAt + QUESTION_WAIT_MS - now;
      if (remain > 0 && (!wait || remain + 40 < wait)) wait = remain + 40;
    });
    return wait;
  }
  function scheduleQuestionTick(rows, forceWait) {
    clearTimeout(qTick);
    qTick = null;
    const delay = forceWait || nextQuestionDelay(rows || []);
    if (!delay) return;
    qTick = setTimeout(() => renderQuestions(lastQuestions), delay);
  }
  function renderQuestions(qs) {
    lastQuestions = qs || [];
    const activeEl = document.activeElement;
    if (activeEl && activeEl.classList && activeEl.classList.contains("q-answer-input")) {
      scheduleQuestionTick(null, 1500);
      return;
    }
    const rows = lastQuestions.map((q) => classifyQuestion(q, Date.now()));
    const active = [], archived = [];
    rows.forEach((q) => { (q.phase === "open" ? active : archived).push(q); });
    const sig = rows.map((q) => [q.id, q.phase, q.status, q.question, q.ai_answer, q.serverAnswer].join("\u0001")).join("\u0002") +
      (qArchiveOpen ? "#o" : "");
    const box = $("q-list");
    scheduleQuestionTick(rows);
    if (box.dataset.hash === sig) return;
    box.dataset.hash = sig;
    let html = active.map(questionCardHtml).join("");
    if (archived.length) {
      html += '<details id="q-archive" class="q-archive"' + (qArchiveOpen ? " open" : "") + ">" +
        "<summary>已收起的提问（" + archived.length + "）</summary>" +
        archived.map(questionCardHtml).join("") + "</details>";
    }
    box.innerHTML = html;
  }
  function saveQuestion(qid, text) {
    qid = String(qid);
    text = String(text || "").trim();
    if (!text) return toast("先写一点老师的讲解");
    qDraft.set(qid, text);
    qLocal.set(qid, { status: "answered", answer: text });
    renderQuestions(lastQuestions);
    api("/api/live/questions/" + qid, { method: "POST", json: { answer: text, status: "answered" } })
      .catch((e) => {
        qLocal.delete(qid);
        renderQuestions(lastQuestions);
        toast(e.message || "没能记下讲解");
      });
  }
  function dismissQuestion(qid) {
    qid = String(qid);
    qDismissed.add(qid);
    qLocal.set(qid, { status: "dismissed" });
    renderQuestions(lastQuestions);
    api("/api/live/questions/" + qid, { method: "POST", json: { status: "dismissed" } })
      .catch((e) => {
        qDismissed.delete(qid);
        qLocal.delete(qid);
        renderQuestions(lastQuestions);
        toast(e.message || "没能收起");
      });
  }

  async function stopLive(clearSession) {
    clearInterval(livePollId); clearInterval(liveTimerId); clearTimeout(qTick);
    qTick = null;
    livePollId = liveTimerId = null;
    livePollGeneration++;
    clearTimeout(liveChunkTimerId);
    liveChunkTimerId = null;
    liveCapturing = false;
    liveRecordSegment = null;
    const hadSession = liveSessionId;
    const recorder = liveRecorder, stopped = liveRecorderDone, stream = liveStream;
    liveStream = null;
    if (clearSession !== false) {
      liveSessionId = null;
      liveStartTs = 0;
      if (hadSession) clearLiveCheckpoint();
    }
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
      // stop() 异步触发最终 dataavailable/onstop，必须等该段进入上传队列。
      if (stopped) await stopped;
    } finally {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (liveRecorder === recorder) liveRecorder = null;
      if (liveRecorderDone === stopped) liveRecorderDone = null;
    }
  }

  $("btn-live-end").addEventListener("click", () => {
    if (!liveSessionId || liveEnding) return;
    const sid = liveSessionId;
    confirmDlg("结束这场实时记录？", "将用整场文字流 + 问答卡片生成标准纪要。", "结束并生成纪要", async () => {
      if (liveEnding || liveSessionId !== sid) return;
      const btn = $("btn-live-end");
      liveEnding = true;
      btn.disabled = true;
      btn.textContent = "正在上传最后一段…";
      try {
        await stopLive(false);
        await liveUploadQueue;
        // 网络故障未成功的片段先补传；仍失败时不生成一份悄悄缺内容的纪要。
        for (const chunk of liveFailedChunks.filter((c) => c.sid === sid)) {
          await uploadChunkWithRetry(chunk);
          liveFailedChunks.splice(liveFailedChunks.indexOf(chunk), 1);
        }
        btn.textContent = "正在生成纪要…";
        toast("正在生成纪要…");
        const r = await api("/api/live/" + sid + "/end", { method: "POST" });
        const stillCurrent = liveSessionId === sid;
        if (stillCurrent) {
          liveSessionId = null;
          clearLiveCheckpoint();
        }
        toast("纪要生成好了");
        if (stillCurrent) location.hash = "#/note/" + r.note_id;
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "重试结束并生成纪要";
        if (liveSessionId === sid) {
          // 补传后重新取全量文字，避免漏掉先前失败的较早序号。
          liveAfterSeq = -1;
          $("stream").innerHTML = '<p class="stream-empty">重新连接文字流…</p>';
          startPoll();
        }
        toast("录音已停止，但纪要未完成：" + e.message + "。请重试。");
      } finally { liveEnding = false; }
    });
  });

  $("q-list").addEventListener("input", (e) => {
    const el = e.target;
    if (!el || !el.dataset || !el.dataset.qid) return;
    qDraft.set(String(el.dataset.qid), el.value);
    saveLiveCheckpoint();
  });
  $("q-list").addEventListener("click", (e) => {
    const btn = e.target && e.target.closest ? e.target.closest("[data-act]") : null;
    if (!btn) return;
    const qid = btn.getAttribute("data-qid");
    if (btn.getAttribute("data-act") === "dismiss") { dismissQuestion(qid); return; }
    if (btn.getAttribute("data-act") !== "save") return;
    let text = qDraft.get(String(qid)) || "";
    const card = btn.closest ? btn.closest(".q-card") : null;
    const input = card && card.querySelector ? card.querySelector("textarea") : null;
    if (input) text = input.value;
    saveQuestion(qid, text);
  });
  $("q-list").addEventListener("focusout", () => setTimeout(() => renderQuestions(lastQuestions), 0));
  $("q-list").addEventListener("toggle", (e) => {
    if (e.target && e.target.id === "q-archive") qArchiveOpen = !!e.target.open;
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushLiveCapture();
    else onLiveVisible();
  });
  document.addEventListener("freeze", () => flushLiveCapture({ leaving: true, keepalive: true }));
  window.addEventListener("pagehide", () => flushLiveCapture({ leaving: true, keepalive: true }));
  window.addEventListener("pageshow", () => onLiveVisible());
  window.addEventListener("beforeunload", (e) => {
    if (!liveCapturing && !liveStarting && !liveEnding) return;
    e.preventDefault();
    e.returnValue = "";
  });

  /* ---------- 启动 ---------- */
  route();
})();
