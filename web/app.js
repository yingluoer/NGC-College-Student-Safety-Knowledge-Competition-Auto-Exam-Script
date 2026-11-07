
(() => {
  const $ = (s) => document.querySelector(s);
  const el = {
    link: $('#linkState'), bank: $('#bankCount'), elapsed: $('#elapsed'), clock: $('#clock'),
    phase: $('#phaseText'), statusMsg: $('#statusMsg'),
    school: $('#fSchool'), user: $('#fUser'), pass: $('#fPass'),
    btnLaunch: $('#btnLaunch'), btnLogin: $('#btnLogin'),
    btnRun: $('#btnRun'), btnPause: $('#btnPause'), btnStop: $('#btnStop'),
    btnExport: $('#btnExport'), btnClearLog: $('#btnClearLog'),
    captchaImg: $('#captchaImg'), captchaMask: $('#captchaMask'), code: $('#fCode'),
    qText: $('#qText'), qOptions: $('#qOptions'), qType: $('#qType'), qAns: $('#qAns'), qHow: $('#qHow'),
    logs: $('#logs'), runTip: $('#runTip'),
    sAnswered: $('#sAnswered'), sRight: $('#sRight'), sWrong: $('#sWrong'), sMiss: $('#sMiss'),
    tAuto: $('#tAuto'), fTarget: $('#fTarget'), tOcr: $('#tOcr'),
    btnUpdateBank: $('#btnUpdateBank'), bankText: $('#bankText'), bankHint: $('#bankHint'),
    fSpeedMin: $('#fSpeedMin'), fSpeedMax: $('#fSpeedMax'), fAcc: $('#fAcc'),
    customBox: $('#customBox'), modeHint: $('#modeHint'),
    hitRate: $('#hitRate'), hitBar: $('#hitBar'),
    shotImg: $('#shotImg'), shotEmpty: $('#shotWrap .shot-empty'), tShot: $('#tShot'),
  };

  const S = { running: false, paused: false, phase: 'idle', shotTimer: 0, logCount: 0 };

  let linkBroken = false;
  async function post(path, body) {
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      const t = await r.text();
      try { return JSON.parse(t); } catch (e) { throw new Error('响应不是 JSON: ' + t.slice(0, 60)); }
    } catch (e) {
      if (!linkBroken) {
        linkBroken = true;
        setLink('NO LINK', 'bad');
        addLog('error', '后端连接中断：' + e.message + ' —— 请关闭窗口重新启动程序');
      }
      return { ok: false };
    }
  }

  function setLink(text, cls) {
    el.link.textContent = text;
    el.link.className = cls || '';
  }

  const PHASE_MAP = {
    idle: ['STANDBY', '等待启动'],
    booting: ['BOOTING', '正在启动浏览器'],
    login: ['LINKING', '填写登录信息'],
    captcha: ['CAPTCHA', '等待输入验证码'],
    logging: ['AUTH', '正在登录'],
    ready: ['ONLINE', '已登录'],
    entering: ['ENTER', '进入模块'],
    answering: ['ARMED', '答题界面就绪'],
    running: ['RUN', '自动答题中'],
    done: ['DONE', '答题结束'],
    manual: ['MANUAL', '等待手动操作'],
    unknown: ['UNKNOWN', '状态未知'],
    error: ['FAULT', '异常'],
  };

  function renderPhase(p, msg) {
    S.phase = p;
    if (el.btnUpdateBank) {
      const ready = p === 'ready' || p === 'done';
      const collecting = p === 'collecting';
      el.btnUpdateBank.disabled = !ready && !collecting;
      el.btnUpdateBank.textContent = collecting ? '采集中…' : '更新题库';
      el.bankHint.textContent = collecting
        ? '正在逐题抓取官方答案，请勿操作浏览器窗口…'
        : ready
          ? '已登录，可点「更新题库」重新抓取最新官方答案。'
          : '登录后可点「更新题库」：自动进入顺序练习逐题抓取官方答案，约 10 分钟。';
    }
    if (p === 'captcha') {
      if (el.tOcr) el.tOcr.checked = false;
      setTimeout(() => el.code && el.code.focus(), 120);
    }
    const [t, d] = PHASE_MAP[p] || [p.toUpperCase(), ''];
    el.phase.textContent = t;
    el.statusMsg.textContent = msg || d;
    if (p === 'error') setLink('FAULT', 'bad');
    else if (['ready', 'running'].includes(p)) setLink('ONLINE', 'ok');
    else if (['idle', 'done'].includes(p)) setLink('STANDBY', 'warn');
    else setLink('LINK', 'warn');
  }

  function renderStats(s) {
    if (!s) return;
    el.sAnswered.textContent = s.answered || 0;
    el.sRight.textContent = s.right || 0;
    el.sWrong.textContent = s.wrong || 0;
    el.sMiss.textContent = s.miss || 0;
    const total = (s.exact || 0) + (s.fuzzy || 0) + (s.miss || 0);
    const rate = total ? ((s.exact + s.fuzzy) / total) * 100 : 0;
    el.hitRate.textContent = rate.toFixed(1) + '%';
    el.hitBar.style.width = Math.min(100, rate) + '%';
    if (s.elapsed !== undefined) el.elapsed.textContent = fmtTime(s.elapsed);
  }

  function fmtTime(sec) {
    const m = Math.floor(sec / 60), s = sec % 60;
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  function renderQuestion(q) {
    if (!q || !q.question) return;
    document.querySelector('.question-panel').classList.add('has-q');
    el.qText.textContent = q.question;
    el.qType.textContent = q.type || '—';
    const ans = (q.answer || '').toUpperCase();
    el.qAns.textContent = ans ? 'ANS ' + ans : '';
    el.qHow.textContent = q.how ? q.how.toUpperCase() + (q.score ? ' ' + Number(q.score).toFixed(2) : '') : 'MATCH';

    const opts = q.options || [];
    el.qOptions.innerHTML = '';
    opts.forEach((o) => {
      const div = document.createElement('div');
      const pick = ans.includes((o.key || '').toUpperCase());
      div.className = 'opt' + (pick ? ' pick' : '');
      div.innerHTML = `<span class="k">${esc(o.key)}</span><span class="v">${esc(o.text)}</span><span class="mark">PICKED</span>`;
      el.qOptions.appendChild(div);
    });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function addLog(level, msg, t) {
    const d = document.createElement('div');
    d.className = 'log ' + (level || 'info');
    d.innerHTML = `<span class="t">${esc(t || nowStr())}</span><span class="m">${esc(msg)}</span>`;
    el.logs.appendChild(d);
    S.logCount++;
    while (S.logCount > 300) { el.logs.removeChild(el.logs.firstChild); S.logCount--; }
    el.logs.scrollTop = el.logs.scrollHeight;
  }

  function nowStr() {
    const d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
  }

  function renderRun(running, paused) {
    S.running = !!running;
    S.paused = !!paused;
    el.btnRun.disabled = S.running;
    el.btnPause.disabled = !S.running;
    el.btnStop.disabled = !S.running;
    el.btnPause.textContent = S.paused ? '继续' : '暂停';
    el.runTip.textContent = S.running ? (S.paused ? 'PAUSED' : 'AUTO RUNNING') : '';
  }

  function renderCaptcha(dataUrl) {
    if (!dataUrl) return;
    el.captchaImg.src = dataUrl;
    el.captchaImg.classList.add('on');
    el.captchaMask.classList.add('hide');
  }

  function fullRender(st) {
    if (!st) return;
    el.bank.textContent = st.bank || 0;
    renderPhase(st.phase, '');
    renderStats(st.stats);
    renderRun(st.running, st.paused);
    const s = st.settings || {};
    if (s.school) el.school.value = s.school;
    if (s.user) el.user.value = s.user;
    if (s.password) el.pass.value = s.password;
    if (s.auto_submit !== undefined) el.tAuto.checked = !!s.auto_submit;
    if (st.textbank !== undefined && el.bankText) el.bankText.textContent = st.textbank;
    if (s.auto_captcha !== undefined) el.tOcr.checked = !!s.auto_captcha;
    if (s.mode) setMode(s.mode, true);
    if (s.target !== undefined) el.fTarget.value = s.target;
    if (s.speed_min !== undefined) el.fSpeedMin.value = s.speed_min;
    if (s.speed_max !== undefined) el.fSpeedMax.value = s.speed_max;
    if (s.accuracy !== undefined) el.fAcc.value = s.accuracy;
    if (st.current && st.current.question) renderQuestion(st.current);
    el.logs.innerHTML = '';
    S.logCount = 0;
    (st.logs || []).forEach((l) => addLog(l.level, l.msg, l.t));
  }

  let es = null;
  function connect() {
    try { es && es.close(); } catch (e) {}
    es = new EventSource('/api/events');
    es.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      handle(m);
    };
    es.onerror = () => setLink('NO LINK', 'bad');
  }

  function handle(m) {
    switch (m.type) {
      case 'hello':
        setLink('ONLINE', 'ok');
        fullRender(m.state);
        break;
      case 'log': addLog(m.level, m.msg, m.t); break;
      case 'phase': renderPhase(m.phase, m.msg); break;
      case 'stats': renderStats(m); break;
      case 'captcha': renderCaptcha(m.data); break;
      case 'question': renderQuestion(m); break;
      case 'picked': break;
      case 'ping': break;
      default: break;
    }
  }

  el.btnLaunch.onclick = async () => {
    const body = {
      school: el.school.value.trim(),
      user: el.user.value.trim(),
      password: el.pass.value,
      delay: 0.3,
      on_miss: 'first',
      headless: false,
    };
    if (!body.school) { addLog('error', '先填学校全称'); el.school.focus(); return; }
    if (!body.user) { addLog('error', '先填学号'); el.user.focus(); return; }
    if (!body.password) { addLog('error', '先填密码'); el.pass.focus(); return; }
    el.btnLaunch.disabled = true;
    el.btnLaunch.innerHTML = '<span class="bnum">···</span> 启动中';
    addLog('info', '启动浏览器…');
    await post('/api/launch', body);
    setTimeout(() => {
      el.btnLaunch.disabled = false;
      el.btnLaunch.innerHTML = '<span class="bnum">▶</span> 重新接入';
      startShot();
    }, 1200);
  };


  document.getElementById('captchaWrap').onclick = () => post('/api/captcha');

  el.btnLogin.onclick = async () => {
    const code = el.code.value.trim();
    if (!code) { el.code.focus(); return; }
    el.btnLogin.disabled = true;
    await post('/api/login', { code });
    setTimeout(() => { el.btnLogin.disabled = false; }, 900);
  };
  el.code.addEventListener('keydown', (e) => { if (e.key === 'Enter') el.btnLogin.click(); });

  document.querySelectorAll('.btn.mod').forEach((b) => {
    b.onclick = async () => {
      document.querySelectorAll('.btn.mod').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      await post('/api/enter', { module: b.dataset.mod });
      startShot();
    };
  });

  el.btnRun.onclick = async () => { await post('/api/run'); renderRun(true, false); startShot(); };
  el.btnPause.onclick = async () => { const p = !S.paused; await post('/api/pause', { paused: p }); renderRun(S.running, p); };
  el.btnStop.onclick = async () => { await post('/api/stop'); renderRun(false, false); };
  el.btnExport.onclick = async () => {
    const r = await post('/api/export');
    addLog(r.ok ? 'ok' : 'error', r.ok ? '未命中题目已导出: ' + r.path : '导出失败');
  };
  el.btnClearLog.onclick = () => { el.logs.innerHTML = ''; S.logCount = 0; };

  el.tShot.onchange = () => { if (el.tShot.checked) startShot(); else stopShot(); };
  el.tAuto.onchange = () => post('/api/settings', { auto_submit: el.tAuto.checked });
  el.tOcr.onchange = () => post('/api/settings', { auto_captcha: el.tOcr.checked });

  el.btnUpdateBank.onclick = () => {
    if (!confirm('将从「顺序练习」逐题抓取官方答案并覆盖本地题库。\n约 10 分钟，期间不要操作浏览器窗口。\n\n继续？')) return;
    addLog('info', '开始更新题库…');
    post('/api/collect');
  };

  const MODE_HINT = {
    top: '速刷全对：全部按官方题库作答，目标 100 分，0.25s/题。',
    pass: '控分速刷：全速作答，只保证合格，硬上限 92 分不进评奖线。',
    real: '控分拟真：每题随机 3~10 秒，模拟真人节奏，同时控分合格。',
    custom: '自定义：自己定每题停留区间和目标正确率，剩余时间不够会自动压缩节奏。',
  };
  function setMode(m, silent) {
    document.querySelectorAll('.btn.strat').forEach((b) => b.classList.toggle('active', b.dataset.mode === m));
    const isCustom = m === 'custom';
    el.customBox.classList.toggle('on', isCustom);
    el.fTarget.closest('.target-row').classList.toggle('off', m === 'top' || isCustom);
    el.modeHint.textContent = MODE_HINT[m] || MODE_HINT.top;
    if (!silent) post('/api/settings', { mode: m });
  }
  document.querySelectorAll('.btn.strat').forEach((b) => {
    b.onclick = () => {
      setMode(b.dataset.mode);
      addLog('info', MODE_HINT[b.dataset.mode] || '');
    };
  });
  el.fTarget.onchange = () => post('/api/settings', { target: Math.max(80, Math.min(100, Number(el.fTarget.value) || 84)) });
  const pushCustom = () => {
    let lo = Math.max(0.5, Number(el.fSpeedMin.value) || 3);
    let hi = Math.max(0.5, Number(el.fSpeedMax.value) || 10);
    if (hi < lo) { const t = lo; lo = hi; hi = t; el.fSpeedMin.value = lo; el.fSpeedMax.value = hi; }
    post('/api/settings', {
      speed_min: lo, speed_max: hi,
      accuracy: Math.max(80, Math.min(100, Number(el.fAcc.value) || 85)),
    });
  };
  [el.fSpeedMin, el.fSpeedMax, el.fAcc].forEach((i) => i.addEventListener('change', pushCustom));

  function startShot() {
    if (S.shotTimer) return;
    const tick = async () => {
      if (!el.tShot.checked) return;
      try {
        const r = await fetch('/api/shot').then((x) => x.json());
        if (r.img) {
          el.shotImg.src = r.img;
          el.shotImg.classList.add('on');
          el.shotEmpty.classList.add('hide');
        }
      } catch (e) {}
    };
    tick();
    S.shotTimer = setInterval(tick, 2200);
  }
  function stopShot() {
    if (S.shotTimer) clearInterval(S.shotTimer);
    S.shotTimer = 0;
    el.shotImg.classList.remove('on');
    el.shotEmpty.classList.remove('hide');
  }

  setInterval(async () => {
    try {
      const st = await fetch('/api/state').then((r) => r.json());
      el.elapsed.textContent = fmtTime(st.stats.elapsed || 0);
      renderRun(st.running, st.paused);
      if (st.phase && st.phase !== S.phase) renderPhase(st.phase, '');
    } catch (e) {
      if (!linkBroken) {
        linkBroken = true;
        setLink('NO LINK', 'bad');
        addLog('error', '后端已断开，请重新启动程序');
      }
    }
  }, 3000);

  setInterval(() => {
    const d = new Date();
    el.clock.textContent = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map((n) => String(n).padStart(2, '0')).join(':');
  }, 1000);

  const syncSettings = () => post('/api/settings', {
    school: el.school.value.trim(),
    user: el.user.value.trim(),
    password: el.pass.value,
    delay: 0.3,
    on_miss: 'first',
  });
  [el.school, el.user, el.pass].forEach((i) => i.addEventListener('change', syncSettings));

  connect();
  fetch('/api/state').then((r) => r.json()).then(fullRender).catch(() => {});
  addLog('info', '终端就绪，等待接入考试系统');

  const mask = $('#noticeMask');
  if (mask && !sessionStorage.getItem('notice-ok')) {
    mask.classList.add('on');
    $('#btnAgree').onclick = () => {
      mask.classList.remove('on');
      sessionStorage.setItem('notice-ok', '1');
    };
  }
})();
