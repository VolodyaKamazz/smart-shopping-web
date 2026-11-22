// Страница результатов: данные берутся из API /results/<id>/api/
(function () {
  const app = document.getElementById('results-app');
  if (!app) return;

  const MAX_PICK = 3;
  const state = { criterion: app.dataset.criterion || 'balanced', sort: '', priceMin: '', priceMax: '', maxDays: '', shop: '' };
  const picked = new Set();
  const favState = new Map();
  const byId = new Map();
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

  function isFav(i) { return favState.has(i.product_id) ? favState.get(i.product_id) : !!i.is_favorite; }

  function heart(i) {
    if (i.product_id == null) return '<span class="heart" style="opacity:.3" title="Товара нет в каталоге">♡</span>';
    const on = isFav(i);
    return '<span class="heart" style="cursor:pointer" data-product="' + i.product_id + '" data-offer="' + i.offer_id +
      '" title="' + (on ? 'Убрать из избранного' : 'В избранное') + '">' + (on ? '♥' : '♡') + '</span>';
  }

  function card(i) {
    const rating = i.rating == null ? '' : ' · ★ ' + Number(i.rating).toFixed(1).replace('.', ',');
    return '<div class="offer' + (i.is_recommended ? ' recommended' : '') + '">' +
      '<div class="sel">' + heart(i) +
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

  const kv = (k, v) => '<div class="d-flex justify-content-between mb-1"><span>' + k + '</span><span>' + v + '</span></div>';
  function cmpCard(i, best) {
    const rating = i.rating == null ? '' : '★ ' + Number(i.rating).toFixed(1).replace('.', ',');
    return '<div class="col-md-4"><div class="cmp' + (best ? ' best' : '') + '">' +
      (best ? '<div class="best-tag">★ Лучший вариант</div>' : '') +
      '<div class="cmp-img">🖼</div>' +
      '<div class="d-flex justify-content-between align-items-start mb-1"><span>' + esc(i.title) + '</span>' + heart(i) + '</div>' +
      '<div class="d-flex justify-content-between mb-2"><span>' + esc(i.shop) + '</span><span>' + rating + '</span></div><hr>' +
      kv('Цена', money(i.price)) + kv('Доставка', money(i.delivery_price)) + kv('Срок', term(i)) + '<hr>' +
      kv('Итого', '<strong>' + money(i.total_price) + '</strong>') +
      '<a class="btn-find d-block text-center text-decoration-none mt-2" target="_blank" rel="noopener" href="' + esc(i.url) + '">В магазин</a></div></div>';
  }
  function showCompare(on) {
    if (on) {
      const list = [...picked].map((id) => byId.get(id)).filter(Boolean);
      if (list.length < 2) return;
      const best = list.reduce((a, b) => ((b.total_price == null ? Infinity : b.total_price) < (a.total_price == null ? Infinity : a.total_price) ? b : a));
      $('cmp-cards').innerHTML = list.map((i) => cmpCard(i, i === best)).join('');
    }
    $('dash').classList.toggle('d-none', on);
    $('compare-view').classList.toggle('d-none', !on);
    window.scrollTo(0, 0);
  }

  const skeleton = '<div class="offer placeholder-glow"><span class="placeholder col-12" style="height:4.2rem"></span></div>'.repeat(3);
  const stateBox = (title, text, btn) => '<div class="state-box"><div class="fw-semibold mb-1">' + title + '</div><div class="text-muted mb-3">' + text + '</div>' + btn + '</div>';

  function reco(r) {
    if (!r) { $('reco').innerHTML = ''; return; }
    const url = app.dataset.go.replace(/0\/$/, r.offer_id + '/');
    $('reco').innerHTML = '<div class="card border-success mb-3"><div class="card-body">' +
      '<div class="text-success small fw-semibold mb-1">Рекомендация</div>' +
      '<div class="fw-semibold">' + esc(r.shop) + ': ' + esc(r.title) + '</div>' +
      '<p class="mb-2">' + esc(r.explanation) + '</p>' +
      '<a class="btn btn-success btn-sm" target="_blank" rel="noopener" href="' + esc(url) + '">В магазин</a></div></div>';
  }

  function updateBar() {
    $('picked').textContent = 'Выбрано ' + picked.size + '/' + MAX_PICK;
    $('compare').disabled = picked.size < 2;
  }

  function updateShops(shops) {
    $('shop').innerHTML = '<option value="">Все</option>' + (shops || []).map((s) =>
      '<option value="' + esc(s.id) + '"' + (String(s.id) === state.shop ? ' selected' : '') + '>' +
      esc(s.name) + ' (' + s.count + ')</option>').join('');
  }

  function render(data) {
    state.criterion = data.criterion || state.criterion;
    updateShops(data.shops);
    const items = data.items;
    items.forEach((i) => byId.set(i.offer_id, i));
    reco(data.recommendation);
    $('rows').innerHTML = items.map(card).join('');
    $('state').innerHTML = data.status !== 'done' ? stateBox('Поиск ещё выполняется…', 'Обновите страницу через несколько секунд.', '')
      : items.length ? '' : stateBox('Ничего не найдено', 'Попробуйте изменить или сбросить фильтры.', '<button type="button" class="btn-find" data-act="reset">Сбросить фильтры</button>');
    document.querySelectorAll('#criteria button').forEach((b) =>
      b.classList.toggle('active', b.dataset.criterion === state.criterion));
    updateBar();
  }

  async function load() {
    const id = ++requestId;
    const q = new URLSearchParams({ criterion: state.criterion });
    if (state.sort) q.set('sort', state.sort);
    if (state.priceMin !== '') q.set('price_min', state.priceMin);
    if (state.priceMax !== '') q.set('price_max', state.priceMax);
    if (state.shop !== '') q.set('shop', state.shop);
    if (state.maxDays !== '') q.set('delivery_max_days', state.maxDays);
    $('state').innerHTML = '';
    $('rows').innerHTML = skeleton;
    try {
      const resp = await fetch(app.dataset.api + '?' + q);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      if (id === requestId) render(data);   // игнорируем устаревшие ответы
    } catch (e) {
      if (id === requestId) { $('rows').innerHTML = ''; $('state').innerHTML = stateBox('Не удалось загрузить результаты', 'Проверьте соединение и попробуйте снова.', '<button type="button" class="btn-find" data-act="retry">Повторить</button>'); }
    }
  }

  $('apply').addEventListener('click', () => {
    state.priceMin = $('priceMin').value; state.priceMax = $('priceMax').value; state.maxDays = $('maxDays').value;
    state.shop = $('shop').value; state.sort = $('sort').value; load();
  });
  function resetFilters() {
    $('priceMin').value = ''; $('priceMax').value = ''; $('maxDays').value = ''; $('shop').value = ''; $('sort').value = '';
    Object.assign(state, { priceMin: '', priceMax: '', maxDays: '', shop: '', sort: '' }); load();
  }
  $('reset').addEventListener('click', resetFilters);
  $('compare').addEventListener('click', () => showCompare(true));
  $('cmp-back').addEventListener('click', () => showCompare(false));
  $('criteria').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-criterion]');
    if (b) { state.criterion = b.dataset.criterion; load(); }
  });
  app.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-act]');
    if (act) { act.dataset.act === 'retry' ? load() : resetFilters(); return; }
    const h = e.target.closest('.heart[data-product]');
    if (h) {
      const pid = Number(h.dataset.product);
      const body = new URLSearchParams({ offer_id: h.dataset.offer });
      try {
        const resp = await fetch(app.dataset.fav.replace('/0/', '/' + pid + '/'), {
          method: 'POST', body,
          headers: { 'X-CSRFToken': app.dataset.csrf, 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        favState.set(pid, data.is_favorite);
        document.querySelectorAll('.heart[data-product="' + pid + '"]').forEach((el) => {
          el.textContent = data.is_favorite ? '♥' : '♡';
          el.title = data.is_favorite ? 'Убрать из избранного' : 'В избранное';
        });
      } catch (err) {
        $('state').innerHTML = '<span class="text-danger">Не удалось обновить избранное.</span>';
      }
      return;
    }
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
