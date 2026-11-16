// Страница результатов: данные берутся из API /results/<id>/api/
(function () {
  const app = document.getElementById('results-app');
  if (!app) return;

  const MAX_PICK = 3;
  const state = { criterion: app.dataset.criterion || 'balanced', sort: '', priceMax: '', maxDays: '', shop: '' };
  const picked = new Set();
  const shops = new Set();
  let requestId = 0;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (v) => (v == null ? '—' : Math.round(v).toLocaleString('ru-RU') + ' ₽');
  const term = (i) => {
    const a = i.delivery_min_days, b = i.delivery_max_days;
    if (a == null || b == null) return '—';
    if (b === 1) return 'Завтра';
    return a === b ? a + ' дн.' : a + '–' + b + ' дн.';
  };
  const empty = '<span class="text-muted">нет данных</span>';
  const val = (v, fmt) => (v == null || v === '' || (Array.isArray(v) && !v.length) ? empty : fmt(v));

  function details(i) {
    return '<div class="row small">' +
      '<div class="col-md-4"><b>Оплата:</b> ' + val(i.payment_methods, (v) => esc([].concat(v).join(', '))) + '</div>' +
      '<div class="col-md-4"><b>Возврат:</b> ' + val(i.return_days, (v) => 'в течение ' + esc(v) + ' дн.') + '</div>' +
      '<div class="col-md-4"><b>Гарантия:</b> ' + val(i.warranty_months, (v) => esc(v) + ' мес.') + '</div></div>';
  }

  function card(i) {
    const rating = i.rating == null ? '' : ' · ★ ' + Number(i.rating).toFixed(1).replace('.', ',');
    return '<div class="offer' + (i.is_recommended ? ' recommended' : '') + '">' +
      '<div class="sel"><span class="heart" title="В избранное">♡</span>' +
      '<input type="checkbox" class="form-check-input pick" data-id="' + i.offer_id + '"' + (picked.has(i.offer_id) ? ' checked' : '') + '></div>' +
      '<div class="main"><div class="thumb">🖼</div><div>' +
      '<div class="title">' + esc(i.title) + '</div>' +
      '<div class="shop">' + esc(i.shop) + rating + '</div>' +
      '<div class="links"><button type="button" class="link" data-toggle="' + i.offer_id + '">Подробнее ▾</button>' +
      '<a target="_blank" rel="noopener" href="' + esc(i.url) + '">В магазин</a></div></div></div>' +
      '<div class="cell" data-label="Цена">' + money(i.price) + '</div>' +
      '<div class="cell" data-label="Доставка">' + money(i.delivery_price) + '</div>' +
      '<div class="cell" data-label="Срок">' + term(i) + '</div>' +
      '<div class="cell" data-label="Итого"><strong>' + money(i.total_price) + '</strong></div>' +
      '<div class="more d-none" id="d-' + i.offer_id + '">' + details(i) + '</div></div>';
  }

  function reco(r) {
    if (!r) { $('reco').innerHTML = ''; return; }
    const url = app.dataset.go.replace(/0\/$/, r.offer_id + '/');
    $('reco').innerHTML = '<div class="card border-success mb-3"><div class="card-body">' +
      '<div class="text-success small fw-semibold mb-1">Рекомендация</div>' +
      '<div class="fw-semibold">' + esc(r.shop) + ': ' + esc(r.title) + '</div>' +
      '<p class="mb-2">' + esc(r.explanation) + '</p>' +
      '<a class="btn btn-success btn-sm" target="_blank" rel="noopener" href="' + esc(url) + '">В магазин</a></div></div>';
  }

  function updateBar() { $('picked').textContent = 'Выбрано ' + picked.size + '/' + MAX_PICK; }

  function updateShops(items) {
    items.forEach((i) => shops.add(i.shop));
    $('shop').innerHTML = '<option value="">Все</option>' + [...shops].sort().map((s) =>
      '<option' + (s === state.shop ? ' selected' : '') + '>' + esc(s) + '</option>').join('');
  }

  function render(data) {
    state.criterion = data.criterion || state.criterion;
    updateShops(data.items);
    const items = data.items.filter((i) => !state.shop || i.shop === state.shop);
    reco(data.recommendation);
    $('rows').innerHTML = items.map(card).join('');
    $('state').textContent = data.status !== 'done' ? 'Поиск ещё выполняется…'
      : items.length ? '' : 'Ничего не найдено. Попробуйте изменить фильтры.';
    document.querySelectorAll('#criteria button').forEach((b) =>
      b.classList.toggle('active', b.dataset.criterion === state.criterion));
    updateBar();
  }

  async function load() {
    const id = ++requestId;
    const q = new URLSearchParams({ criterion: state.criterion });
    if (state.sort) q.set('sort', state.sort);
    if (state.priceMax !== '') q.set('price_max', state.priceMax);
    if (state.maxDays !== '') q.set('delivery_max_days', state.maxDays);
    $('state').textContent = 'Загрузка…';
    try {
      const resp = await fetch(app.dataset.api + '?' + q);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      if (id === requestId) render(data);   // игнорируем устаревшие ответы
    } catch (e) {
      if (id === requestId) $('state').innerHTML = '<span class="text-danger">Не удалось загрузить результаты. Обновите страницу.</span>';
    }
  }

  $('apply').addEventListener('click', () => {
    state.priceMax = $('priceMax').value; state.maxDays = $('maxDays').value;
    state.shop = $('shop').value; state.sort = $('sort').value; load();
  });
  $('reset').addEventListener('click', () => {
    $('priceMax').value = ''; $('maxDays').value = ''; $('shop').value = ''; $('sort').value = '';
    Object.assign(state, { priceMax: '', maxDays: '', shop: '', sort: '' }); load();
  });
  $('criteria').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-criterion]');
    if (b) { state.criterion = b.dataset.criterion; load(); }
  });
  $('rows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-toggle]');
    if (!b) return;
    const open = $('d-' + b.dataset.toggle).classList.toggle('d-none') === false;
    b.textContent = open ? 'Скрыть ▴' : 'Подробнее ▾';
  });
  $('rows').addEventListener('change', (e) => {
    if (!e.target.classList.contains('pick')) return;
    const id = Number(e.target.dataset.id);
    if (e.target.checked && picked.size >= MAX_PICK) { e.target.checked = false; return; }
    e.target.checked ? picked.add(id) : picked.delete(id);
    updateBar();
  });
  $('clear').addEventListener('click', () => {
    picked.clear(); document.querySelectorAll('.pick').forEach((c) => (c.checked = false)); updateBar();
  });

  load();
})();
