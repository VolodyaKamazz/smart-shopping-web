// Страница результатов: данные берутся из API /results/<id>/api/
(function () {
  const app = document.getElementById('results-app');
  if (!app) return;

  const state = { criterion: app.dataset.criterion || 'balanced', sort: '', priceMax: '', fast: false };
  let requestId = 0;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (v) => (v == null ? '—' : Math.round(v).toLocaleString('ru-RU') + ' ₽');
  const delivery = (i) => (i.delivery_price == null ? '—' : i.delivery_price === 0 ? 'бесплатно' : money(i.delivery_price));
  const term = (i) => {
    const a = i.delivery_min_days, b = i.delivery_max_days;
    return a == null || b == null ? '—' : a === b ? a + ' дн.' : a + '–' + b + ' дн.';
  };
  const empty = '<span class="text-muted">нет данных</span>';
  const val = (v, fmt) => (v == null || v === '' || (Array.isArray(v) && !v.length) ? empty : fmt(v));

  function details(i) {
    return '<div class="row small">' +
      '<div class="col-md-4"><b>Оплата:</b> ' + val(i.payment_methods, (v) => esc([].concat(v).join(', '))) + '</div>' +
      '<div class="col-md-4"><b>Возврат:</b> ' + val(i.return_days, (v) => 'в течение ' + esc(v) + ' дн.') + '</div>' +
      '<div class="col-md-4"><b>Гарантия:</b> ' + val(i.warranty_months, (v) => esc(v) + ' мес.') + '</div></div>';
  }

  function row(i) {
    return '<tr class="' + (i.is_recommended ? 'table-success' : '') + '">' +
      '<td><div class="fw-semibold">' + esc(i.shop) + '</div><div class="small text-muted">' + esc(i.title) + '</div></td>' +
      '<td>' + money(i.price) + '</td><td>' + delivery(i) + '</td><td>' + term(i) + '</td>' +
      '<td><strong>' + money(i.total_price) + '</strong></td>' +
      '<td>' + (i.rating == null ? '—' : '★ ' + Number(i.rating).toFixed(1)) + '</td>' +
      '<td class="text-nowrap"><button type="button" class="btn btn-sm btn-outline-secondary" data-toggle="' + i.offer_id + '" aria-expanded="false">Подробнее</button> ' +
      '<a class="btn btn-sm btn-outline-success" target="_blank" rel="noopener" href="' + esc(i.url) + '">В магазин</a></td></tr>' +
      '<tr class="d-none" id="d-' + i.offer_id + '"><td colspan="7" class="bg-light">' + details(i) + '</td></tr>';
  }

  function reco(r) {
    if (!r) { $('reco').innerHTML = ''; return; }
    const url = app.dataset.go.replace(/0\/$/, r.offer_id + '/');
    $('reco').innerHTML = '<div class="card border-success mb-3"><div class="card-body">' +
      '<div class="text-success small fw-semibold mb-1">Рекомендация</div>' +
      '<h5 class="card-title">' + esc(r.shop) + ': ' + esc(r.title) + '</h5>' +
      '<p class="card-text">' + esc(r.explanation) + '</p>' +
      '<a class="btn btn-success btn-sm" target="_blank" rel="noopener" href="' + esc(url) + '">В магазин</a></div></div>';
  }

  function render(data) {
    state.criterion = data.criterion || state.criterion;
    reco(data.recommendation);
    $('rows').innerHTML = data.items.map(row).join('');
    $('state').textContent = data.status !== 'done' ? 'Поиск ещё выполняется…'
      : data.count ? 'Найдено предложений: ' + data.count
      : 'Ничего не найдено. Попробуйте изменить фильтры.';
    document.querySelectorAll('#criteria button').forEach((b) =>
      b.classList.toggle('active', b.dataset.criterion === state.criterion));
    document.querySelectorAll('th.sortable').forEach((th) =>
      th.classList.toggle('active', th.dataset.sort === state.sort));
  }

  async function load() {
    const id = ++requestId;
    const q = new URLSearchParams({ criterion: state.criterion });
    if (state.sort) q.set('sort', state.sort);
    if (state.priceMax !== '') q.set('price_max', state.priceMax);
    if (state.fast) q.set('delivery_max_days', '1');
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

  $('criteria').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-criterion]');
    if (b) { state.criterion = b.dataset.criterion; load(); }
  });
  document.querySelector('thead').addEventListener('click', (e) => {
    const th = e.target.closest('th.sortable');
    if (th) { state.sort = state.sort === th.dataset.sort ? '' : th.dataset.sort; load(); }
  });
  $('rows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-toggle]');
    if (!b) return;
    const open = $('d-' + b.dataset.toggle).classList.toggle('d-none') === false;
    b.setAttribute('aria-expanded', open);
    b.textContent = open ? 'Скрыть' : 'Подробнее';
  });
  let timer;
  $('priceMax').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.priceMax = e.target.value; load(); }, 400);
  });
  $('fastDelivery').addEventListener('change', (e) => { state.fast = e.target.checked; load(); });

  load();
})();
