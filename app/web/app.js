'use strict';

// ---------------------------------------------------------------- состояние
const state = {
  heroes: [],
  byId: new Map(),
  brackets: [],
  roles: [],
  draft: { enemy: [], ally: [], banned: [] },
  mode: 'enemy',
  search: '',
};

// Роли приходят от OpenDota на английском, а интерфейс русский.
// Значение в списке остаётся английским: по нему фильтрует сервер.
const ROLE_LABELS = {
  Carry: 'Кэрри',
  Support: 'Поддержка',
  Nuker: 'Нюкер',
  Disabler: 'Контроль',
  Durable: 'Живучесть',
  Escape: 'Уход',
  Pusher: 'Пушер',
  Initiator: 'Инициатор',
};
const roleLabel = (r) => ROLE_LABELS[r] || r;

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

// Таймаут обязателен: без него неотвечающий запрос оставляет интерфейс
// пустым навсегда, и непонятно, грузится он или сломался.
const API_TIMEOUT_MS = 120000;

async function api(path, opts) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), API_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(path, Object.assign({ signal: ctrl.signal }, opts || {}));
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') {
      throw new Error(
        `сервер не ответил за ${API_TIMEOUT_MS / 1000} с (${path}). ` +
        'Обычно это значит, что нет доступа к api.opendota.com — ' +
        'проверьте интернет, VPN или брандмауэр.');
    }
    throw new Error(`не удалось связаться с сервером (${path}): ${e.message}`);
  }
  clearTimeout(timer);
  let data;
  try {
    data = await res.json();
  } catch (e) {
    throw new Error(`сервер вернул не JSON (HTTP ${res.status})`);
  }
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function showError(container, err) {
  container.innerHTML = '';
  container.appendChild(el('div', 'error', 'Ошибка: ' + err.message));
}

const sign = (v) => (v > 0 ? '+' : '') + v.toFixed(2);
const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'dim');

// ---------------------------------------------------------------- вкладки
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    tab.classList.add('active');
    $('#view-' + tab.dataset.view).classList.add('active');
    if (tab.dataset.view === 'meta') loadMeta();
    if (tab.dataset.view === 'pro') loadProList();
  });
});

// ---------------------------------------------------------------- загрузка справочника
async function boot() {
  // Показываем, что идёт загрузка: первый запуск тянет справочник героев
  // из OpenDota, и без подсказки пустой интерфейс выглядит как поломка.
  $('#hero-grid').innerHTML =
    '<div class="loading">Загружаю справочник героев из OpenDota…</div>';
  $('#src-label').textContent = 'загрузка…';
  try {
    const data = await api('/api/heroes');
    state.heroes = data.heroes;
    state.byId = new Map(data.heroes.map((h) => [h.id, h]));
    state.brackets = data.brackets;
    $('#src-label').textContent = data.offline
      ? 'источник: локальный снимок'
      : 'источник: ' + data.source;
    if (data.offline_note) {
      const warn = el('div', 'error', data.offline_note);
      $('#rec-out').parentNode.insertBefore(warn, $('#rec-out'));
    }

    const roles = new Set();
    data.heroes.forEach((h) => h.roles.forEach((r) => roles.add(r)));
    state.roles = [...roles].sort();

    fillSelect($('#bracket'), state.brackets.map((b) => [b.key, b.label]));
    fillSelect($('#meta-bracket'), state.brackets.map((b) => [b.key, b.label]));
    const posOptions = [['', 'Любая']]
      .concat((data.positions || []).map((p) => [p.key, p.label]));
    fillSelect($('#position'), posOptions);
    fillSelect($('#meta-position'), posOptions);

    renderHeroGrid();
    renderSlots();
    visionBoot();
  } catch (e) {
    bootFailed(e);
  }
}

function bootFailed(err) {
  $('#src-label').textContent = 'источник недоступен';
  const grid = $('#hero-grid');
  grid.innerHTML = '';
  grid.style.display = 'block';
  grid.appendChild(el('div', 'error', 'Не удалось загрузить героев. ' + err.message));

  const retry = el('button', 'tab', 'Попробовать снова');
  retry.style.marginTop = '10px';
  retry.addEventListener('click', () => {
    grid.style.display = '';
    boot();
  });
  grid.appendChild(retry);

  const hint = el('div', 'dim');
  hint.style.marginTop = '10px';
  hint.textContent = 'Приложению нужен доступ к api.opendota.com. ' +
    'Если он закрыт, подбор работать не будет: все данные берутся оттуда. ' +
    'Подробности ошибки видны в окне, из которого запущен сервер.';
  grid.appendChild(hint);

  $('#vision-status').textContent =
    'Недоступно, пока не загрузится справочник героев.';
}

function fillSelect(sel, pairs) {
  sel.innerHTML = '';
  pairs.forEach(([value, label]) => {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = label;
    sel.appendChild(o);
  });
}

// ---------------------------------------------------------------- драфт
$('#mode').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  state.mode = btn.dataset.mode;
  document.querySelectorAll('#mode button').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
});

$('#hero-search').addEventListener('input', (e) => {
  state.search = e.target.value.trim().toLowerCase();
  renderHeroGrid();
});

function usedIds() {
  const d = state.draft;
  return new Set([...d.enemy, ...d.ally, ...d.banned]);
}

function renderHeroGrid() {
  const grid = $('#hero-grid');
  const used = usedIds();
  grid.innerHTML = '';
  state.heroes
    .filter((h) => !state.search || (h.name || '').toLowerCase().includes(state.search))
    .forEach((h) => {
      const card = el('div', 'hero' + (used.has(h.id) ? ' used' : ''));
      const img = el('img');
      img.src = h.img;
      img.alt = h.name;
      img.loading = 'lazy';
      card.appendChild(img);
      card.appendChild(el('div', 'n', h.name));
      card.title = h.name + ' — ' + h.roles.join(', ');
      card.addEventListener('click', () => addHero(h.id));
      grid.appendChild(card);
    });
}

function addHero(id) {
  const list = state.draft[state.mode];
  const cap = state.mode === 'banned' ? 14 : 5;
  if (list.length >= cap || usedIds().has(id)) return;
  list.push(id);
  renderSlots();
  renderHeroGrid();
  refreshRecommendations();
}

function removeHero(kind, id) {
  state.draft[kind] = state.draft[kind].filter((x) => x !== id);
  renderSlots();
  renderHeroGrid();
  refreshRecommendations();
}

function renderSlots() {
  [['enemy', '#slots-enemy'], ['ally', '#slots-ally'], ['banned', '#slots-banned']]
    .forEach(([kind, sel]) => {
      const box = $(sel);
      box.innerHTML = '';
      if (!state.draft[kind].length) {
        box.appendChild(el('div', 'empty-hint', 'пусто'));
        return;
      }
      state.draft[kind].forEach((id) => {
        const h = state.byId.get(id);
        const chip = el('div', 'chip');
        const img = el('img');
        img.src = h.img;
        img.alt = h.name;
        chip.appendChild(img);
        chip.appendChild(el('span', '', h.name));
        chip.appendChild(el('span', 'x', '✕'));
        chip.title = 'Убрать';
        chip.addEventListener('click', () => removeHero(kind, id));
        box.appendChild(chip);
      });
    });
}

['#bracket', '#position', '#limit'].forEach((sel) =>
  $(sel).addEventListener('change', refreshRecommendations));

let recToken = 0;
async function refreshRecommendations() {
  const out = $('#rec-out');
  if (!state.draft.enemy.length) {
    out.innerHTML = '<div class="empty-hint">Выберите хотя бы одного героя противника.</div>';
    return;
  }
  const token = ++recToken;
  out.innerHTML = '<div class="loading">Считаю…</div>';
  try {
    const data = await api('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enemy: state.draft.enemy,
        ally: state.draft.ally,
        banned: state.draft.banned,
        bracket: $('#bracket').value,
        role: $('#role').value,
        limit: Number($('#limit').value),
      }),
    });
    if (token !== recToken) return;
    renderRecommendations(out, data);
  } catch (e) {
    if (token === recToken) showError(out, e);
  }
}

function renderRecommendations(out, data) {
  const rows = data.rows;
  out.innerHTML = '';
  if (data.note) out.appendChild(el('div', 'error', 'Внимание: ' + data.note));
  if (!rows.length) {
    out.appendChild(el('div', 'empty-hint', 'Ничего не подошло под фильтры.'));
    return;
  }
  const max = Math.max(...rows.map((r) => Math.abs(r.score_pp)), 1);
  const table = el('table');
  table.innerHTML = `<thead><tr>
      <th>#</th><th>Герой</th><th class="num">Балл</th>
      <th class="num">Матчапы</th><th class="num">База</th>
      <th class="num">Винрейт</th><th class="num">Выборка</th>
      <th>Против кого</th></tr></thead>`;
  const tb = el('tbody');

  rows.forEach((r, i) => {
    const tr = el('tr');

    tr.appendChild(el('td', 'dim', String(i + 1)));

    const tdHero = el('td');
    const cell = el('div', 'hero-cell');
    const img = el('img');
    img.src = 'https://cdn.cloudflare.steamstatic.com' + (r.img || '');
    img.alt = r.name;
    img.loading = 'lazy';
    cell.appendChild(img);
    const nameBox = el('div');
    nameBox.appendChild(el('div', '', r.name));
    nameBox.appendChild(el('div', 'dim', r.roles.slice(0, 3).join(', ')));
    cell.appendChild(nameBox);
    tdHero.appendChild(cell);
    tr.appendChild(tdHero);

    const tdScore = el('td', 'num');
    tdScore.appendChild(el('div', cls(r.score_pp), sign(r.score_pp)));
    const bar = el('div', 'bar');
    bar.style.width = Math.round((Math.abs(r.score_pp) / max) * 60) + 'px';
    bar.style.marginLeft = 'auto';
    bar.style.opacity = r.score_pp >= 0 ? '1' : '.4';
    tdScore.appendChild(bar);
    tr.appendChild(tdScore);

    tr.appendChild(el('td', 'num ' + cls(r.matchup_pp), sign(r.matchup_pp)));
    tr.appendChild(el('td', 'num ' + cls(r.base_pp), sign(r.base_pp)));
    tr.appendChild(el('td', 'num', r.base_winrate === null ? '—' : r.base_winrate.toFixed(1) + '%'));
    tr.appendChild(el('td', 'num dim', String(r.games_total)));

    const tdBreak = el('td');
    const bd = el('div', 'breakdown');
    r.per_enemy.forEach((pe) => {
      const enemy = state.byId.get(pe.enemy_id);
      const s = el('span');
      s.textContent = (enemy ? enemy.name : pe.enemy_id) + ' ';
      const v = el('b', cls(pe.adv_pp), sign(pe.adv_pp));
      s.appendChild(v);
      s.title = `${pe.games} игр в выборке`;
      if (pe.games < 15) s.style.opacity = '.45';
      bd.appendChild(s);
    });
    tdBreak.appendChild(bd);
    tr.appendChild(tdBreak);

    tb.appendChild(tr);
  });
  table.appendChild(tb);
  out.appendChild(table);

  const legend = el('div', 'dim');
  legend.style.marginTop = '10px';
  legend.textContent =
    'Балл в процентных пунктах: сколько винрейта герой добирает против этого драфта. ' +
    'Матчапы — вклад контрпика, База — насколько герой силён в выбранном ранге сам по себе. ' +
    'Полупрозрачные пары — менее 15 игр в выборке, доверять им не стоит. ' +
    'Сглаживание K = ' + (data.k_shrink ?? '—') +
    ' подобрано по разбросу самих данных: чем больше K, тем сильнее в них шум.';
  out.appendChild(legend);
}

// ---------------------------------------------------------------- чтение экрана
const vision = { timer: null, running: false, lastKey: '' };

async function visionBoot() {
  const box = $('#vision-status');
  try {
    const st = await api('/api/vision/status');
    if (!st.available) {
      box.innerHTML = '';
      box.appendChild(el('div', 'error', st.hint || 'Чтение экрана недоступно.'));
      return;
    }
    $('#vision-controls').hidden = false;
    fillSelect($('#vis-monitor'), st.monitors.filter((m) => m.index > 0)
      .map((m) => [String(m.index), m.label]));
    if (st.config) {
      $('#vis-monitor').value = String(st.config.monitor);
      $('#vis-interval').value = String(st.config.interval);
    }
    const ic = st.icons;
    box.textContent = ic.ready
      ? `Готово. Эталонов героев: ${ic.have} из ${ic.total}.`
      : `Портретов героев: ${ic.have} из ${ic.total}. Они скачаются сами при ` +
        `первом запуске слежения — это займёт около минуты. Можно и заранее, ` +
        `кнопкой «Скачать портреты».`;
  } catch (e) {
    showError(box, e);
  }
}

async function visionConfig() {
  const region = $('#vis-region').value.split(',').map(Number);
  await api('/api/vision/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      monitor: Number($('#vis-monitor').value),
      interval: Number($('#vis-interval').value),
      region,
    }),
  });
}

$('#vis-start').addEventListener('click', async () => {
  try {
    await visionConfig();
    const r = await api('/api/vision/start', { method: 'POST' });
    if (!r.started && r.state && r.state.last_error) throw new Error(r.state.last_error);
    vision.running = true;
    renderVision(r.state);
    if (vision.timer) clearInterval(vision.timer);
    vision.timer = setInterval(pollVision, 1200);
  } catch (e) { showError($('#vision-out'), e); }
});

$('#vis-stop').addEventListener('click', async () => {
  vision.running = false;
  if (vision.timer) { clearInterval(vision.timer); vision.timer = null; }
  try { renderVision((await api('/api/vision/stop', { method: 'POST' })).state); }
  catch (e) { showError($('#vision-out'), e); }
});

$('#vis-scan').addEventListener('click', async () => {
  $('#vision-out').innerHTML = '<div class="loading">Ищу героев на экране…</div>';
  try {
    await visionConfig();
    renderVision(await api('/api/vision/scan', { method: 'POST' }));
  } catch (e) { showError($('#vision-out'), e); }
});

$('#vis-icons').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  $('#vision-status').textContent =
    'Скачиваю портреты героев (127 штук), это займёт около минуты…';
  try {
    const r = await api('/api/vision/icons', { method: 'POST' });
    $('#vision-status').textContent =
      `Портретов на диске: ${r.have} из ${r.total}` +
      (r.failed ? `, не удалось скачать: ${r.failed}` : '') +
      (r.ready ? '. Можно включать слежение.' : '');
  } catch (err) { showError($('#vision-status'), err); }
  btn.disabled = false;
});

async function pollVision() {
  if (!vision.running) return;
  try { renderVision(await api('/api/vision/state')); }
  catch (e) { /* сеть моргнула — ждём следующего опроса */ }
}

function splitBySide(heroes) {
  const side = $('#vis-side').value;
  if (side === 'none' || heroes.length < 2) return { enemy: heroes, ally: [] };
  const xs = heroes.map((h) => h.box[0] + h.box[2] / 2);
  const mid = (Math.min(...xs) + Math.max(...xs)) / 2;
  const left = heroes.filter((h) => h.box[0] + h.box[2] / 2 < mid);
  const right = heroes.filter((h) => h.box[0] + h.box[2] / 2 >= mid);
  return side === 'left' ? { ally: left, enemy: right } : { ally: right, enemy: left };
}

// параметр называется vs, а не state: глобальный state — это драфт,
// перекрыть его здесь значит сломать подстановку героев
function renderVision(vs) {
  const out = $('#vision-out');
  out.innerHTML = '';
  if (!vs) { out.appendChild(el('div', 'empty-hint', 'Нет данных.')); return; }

  const head = el('div', 'dim');
  head.textContent = `Режим: ${vs.mode}` +
    (vs.template_width ? ` · размер портрета ${vs.template_width} px` : '') +
    ` · распознано: ${(vs.heroes || []).length}`;
  out.appendChild(head);

  if (vs.last_error) out.appendChild(el('div', 'error', vs.last_error));

  const heroes = vs.heroes || [];
  if (!heroes.length) {
    out.appendChild(el('div', 'empty-hint',
      'Героев на экране не видно. Откройте экран драфта и нажмите «Сканировать сейчас».'));
    return;
  }

  const { enemy, ally } = splitBySide(heroes);
  const row = el('div', 'draft-row');
  heroes.forEach((h) => {
    const chip = el('div', 'chip');
    const known = state.byId.get(h.hero_id);
    if (known && known.img) {
      const img = el('img'); img.src = known.img; img.alt = h.name; chip.appendChild(img);
    }
    chip.appendChild(el('span', '', h.name));
    chip.appendChild(el('span', 'dim', String(h.score)));
    const isAlly = ally.indexOf(h) !== -1;
    chip.title = isAlly ? 'определён как свой' : 'определён как враг';
    if (isAlly) chip.style.borderColor = 'var(--radiant)';
    row.appendChild(chip);
  });
  out.appendChild(row);

  // подставляем распознанное в драфт, не трогая то, что выбрано руками
  const key = heroes.map((h) => h.hero_id).sort().join(',') + '|' + $('#vis-side').value;
  if (key !== vision.lastKey) {
    vision.lastKey = key;
    applyVision(enemy, ally);
  }

  const note = el('div', 'dim');
  note.style.marginTop = '6px';
  note.textContent = 'Распознанное подставляется в драфт автоматически. ' +
    'Выбранного вручную героя это не перезаписывает.';
  out.appendChild(note);
}

function applyVision(enemy, ally) {
  let changed = false;
  const put = (kind, list) => {
    list.slice(0, 5).forEach((h) => {
      if (usedIds().has(h.hero_id)) return;
      if (state.draft[kind].length >= 5) return;
      state.draft[kind].push(h.hero_id);
      changed = true;
    });
  };
  put('ally', ally);
  put('enemy', enemy);
  if (changed) {
    renderSlots();
    renderHeroGrid();
    refreshRecommendations();
  }
  return changed;
}

// ---------------------------------------------------------------- мета
['#meta-bracket', '#meta-role'].forEach((sel) =>
  $(sel).addEventListener('change', loadMeta));

let metaLoaded = false;
async function loadMeta(force) {
  const out = $('#meta-out');
  if (metaLoaded && force === undefined && out.dataset.ready === '1' &&
      out.dataset.key === metaKey()) return;
  out.className = 'loading';
  out.textContent = 'Загрузка…';
  try {
    const q = new URLSearchParams({
      bracket: $('#meta-bracket').value,
      role: $('#meta-role').value,
    });
    const data = await api('/api/meta?' + q);
    out.className = 'scroll';
    out.dataset.ready = '1';
    out.dataset.key = metaKey();
    metaLoaded = true;
    renderMeta(out, data.rows);
  } catch (e) {
    out.className = '';
    showError(out, e);
  }
}

const metaKey = () => $('#meta-bracket').value + '|' + $('#meta-role').value;

function renderMeta(out, rows) {
  out.innerHTML = '';
  const table = el('table');
  table.innerHTML = `<thead><tr>
    <th>#</th><th>Герой</th><th class="num">Винрейт</th><th class="num">Пики</th>
    <th class="num">Доля пиков</th><th class="num">Про-пики</th>
    <th class="num">Про-баны</th><th class="num">Про-винрейт</th></tr></thead>`;
  const tb = el('tbody');
  rows.forEach((r, i) => {
    const tr = el('tr');
    tr.appendChild(el('td', 'dim', String(i + 1)));
    const td = el('td');
    const cell = el('div', 'hero-cell');
    const img = el('img');
    img.src = r.img;
    img.alt = r.name;
    img.loading = 'lazy';
    cell.appendChild(img);
    cell.appendChild(el('span', '', r.name));
    td.appendChild(cell);
    tr.appendChild(td);
    tr.appendChild(el('td', 'num', r.winrate === null ? '—' : r.winrate.toFixed(2) + '%'));
    tr.appendChild(el('td', 'num dim', r.picks.toLocaleString('ru-RU')));
    tr.appendChild(el('td', 'num dim', r.pick_share.toFixed(2) + '%'));
    tr.appendChild(el('td', 'num dim', String(r.pro_pick)));
    tr.appendChild(el('td', 'num dim', String(r.pro_ban)));
    tr.appendChild(el('td', 'num dim',
      r.pro_winrate === null ? '—' : r.pro_winrate.toFixed(1) + '%'));
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  out.appendChild(table);
}

// ---------------------------------------------------------------- про-матчи
let proLoaded = false;
async function loadProList() {
  if (proLoaded) return;
  const out = $('#pro-list');
  try {
    const data = await api('/api/pro/matches');
    proLoaded = true;
    out.className = 'scroll';
    out.innerHTML = '';
    data.matches.forEach((m) => {
      const card = el('div', 'match');
      const teams = el('div', 'teams');
      teams.appendChild(el('span', m.radiant_win ? 'win' : 'lose', m.radiant));
      teams.appendChild(el('span', 'dim', (m.score || []).join(':')));
      teams.appendChild(el('span', m.radiant_win === false ? 'win' : 'lose', m.dire));
      card.appendChild(teams);
      const meta = el('div', 'dim');
      const mins = m.duration ? Math.round(m.duration / 60) + ' мин' : '';
      meta.textContent = [m.league, mins].filter(Boolean).join(' · ');
      card.appendChild(meta);
      card.addEventListener('click', () => loadProMatch(m.match_id));
      out.appendChild(card);
    });
  } catch (e) {
    out.className = '';
    showError(out, e);
  }
}

async function loadProMatch(id) {
  const out = $('#pro-detail');
  out.innerHTML = '<div class="loading">Загрузка матча…</div>';
  try {
    const m = await api('/api/pro/match?id=' + id);
    renderProMatch(out, m);
  } catch (e) {
    showError(out, e);
  }
}

function renderProMatch(out, m) {
  out.innerHTML = '';

  const head = el('div');
  head.style.marginBottom = '12px';
  const title = el('div');
  title.innerHTML =
    `<b class="${m.radiant_win ? 'win' : 'lose'}">${m.radiant_name}</b>` +
    ` <span class="dim">${(m.score || []).join(' : ')}</span> ` +
    `<b class="${m.radiant_win === false ? 'win' : 'lose'}">${m.dire_name}</b>`;
  head.appendChild(title);
  head.appendChild(el('div', 'dim',
    [m.league, m.duration ? Math.round(m.duration / 60) + ' мин' : '', 'ID ' + m.match_id]
      .filter(Boolean).join(' · ')));
  out.appendChild(head);

  if (m.edge && m.edge.radiant_edge_pp !== undefined) {
    const e = m.edge.radiant_edge_pp;
    const box = el('div', 'note');
    const who = e > 0 ? m.radiant_name : m.dire_name;
    box.textContent =
      `По матчапам драфт был удобнее для ${who}: ${sign(Math.abs(e))} п.п. ` +
      `в сторону ${e > 0 ? 'Radiant' : 'Dire'}. ` +
      `Это оценка только по историческим матчапам — она не учитывает ни игроков, ни исполнение.`;
    out.appendChild(box);
  }

  if (m.has_draft) {
    ['radiant', 'dire'].forEach((side) => {
      const picks = m.draft_order.filter((d) => d.team === side && d.is_pick);
      const bans = m.draft_order.filter((d) => d.team === side && !d.is_pick);
      const wrap = el('div');
      wrap.style.marginBottom = '10px';
      wrap.appendChild(el('div', 'dim',
        (side === 'radiant' ? m.radiant_name : m.dire_name) + ' — пики'));
      wrap.appendChild(heroRow(picks));
      if (bans.length) {
        wrap.appendChild(el('div', 'dim', 'баны'));
        wrap.appendChild(heroRow(bans, true));
      }
      out.appendChild(wrap);
    });
  } else {
    out.appendChild(el('div', 'dim', 'Порядок драфта для этого матча недоступен.'));
  }

  [['radiant', m.radiant_name, m.radiant], ['dire', m.dire_name, m.dire]]
    .forEach(([, name, players]) => {
      if (!players || !players.length) return;
      const card = el('div');
      card.style.marginTop = '12px';
      card.appendChild(el('div', 'dim', name));
      const table = el('table');
      table.innerHTML =
        '<thead><tr><th>Герой</th><th>Игрок</th><th class="num">K/D/A</th>' +
        '<th class="num">GPM</th><th class="num">XPM</th><th class="num">Нетворс</th></tr></thead>';
      const tb = el('tbody');
      players.forEach((p) => {
        const tr = el('tr');
        const td = el('td');
        const cell = el('div', 'hero-cell');
        if (p.img) {
          const img = el('img');
          img.src = p.img;
          img.alt = p.name;
          cell.appendChild(img);
        }
        cell.appendChild(el('span', '', p.name || '—'));
        td.appendChild(cell);
        tr.appendChild(td);
        tr.appendChild(el('td', 'dim', p.player || '—'));
        tr.appendChild(el('td', 'num', (p.kda || []).join(' / ')));
        tr.appendChild(el('td', 'num dim', String(p.gpm ?? '—')));
        tr.appendChild(el('td', 'num dim', String(p.xpm ?? '—')));
        tr.appendChild(el('td', 'num dim',
          p.net_worth ? p.net_worth.toLocaleString('ru-RU') : '—'));
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      card.appendChild(table);
      out.appendChild(card);
    });
}

function heroRow(items, isBan) {
  const row = el('div', 'draft-row');
  items.forEach((d) => {
    if (!d.img) return;
    const img = el('img', isBan ? 'ban' : '');
    img.src = d.img;
    img.alt = d.name;
    img.title = (isBan ? 'бан: ' : '') + (d.name || '');
    row.appendChild(img);
  });
  return row;
}

boot();
