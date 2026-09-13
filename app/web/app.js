'use strict';

// Любая необработанная ошибка скрипта — на экран, крупно. Без этого скрипт
// падает молча, и страница выглядит как «вечная загрузка»: пустые списки
// и никакого объяснения. Именно так это и выглядело у пользователя.
window.addEventListener('error', (ev) => {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999;' +
    'background:#5a1f1a;color:#ffd9d2;padding:10px 16px;font:13px/1.4 monospace;' +
    'white-space:pre-wrap;border-bottom:2px solid #f0563a';
  box.textContent = 'Ошибка скрипта: ' + (ev.message || ev.error) +
    (ev.lineno ? '  (строка ' + ev.lineno + ')' : '') +
    '\nОбновите страницу с очисткой кэша: Ctrl+F5. Если не помогло — пришлите этот текст.';
  document.body.appendChild(box);
});

// ---------------------------------------------------------------- состояние
// Герои, которых пользователь не играет: их не предлагаем никогда.
// Список живёт в localStorage; по умолчанию — Wraith King, по просьбе владельца.
const NEVER_DEFAULT = [42];
const NEVER_KEY = 'draft-helper.never';

function loadNever() {
  try {
    const raw = localStorage.getItem(NEVER_KEY);
    if (raw === null) return NEVER_DEFAULT.slice();
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list.map(Number).filter(Number.isFinite) : [];
  } catch (e) {
    return NEVER_DEFAULT.slice();
  }
}

function saveNever() {
  try { localStorage.setItem(NEVER_KEY, JSON.stringify(state.draft.never)); }
  catch (e) { /* приватный режим — просто не сохранится */ }
}

const state = {
  heroes: [],
  byId: new Map(),
  brackets: [],
  roles: [],
  draft: { enemy: [], ally: [], banned: [], never: loadNever() },
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

// Если элемента нет — это рассинхрон страницы и скрипта (обычно старый
// index.html из кэша браузера). Говорим об этом прямо, а не падаем на null.
const $ = (sel) => {
  const node = document.querySelector(sel);
  if (!node) {
    throw new Error('на странице нет элемента ' + sel +
      ' — страница и скрипт разных версий, обновите с очисткой кэша (Ctrl+F5)');
  }
  return node;
};
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
// «—» для отсутствующего значения; ноль — настоящее значение, его не трогаем
const orDash = (v) => (v === null || v === undefined ? '—' : v);
const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'dim');

// ---------------------------------------------------------------- вкладки
// Только настоящие вкладки — с data-view. Класс .tab используется и для
// оформления обычных кнопок; ловить их клики здесь нельзя.
document.querySelectorAll('.tabs .tab[data-view]').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tabs .tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    tab.classList.add('active');
    $('#view-' + tab.dataset.view).classList.add('active');
    if (tab.dataset.view === 'meta') loadMeta();
    if (tab.dataset.view === 'tournaments') loadTournaments();
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
    $('#src-label').textContent = (data.snapshot
      ? 'источник: ' + data.source + ' (снимок)'
      : 'источник: ' + data.source) + ' · v' + (data.version || '?');
    if (data.snapshot_note) {
      const note = el('div', 'dim', data.snapshot_note);
      note.style.marginBottom = '8px';
      $('#rec-out').parentNode.insertBefore(note, $('#rec-out'));
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
    fillMyHeroSelect();
    visionBoot();
    pollGsi();
    me.gsiTimer = setInterval(pollGsi, 3000);
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

// Занятые в текущем драфте. Список «не предлагать» сюда не входит:
// врага Wraith King нужно засчитать во враги, даже если сами мы его не играем.
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
  const caps = { enemy: 5, ally: 5, banned: 14, never: 127 };
  if (list.length >= caps[state.mode]) return;
  // в драфте герой может быть только в одном списке; «не предлагать» —
  // отдельный список, туда можно добавить кого угодно, лишь бы не дважды
  const taken = state.mode === 'never' ? new Set(list) : usedIds();
  if (taken.has(id)) return;
  list.push(id);
  if (state.mode === 'never') saveNever();
  renderSlots();
  renderHeroGrid();
  refreshRecommendations();
}

function removeHero(kind, id) {
  state.draft[kind] = state.draft[kind].filter((x) => x !== id);
  if (kind === 'never') saveNever();
  renderSlots();
  renderHeroGrid();
  refreshRecommendations();
}

function renderSlots() {
  [['enemy', '#slots-enemy'], ['ally', '#slots-ally'],
   ['banned', '#slots-banned'], ['never', '#slots-never']]
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

['#bracket', '#position', '#limit', '#tour-weight', '#tour-period'].forEach((sel) =>
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
        // «не предлагать» для сервера — те же баны: их просто нет в выдаче
        banned: state.draft.banned.concat(state.draft.never),
        bracket: $('#bracket').value,
        position: $('#position').value,
        limit: Number($('#limit').value),
        tour_weight: Number($('#tour-weight').value),
        tour_months: Number($('#tour-period').value),
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
  if (data.tour_note) out.appendChild(el('div', 'error', data.tour_note));
  if (!rows.length) {
    out.appendChild(el('div', 'empty-hint', 'Ничего не подошло под фильтры.'));
    return;
  }
  const withTour = data.tour_weight > 0;
  const max = Math.max(...rows.map((r) => Math.abs(r.score_pp)), 1);
  const table = el('table');
  table.innerHTML = `<thead><tr>
      <th>#</th><th>Герой</th><th class="num">Балл</th>
      <th class="num">Матчапы</th><th class="num">База</th>
      ${withTour ? '<th class="num">Турниры</th>' : ''}
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
    if (withTour) {
      const tp = r.tour_pp || 0;
      tr.appendChild(el('td', 'num ' + cls(tp), sign(tp)));
    }
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
    'Балл в процентных пунктах. Матчапы — вклад контрпика, База — сила героя в выбранном ранге. ' +
    (withTour
      ? `Турниры — востребованность и винрейт у про за выбранный период (${data.tour_matches} матчей), ` +
        `вес ${data.tour_weight}: чем выше, тем сильнее турнирная мета перевешивает остальное. `
      : '') +
    'Полупрозрачные пары — менее 15 игр в выборке. ' +
    'Сглаживание K = ' + orDash(data.k_shrink) + '.';
  out.appendChild(legend);
}

// ---------------------------------------------------------------- мой герой и сборка
const me = { heroId: null, gsiTimer: null, gsiHero: null, gsiTeam: null };

function fillMyHeroSelect() {
  const sel = $('#my-hero');
  const keep = sel.value;
  sel.innerHTML = '<option value="">— не выбран —</option>';
  state.heroes.forEach((h) => {
    const o = document.createElement('option');
    o.value = h.id;
    o.textContent = h.name;
    sel.appendChild(o);
  });
  if (keep) sel.value = keep;
}

$('#my-hero').addEventListener('change', () => {
  setMyHero(Number($('#my-hero').value) || null, 'вручную');
});

function setMyHero(id, how) {
  if (me.heroId === id) return;
  me.heroId = id;
  $('#my-hero').value = id ? String(id) : '';
  // свой герой - это и союзник в драфте
  if (id && !usedIds().has(id) && state.draft.ally.length < 5) {
    state.draft.ally.push(id);
    renderSlots();
    renderHeroGrid();
    refreshRecommendations();
  }
  loadBuild(how);
}

async function loadBuild(how) {
  const out = $('#build-out');
  if (!me.heroId) {
    out.className = 'empty-hint';
    out.textContent = 'Выберите своего героя — покажу стартовый закуп и порядок сборки из турнирных матчей.';
    return;
  }
  const hero = state.byId.get(me.heroId);
  out.className = 'loading';
  out.textContent = `Собираю сборку ${hero ? hero.name : ''} по турнирным матчам…`;
  try {
    const b = await api(`/api/build?hero=${me.heroId}&months=${$('#tour-period').value}`);
    out.className = '';
    renderBuild(out, b, hero, how);
  } catch (e) { out.className = ''; showError(out, e); }
}

function renderBuild(out, b, hero, how) {
  out.innerHTML = '';
  const head = el('div');
  head.style.marginBottom = '8px';
  const title = el('span', '', (hero ? hero.name : '') + ' ');
  title.style.fontWeight = '600';
  head.appendChild(title);
  head.appendChild(el('span', 'dim',
    b.games
      ? `— ${b.games} турнирных игр за ${b.months} мес, винрейт ${b.winrate}%` +
        (how ? ` · герой определён: ${how}` : '')
      : '— в турнирах за этот период герой не встречался'));
  out.appendChild(head);
  if (!b.games) return;

  const block = el('div', 'items');
  const line = (title, nodes) => {
    if (!nodes.length) return;
    const row = el('div', 'items-row');
    row.appendChild(el('span', 'dim items-title', title));
    nodes.forEach((n) => row.appendChild(n));
    block.appendChild(row);
  };
  line('старт', b.start.map((it) =>
    itemIcon(it, it.count > 1 ? `×${it.count}` : `${it.share}%`)));
  line('сборка', b.order.map((it) => itemIcon(it, `${it.minute}м`)));
  line('ситуативно', b.situational.map((it) => itemIcon(it, `${it.share}%`)));
  line('итог', b.final.map((it) => itemIcon(it, `${it.share}%`)));
  out.appendChild(block);

  const legend = el('div', 'dim');
  legend.style.marginTop = '6px';
  legend.textContent = 'Старт — куплено до рога хотя бы в 40% игр, число — сколько штук. ' +
    'Сборка — предметы дороже 500 золота из ≥25% игр по медианной минуте покупки. ' +
    'Ситуативно — дорогие предметы из 10–25% игр. Итог — что чаще всего в инвентаре к концу.';
  out.appendChild(legend);
}

// --- Game State Integration: игра сама сообщает героя и сторону -----------
async function pollGsi() {
  try {
    const s = await api('/api/gsi/state');
    const box = $('#gsi-status');
    if (!s.received) {
      box.textContent = 'не подключена';
      box.className = 'dim';
    } else if (!s.alive) {
      box.textContent = `молчит ${Math.round((Date.now() / 1000 - s.last_at))} с`;
      box.className = 'dim';
    } else {
      const parts = [];
      if (s.hero_localized) parts.push(s.hero_localized);
      if (s.team) parts.push(s.team === 'radiant' ? 'Radiant' : 'Dire');
      if (s.game_state) parts.push(s.game_state.replace('DOTA_GAMERULES_STATE_', '').toLowerCase());
      box.textContent = parts.join(' · ') || 'подключена';
      box.className = 'pos';
    }
    if (s.hero_id && s.hero_id !== me.gsiHero) {
      me.gsiHero = s.hero_id;
      setMyHero(s.hero_id, 'из игры');
    }
    // сторона из игры: в верхней полоске Radiant слева, Dire справа
    if (s.team && s.team !== me.gsiTeam) {
      me.gsiTeam = s.team;
      const want = s.team === 'radiant' ? 'left' : 'right';
      if ($('#vis-side').value !== want) {
        $('#vis-side').value = want;
        $('#vis-side').dispatchEvent(new Event('change'));
      }
    }
  } catch (e) { /* сервер занят - подождём */ }
}

$('#gsi-install').addEventListener('click', async () => {
  const box = $('#gsi-status');
  box.textContent = 'ищу папку Dota…';
  try {
    const r = await api('/api/gsi/install', { method: 'POST' });
    box.textContent = r.message + (r.path ? ` (${r.path})` : '');
    box.className = r.path ? 'pos' : 'neg';
  } catch (e) { box.textContent = 'ошибка: ' + e.message; box.className = 'neg'; }
});

// ---------------------------------------------------------------- чтение экрана
const vision = { timer: null, running: false, lastKey: '', lastState: null };

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
    const loaded = st.templates_loaded;
    if (ic.ready && loaded !== undefined && loaded < ic.have) {
      // файлы есть, а распознаватель их не прочитал — раньше это было
      // невидимо и выглядело как «не распознаёт»
      box.innerHTML = '';
      box.appendChild(el('div', 'error',
        `Файлов портретов ${ic.have}, но в распознаватель загружено только ${loaded}. ` +
        `Папка: ${st.assets_dir}. Пришлите этот текст.`));
    } else {
      box.textContent = ic.ready
        ? `Готово. Эталонов героев: ${ic.have} из ${ic.total}, загружено ${loaded}.`
        : `Портретов героев: ${ic.have} из ${ic.total}. Они скачаются сами при ` +
          `первом запуске слежения — это займёт около минуты. Можно и заранее, ` +
          `кнопкой «Скачать портреты».`;
    }
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
  const out = $('#vision-out');
  const delay = Number($('#vis-delay').value);
  try {
    await visionConfig();
    // обратный отсчёт: чтобы человек успел переключиться в игру,
    // иначе в кадр попадает браузер с этой самой кнопкой
    for (let left = delay; left > 0; left--) {
      out.innerHTML = `<div class="loading">Переключитесь в игру. Снимок через ${left} с…</div>`;
      await new Promise((r) => setTimeout(r, 1000));
    }
    out.innerHTML = '<div class="loading">Ищу героев на экране…</div>';
    renderVision(await api('/api/vision/scan', { method: 'POST' }));
  } catch (e) { showError(out, e); }
});

// Смена стороны — пересобрать драфт из последнего распознанного заново:
// иначе союзники, уже попавшие во враги при неверной стороне, там и останутся.
$('#vis-side').addEventListener('change', () => {
  if (!vision.lastState) return;
  state.draft.enemy = [];
  state.draft.ally = [];
  vision.lastKey = '';
  renderSlots();
  renderHeroGrid();
  renderVision(vision.lastState);
});

// Проверка на файле: отделяет «не захватывает экран» от «не распознаёт».
$('#vis-file').addEventListener('change', async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const out = $('#vision-out');
  out.innerHTML = `<div class="loading">Распознаю ${file.name}…</div>`;
  try {
    const res = await fetch('/api/vision/recognize', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    renderVision(data);
  } catch (err) { showError(out, err); }
  e.target.value = '';
});

// Самопроверка: распознаватель ищет свои же эталоны на синтетическом кадре.
// Провал здесь — поломка самого распознавания, а не захвата или игры.
$('#vis-selftest').addEventListener('click', async () => {
  const out = $('#vision-out');
  out.innerHTML = '<div class="loading">Самопроверка распознавания…</div>';
  try {
    const r = await api('/api/vision/selftest');
    out.innerHTML = '';
    if (r.ok) {
      out.appendChild(el('div', 'note',
        `Самопроверка пройдена: ${r.found} из ${r.placed} эталонов найдено за ${r.seconds} с. ` +
        'Распознавание исправно — если вживую не находит, дело в захвате экрана: ' +
        'смотрите превью «Что видит приложение».'));
    } else {
      out.appendChild(el('div', 'error',
        `Самопроверка НЕ пройдена: найдено ${r.found} из ${r.placed}` +
        (r.missing && r.missing.length ? `, потеряны: ${r.missing.join(', ')}` : '') +
        (r.reason ? `. ${r.reason}` : '') + '. Пришлите этот текст.'));
    }
  } catch (e) { showError(out, e); }
});

function showFrame() {
  const box = $('#vision-frame-box');
  const img = $('#vis-frame');
  box.hidden = false;
  img.src = '/api/vision/frame.jpg?t=' + Date.now();
}

$('#vis-icons').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  $('#vision-status').textContent =
    'Скачиваю портреты героев (127 штук), это займёт около минуты…';
  try {
    const r = await api('/api/vision/icons', { method: 'POST' });
    $('#vision-status').textContent =
      `Портретов на диске: ${r.have} из ${r.total}` +
      (r.failed ? `, не удалось скачать: ${r.failed}. Причина: ${r.reason}` : '') +
      (r.ready ? '. Можно включать слежение.' : '');
  } catch (err) { showError($('#vision-status'), err); }
  btn.disabled = false;
});

async function pollVision() {
  if (!vision.running) return;
  try { renderVision(await api('/api/vision/state')); }
  catch (e) { /* сеть моргнула — ждём следующего опроса */ }
}

// Стороны делятся по центру экрана. Делить по середине между найденными
// портретами нельзя: пока враги не выбрали героев, найдена одна команда,
// и такой делитель режет её пополам.
function splitBySide(heroes, frameWidth) {
  const side = $('#vis-side').value;
  if (side === 'none') return { enemy: heroes, ally: [] };
  const mid = frameWidth ? frameWidth / 2 : null;
  if (!mid) return { enemy: heroes, ally: [] };
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
    ` · распознано: ${(vs.heroes || []).length}` +
    (vs.frame_brightness !== null && vs.frame_brightness !== undefined
      ? ` · яркость кадра ${vs.frame_brightness}` : '');
  out.appendChild(head);

  if (vs.last_error) out.appendChild(el('div', 'error', vs.last_error));
  if (vs.frame_hint) out.appendChild(el('div', 'error', vs.frame_hint));
  if (vs.scans) showFrame();

  const heroes = vs.heroes || [];
  if (!heroes.length) {
    out.appendChild(el('div', 'empty-hint',
      'Героев на экране не видно. Откройте экран драфта и нажмите «Сканировать сейчас».'));
    return;
  }

  const { enemy, ally } = splitBySide(heroes, vs.frame_width);
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
    if (isAlly) {
      chip.style.borderColor = 'var(--radiant)';
      // на своём герое - кнопка «это я»: сразу считается сборка
      const meBtn = el('button', 'tab', me.heroId === h.hero_id ? 'это я ✓' : 'это я');
      meBtn.style.padding = '2px 8px';
      meBtn.style.fontSize = '11px';
      meBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        setMyHero(h.hero_id, 'кнопка «это я»');
        renderVision(vs);
      });
      chip.appendChild(meBtn);
    }
    row.appendChild(chip);
  });
  out.appendChild(row);

  // подставляем распознанное в драфт, не трогая то, что выбрано руками
  vision.lastState = vs;
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
['#meta-bracket', '#meta-position'].forEach((sel) =>
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
      position: $('#meta-position').value,
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

const metaKey = () => $('#meta-bracket').value + '|' + $('#meta-position').value;

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

// ---------------------------------------------------------------- турниры
const tour = { rows: [], total: 0, leaguesFor: null };

['#tour-months', '#tour-tier', '#tour-league'].forEach((sel) =>
  $(sel).addEventListener('change', () => loadTournaments(true)));
$('#tour-sort').addEventListener('change', () => renderTournaments());

async function loadTournamentLeagues() {
  const months = $('#tour-months').value;
  if (tour.leaguesFor === months) return;
  const data = await api('/api/tournaments/leagues?months=' + months);
  tour.leaguesFor = months;
  const sel = $('#tour-league');
  const keep = sel.value;
  sel.innerHTML = '';
  const all = document.createElement('option');
  all.value = ''; all.textContent = 'Все';
  sel.appendChild(all);
  data.leagues.forEach((l) => {
    const o = document.createElement('option');
    o.value = l.leagueid;
    o.textContent = `${l.name} — ${l.matches} матчей (${l.tier})`;
    sel.appendChild(o);
  });
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

let tourLoaded = false;
async function loadTournaments(force) {
  if (tourLoaded && !force) return;
  const out = $('#tour-out');
  out.className = 'loading';
  out.textContent = 'Считаю по базе турнирных матчей, это может занять полминуты…';
  try {
    await loadTournamentLeagues();
    const q = new URLSearchParams({
      months: $('#tour-months').value,
      tier: $('#tour-tier').value,
      league: $('#tour-league').value,
    });
    const data = await api('/api/tournaments?' + q);
    tour.rows = data.rows;
    tour.total = data.total_matches;
    tourLoaded = true;
    out.className = 'scroll';
    renderTournaments();
  } catch (e) {
    out.className = '';
    showError(out, e);
  }
}

function renderTournaments() {
  const out = $('#tour-out');
  const key = $('#tour-sort').value;
  const rows = tour.rows.slice().sort((a, b) => {
    const av = a[key] === null ? -1 : a[key];
    const bv = b[key] === null ? -1 : b[key];
    return bv - av;
  });
  $('#tour-summary').textContent =
    `Матчей в выборке: ${tour.total}. Пик-рейт и бан-рейт — доля матчей, в которых ` +
    'героя взяли или забанили; спорность — их сумма. Винрейт считается только по пикам.';
  out.innerHTML = '';
  if (!rows.length) {
    out.appendChild(el('div', 'empty-hint', 'За этот период матчей нет.'));
    return;
  }
  const table = el('table');
  table.innerHTML = `<thead><tr>
    <th>#</th><th>Герой</th><th class="num">Спорность</th><th class="num">Пики</th>
    <th class="num">Пик-рейт</th><th class="num">Баны</th><th class="num">Бан-рейт</th>
    <th class="num">Винрейт</th></tr></thead>`;
  const tb = el('tbody');
  rows.forEach((r, i) => {
    const tr = el('tr');
    tr.appendChild(el('td', 'dim', String(i + 1)));
    const td = el('td');
    const cell = el('div', 'hero-cell');
    if (r.img) {
      const img = el('img'); img.src = r.img; img.alt = r.name; img.loading = 'lazy';
      cell.appendChild(img);
    }
    cell.appendChild(el('span', '', r.name || String(r.id)));
    td.appendChild(cell);
    tr.appendChild(td);
    tr.appendChild(el('td', 'num', r.contest_rate.toFixed(1) + '%'));
    tr.appendChild(el('td', 'num dim', String(r.picks)));
    tr.appendChild(el('td', 'num dim', r.pick_rate.toFixed(1) + '%'));
    tr.appendChild(el('td', 'num dim', String(r.bans)));
    tr.appendChild(el('td', 'num dim', r.ban_rate.toFixed(1) + '%'));
    const wr = el('td', 'num', r.winrate === null ? '—' : r.winrate.toFixed(1) + '%');
    if (r.winrate !== null && r.picks < 10) wr.classList.add('dim');
    wr.title = r.picks < 10 ? 'меньше 10 пиков — винрейт ненадёжен' : '';
    tr.appendChild(wr);
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
  out.innerHTML = '<div class="loading">Загружаю матч: драфт, игроки, закупы — три коротких ' +
    'запроса к базе OpenDota…</div>';
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
        tr.appendChild(el('td', 'num dim', String(orDash(p.gpm))));
        tr.appendChild(el('td', 'num dim', String(orDash(p.xpm))));
        tr.appendChild(el('td', 'num dim',
          p.net_worth ? p.net_worth.toLocaleString('ru-RU') : '—'));
        tb.appendChild(tr);

        // строка с предметами: старт, сборка по минутам, итог
        if (p.items) {
          const tri = el('tr');
          const tdi = el('td');
          tdi.colSpan = 6;
          tdi.appendChild(itemsBlock(p.items));
          tri.appendChild(tdi);
          tb.appendChild(tri);
        }
      });
      table.appendChild(tb);
      card.appendChild(table);
      out.appendChild(card);
    });
}

function itemIcon(it, label) {
  const wrap = el('span', 'item');
  if (it.img) {
    const img = el('img');
    img.src = it.img;
    img.alt = it.dname;
    img.loading = 'lazy';
    wrap.appendChild(img);
  } else {
    wrap.appendChild(el('span', 'dim', it.dname));
  }
  if (label !== undefined) wrap.appendChild(el('span', 'item-min', label));
  wrap.title = it.dname + (it.cost ? ` — ${it.cost} зол.` : '') +
    (label !== undefined ? ` — ${label} мин` : '');
  return wrap;
}

function itemsBlock(items) {
  const box = el('div', 'items');
  const line = (title, nodes) => {
    if (!nodes.length) return;
    const row = el('div', 'items-row');
    row.appendChild(el('span', 'dim items-title', title));
    nodes.forEach((n) => row.appendChild(n));
    box.appendChild(row);
  };
  if (!items.has_log && !items.final.length) {
    box.appendChild(el('span', 'dim', 'предметы недоступны: матч не разобран'));
    return box;
  }
  line('старт', items.start.map((it) => itemIcon(it)));
  line('сборка', items.build.map((it) => itemIcon(it, it.minute)));
  const fin = items.final.map((it) => itemIcon(it));
  if (items.neutral) fin.push(itemIcon(items.neutral, 'нейтр.'));
  line('итог', fin);
  return box;
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
