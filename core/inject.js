
(function () {

  const norm = (s) => (s || '').replace(/[\s\u00a0\u3000]+/g, '').trim();

  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  }

  function pick(selectors, filter) {
    for (const sel of selectors) {
      let list = [];
      try { list = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
      const hit = filter ? list.filter(filter) : list;
      if (hit.length) return hit;
    }
    return [];
  }

  function questionEl() {
    const direct = pick(['.content', '.question-content', '.question-title', '.q-content', '.subject']);
    if (direct.length) {
      return direct.sort((a, b) => norm(b.innerText).length - norm(a.innerText).length)[0];
    }
    const cands = Array.from(document.querySelectorAll('div, p, h1, h2, h3, span'))
      .filter((e) => visible(e) && e.children.length === 0)
      .map((e) => ({ e, t: norm(e.innerText) }))
      .filter((o) => o.t.length > 8);
    cands.sort((a, b) => b.t.length - a.t.length);
    return cands.length ? cands[0].e : null;
  }

  function questionText() {
    const el = questionEl();
    if (!el) return '';
    return norm(el.innerText).replace(/^\d+[、.．)）]/, '');
  }

  function questionType() {
    const el = pick(['.type', '.question-type', '.q-type'])[0];
    if (el) return norm(el.innerText);
    const t = norm(questionText());
    if (/(多选|多项|以下.*正确的有|下列说法正确的有)/.test(t)) return '多选题';
    if (/(判断|正确|错误)/.test(t) && t.length < 60) return '判断题';
    return '单选题';
  }

  const LETTER = /^([A-H])\s*[\.．、\)）:：]?\s*/;

  function optionNodes() {
    const wrap = pick(['.option', '.options .item', '.answer-list .item', '.subject-option']);
    if (wrap.length) return wrap.map((w) => ({ wrap: w, label: w.querySelector('.el-radio__label, .el-checkbox__label') || w }));
    const el = pick(['.el-radio', '.el-checkbox', '.option-item', '.answer-item']);
    return el.map((w) => ({ wrap: w, label: w.querySelector('.el-radio__label, .el-checkbox__label') || w }));
  }

  function keyOf(labelText, index) {
    const t = (labelText || '').trim();
    const m = t.match(LETTER);
    if (m) return m[1];
    if (/^(正确|对|是|√|T|true)/i.test(t)) return 'A';
    if (/^(错误|错|否|×|F|false)/i.test(t)) return 'B';
    return String.fromCharCode(65 + index);
  }

  function readOptions() {
    return optionNodes().map((o, i) => {
      const labelText = (o.label.innerText || '').trim();
      const checked = !!o.wrap.querySelector('.is-checked') ||
        (o.wrap.classList.contains('is-checked')) ||
        (o.wrap.querySelector('input') || {}).checked === true;
      return { key: keyOf(labelText, i), text: labelText, checked };
    });
  }

  function clickNode(node) {
    if (!node) return false;
    try { node.scrollIntoView({ block: 'center' }); } catch (e) {}
    if (typeof node.click === 'function') {
      node.click();
      return true;
    }
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
  }

  
  function setOption(o) {
    const wrap = o.wrap || o;
    const isOn = () => {
      const inp = wrap.querySelector('input[type=radio], input[type=checkbox]');
      if (inp && inp.checked) return true;
      return !!wrap.querySelector('.is-checked') || wrap.classList.contains('is-checked');
    };
    if (isOn()) return true;

    const input = wrap.querySelector('input[type=radio], input[type=checkbox]');
    if (input && typeof input.click === 'function') {
      input.click();
      return true;
    }
    const label = wrap.querySelector('.el-radio, .el-checkbox') || wrap;
    clickNode(label);
    return true;
  }

  function choose(keys) {
    const want = new Set((keys || '').toUpperCase().split('').filter((c) => /[A-H]/.test(c)));
    const picked = [];
    optionNodes().forEach((o, i) => {
      const labelText = (o.label.innerText || '').trim();
      const k = keyOf(labelText, i);
      if (!want.has(k)) return;
      setOption(o);
      picked.push(k);
    });
    return picked;
  }

  function checkedKeys() {
    return readOptions().filter((o) => o.checked).map((o) => o.key);
  }

  function byText(words, tagSel) {
    const list = Array.from(document.querySelectorAll(tagSel || 'button, div, span, a'))
      .filter((e) => visible(e) && (e.innerText || '').trim().length <= 12 && e.children.length <= 2);
    for (const w of words) {
      const hit = list.find((e) => norm(e.innerText) === w);
      if (hit) return hit;
    }
    for (const w of words) {
      const hit = list.find((e) => norm(e.innerText).includes(w));
      if (hit) return hit;
    }
    return null;
  }

  function nextButton() {
    const direct = pick(['.next.btn', '.next-btn', '.btn-next', '.el-button--primary']);
    for (const el of direct) {
      const t = norm((el.innerText || ''));
      if (/下一题|下一|继续|next/i.test(t) || el.classList.contains('next')) return el;
    }
    return byText(['下一题', '下一道', '继续答题', '下一']);
  }

  function submitButton() {
    const words = ['交卷', '提交', '提交试卷', '提交答案', '确认交卷', '确认提交'];
    const list = Array.from(document.querySelectorAll('button, .btn, div, span, a'))
      .filter((e) => visible(e) && (e.innerText || '').trim().length <= 10 && e.children.length <= 2);
    for (const w of words) {
      const hit = list.find((e) => norm(e.innerText) === w);
      if (hit) return hit;
    }
    for (const w of words) {
      const hit = list.find((e) => {
        const t = e.innerText || '';
        return norm(t).includes(w) && !/自动|计时|结束|提示/.test(t);
      });
      if (hit) return hit;
    }
    return null;
  }

  function startButton() {
    return byText(['开始考试', '开始答题', '开始', '进入']);
  }

  window.__EF = {
    version: '1.8',
    probe() {
      const opts = readOptions();
      if (!opts.length) {
        return {
          url: location.href, title: document.title,
          question: '', type: '', options: [], checked: [],
          hasNext: false, hasSubmit: false, nextText: '',
        };
      }
      const q = questionText();
      return {
        url: location.href,
        title: document.title,
        question: q,
        type: questionType(),
        options: opts,
        checked: opts.filter((o) => o.checked).map((o) => o.key),
        hasNext: !!nextButton(),
        hasSubmit: !!submitButton(),
        nextText: (nextButton() || {}).innerText || '',
      };
    },
    answer(keys) {
      const picked = choose(keys);
      return { picked, options: readOptions() };
    },
    
    targets(keys) {
      const want = new Set((keys || '').toUpperCase().split('').filter((c) => /[A-H]/.test(c)));
      const grab = () => {
        const out = [];
        optionNodes().forEach((o, i) => {
          const labelText = (o.label.innerText || '').trim();
          const k = keyOf(labelText, i);
          if (!want.has(k)) return;
          const r = o.wrap.getBoundingClientRect();
          out.push({
            key: k,
            x: r.left + r.width / 2,
            y: r.top + r.height / 2,
            el: o.wrap,
            ok: r.width > 4 && r.height > 4,
          });
        });
        return out;
      };

      let pts = grab();
      if (!pts.length) return [];
      const vh = window.innerHeight || 900;
      if (pts.some((p) => p.y < 4 || p.y > vh - 4)) {
        try { pts[0].el.scrollIntoView({ block: 'center' }); } catch (e) {}
        pts = grab();
      }
      return pts.filter((p) => p.ok).map((p) => ({ key: p.key, x: p.x, y: p.y }));
    },
    
    model() {
      try {
        const g = document.querySelector('.el-checkbox-group, .el-radio-group');
        if (g && g.__vue__) {
          const v = g.__vue__.$props ? g.__vue__.$props.value : null;
          if (v !== undefined && v !== null) return v;
        }
        const boxes = Array.from(document.querySelectorAll('.el-checkbox, .el-radio'));
        for (const b of boxes) {
          if (b.__vue__ && b.__vue__.$parent) {
            const v = b.__vue__.$parent.value;
            if (v !== undefined) return v;
          }
        }
      } catch (e) {}
      return null;
    },
    checked() {
      return checkedKeys();
    },
    
    clickOne(key) {
      const opts = optionNodes();
      for (let i = 0; i < opts.length; i++) {
        const k = keyOf((opts[i].label.innerText || '').trim(), i);
        if (k === key) {
          setOption(opts[i]);
          return true;
        }
      }
      return false;
    },
    
    clearAll() {
      let n = 0;
      optionNodes().forEach((o) => {
        const inp = o.wrap.querySelector('input[type=radio], input[type=checkbox]');
        if ((inp && inp.checked) || o.wrap.querySelector('.is-checked')) {
          clickNode(o.wrap);
          n++;
        }
      });
      return n;
    },
    next() {
      const b = nextButton();
      if (!b) return false;
      clickNode(b);
      return true;
    },
    
    submitPoint() {
      const b = submitButton();
      if (!b) return null;
      try { b.scrollIntoView({ block: 'center' }); } catch (e) {}
      const r = b.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) return null;
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: (b.innerText || '').trim() };
    },
    submit() {
      const b = submitButton();
      if (!b) return false;
      clickNode(b);
      return true;
    },
    start() {
      const b = startButton();
      if (!b) return false;
      clickNode(b);
      return true;
    },
    typeInto(selectorOrIndex, value) {
      const inputs = Array.from(document.querySelectorAll('input'));
      const el = typeof selectorOrIndex === 'number' ? inputs[selectorOrIndex]
        : document.querySelector(selectorOrIndex);
      if (!el) return false;
      const proto = Object.getPrototypeOf(el);
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      el.focus();
      if (desc && desc.set) desc.set.call(el, value); else el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.blur();
      return true;
    },
    clickByText(texts) {
      const b = byText(texts);
      if (!b) return false;
      clickNode(b);
      return true;
    },
    pageText() {
      return (document.body.innerText || '').slice(0, 4000);
    },
  };
  return 'ok';
})();
