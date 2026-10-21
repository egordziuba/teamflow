'use strict';
(() => {
  const M = globalThis.TeamflowModel;
  const $ = id => document.getElementById(id);
  const state = {snapshot:null, selected:null, inFlight:false, queued:false, timer:null, lastOK:0, error:false, navKey:null, detailKey:null, expanded:new Map()};
  const dateFormat = new Intl.DateTimeFormat('ru-RU', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'});
  function time(value) { const date = new Date(value); return value && Number.isFinite(date.getTime()) ? dateFormat.format(date) : 'Не записано'; }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function tone(value) { return ['completed','pending','failed','planned','idle','blocked','accepted','incomplete','evidence_mismatch'].includes(value) ? value : 'unknown'; }
  function badge(label, value) { return el('span', `badge ${tone(value)}`, label); }
  function roleTitle(id, run) { return [...run.roles, ...state.snapshot.roles].find(role => role.id === id)?.title || id || 'Не указан'; }
  function section(title, note) {
    const node = el('section', 'section'); node.append(el('h2', '', title));
    if (note) node.append(el('p', 'section-note', note));
    return node;
  }
  function disclosure(run, key, title) {
    const details = el('details');
    const storageKey = `${run.id}:${key}`;
    details.open = state.expanded.get(storageKey) || false;
    const summary = el('summary', '', title); summary.dataset.focusKey = key;
    details.append(summary);
    details.addEventListener('toggle', () => { if (details.isConnected) state.expanded.set(storageKey, details.open); });
    const body = el('div', 'disclosure-body'); details.append(body);
    return {details, body};
  }
  function renderNav() {
    const key = JSON.stringify([state.selected, state.snapshot.runs.map(run => [run.id,run.kind,run.status,run.status_label])]);
    if (key === state.navKey) return;
    state.navKey = key;
    const focused = document.activeElement?.dataset.runId;
    const list = document.createDocumentFragment();
    for (const run of state.snapshot.runs) {
      const button = el('button', 'run-button'); button.type = 'button'; button.dataset.runId = run.id;
      button.setAttribute('aria-current', String(run.id === state.selected));
      button.append(el('strong', '', M.runLabel(run)), el('span', 'run-id', run.id), badge(run.status_label || 'Статус неизвестен', run.status));
      button.addEventListener('click', () => { state.selected = run.id; render(); });
      list.append(button);
    }
    if (!state.snapshot.runs.length) list.append(el('p', 'empty', 'Сохранённых запусков нет.'));
    $('runs').replaceChildren(list);
    $('run-count').textContent = String(state.snapshot.runs.length);
    if (focused) [...$('runs').querySelectorAll('button')].find(button => button.dataset.runId === focused)?.focus({preventScroll:true});
  }
  function renderDetail(run) {
    const key = JSON.stringify([run, state.snapshot.roles]);
    if (key === state.detailKey) return;
    state.detailKey = key;
    const focused = $('run-detail').contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
    if (!run) {
      const empty = el('section', 'empty-state');
      empty.append(el('p','eyebrow','Журнал пуст'), el('h2','','Пока нет сохранённых запусков'), el('p','','Панель только читает журнал. Когда в нём появятся записи, они отобразятся автоматически.'));
      $('run-detail').replaceChildren(empty); return;
    }
    const fragment = document.createDocumentFragment();
    const hero = el('section', `hero ${run.status === 'blocked' ? 'blocked' : ''}`);
    const top = el('div','hero-top'); top.append(badge(run.status_label || 'Статус неизвестен', run.status), el('span','run-id', run.id));
    hero.append(top, el('p','eyebrow', 'Текущий этап по журналу'), el('h2','',run.current_stage || 'Этап не записан'), el('p','headline',run.headline || 'Пояснение отсутствует в журнале.'));
    if (run.warning) hero.append(el('p','warning',run.warning));
    const facts = el('dl','facts');
    for (const [label, value] of [['Задача',M.runLabel(run)], ['Роль на текущем этапе',roleTitle(run.current_role,run)], ['Записано шагов',`${run.steps.length} · завершено: ${run.counts?.completed ?? '—'}`], ['Обновление запуска',time(run.updated_at)]]) {
      const fact = el('div'); fact.append(el('dt','',label), el('dd','',value)); facts.append(fact);
    }
    hero.append(facts);
    const next = el('p','next'); next.append(el('span','','Следующий шаг · рекомендация из журнала'), document.createTextNode(run.next_action || 'Не указан.')); hero.append(next);
    fragment.append(hero);
    const workflow = section('Ход работы', 'Порядок записей из API. Повторные роли и попытки показаны отдельно; PENDING не подтверждает, что процесс сейчас работает.');
    const flow = el('ol','flow');
    run.steps.forEach((step,index) => {
      const card = el('li', `step ${tone(step.state)}`);
      const top = el('div','step-top'); top.append(el('span','step-number',`Шаг ${index + 1}`),badge(M.stateLabel(step),step.state));
      card.append(top, el('p','step-role',roleTitle(step.role,run)), el('h3','',step.title || 'Шаг без названия'));
      const meta = [step.phase, step.attempt !== null && step.attempt !== undefined ? `Попытка ${step.attempt}` : null].filter(Boolean).join(' · ');
      if (meta) card.append(el('p','step-meta',meta));
      card.append(el('p','step-meta',`Начало: ${time(step.started_at)} · Конец: ${time(step.ended_at)}`));
      if (typeof step.duration_seconds === 'number' && Number.isFinite(step.duration_seconds)) card.append(el('p','step-meta',`Длительность: ${step.duration_seconds} с`));
      if (step.note) card.append(el('p','step-note',step.note));
      flow.append(card);
    });
    workflow.append(run.steps.length ? flow : el('p','empty','Шаги не записаны. Фиксированный маршрут не предполагается.')); fragment.append(workflow);
    const people = section('Участники');
    for (const [label, members] of [
      ['Есть записи об участии',run.roles.filter(role => !['idle','planned'].includes(role.state))],
      ['Запланированы',run.roles.filter(role => role.state === 'planned')],
      ['Не участвовали',run.roles.filter(role => role.state === 'idle')]
    ]) {
      if (!members.length) continue;
      people.append(el('p','participant-group',label));
      const strip = el('ul','participants');
      members.forEach(role => { const item = el('li','participant'); item.append(document.createTextNode(role.title || role.id),badge(M.stateLabel(role),role.state)); strip.append(item); });
      people.append(strip);
    }
    if (!run.roles.length) people.append(el('p','empty','Участники не записаны.'));
    fragment.append(people);
    const events = disclosure(run,'events',`События журнала · ${run.events.length}`);
    const eventList = el('ol','events');
    run.events.forEach(event => {
      const item = el('li','event');
      item.append(el('p','event-meta',[time(event.at),roleTitle(event.role,run),event.ticket_id].filter(Boolean).join(' · ')), el('p','',event.label || 'Событие без описания'));
      if (event.state) item.append(badge(M.stateLabel(event),event.state));
      eventList.append(item);
    });
    events.body.append(run.events.length ? eventList : el('p','empty','События не записаны.')); fragment.append(events.details);
    const evidence = disclosure(run,'evidence',`Подтверждения и артефакты · ${run.artifacts.length}`);
    evidence.body.append(el('p','evidence-summary',`${run.evidence?.checked ? 'Проверка выполнена' : 'Проверка не подтверждена'}. ${run.evidence?.summary || 'Сводка отсутствует.'}`));
    const artifacts = el('ul','artifacts');
    run.artifacts.forEach(artifact => {
      const item = el('li','artifact'); item.append(el('p','',artifact.label || 'Артефакт'),el('code','',artifact.path || 'Путь не указан'));
      if (artifact.state) item.append(badge(M.stateLabel(artifact) === 'Неизвестно' ? artifact.state : M.stateLabel(artifact),artifact.state));
      artifacts.append(item);
    });
    evidence.body.append(run.artifacts.length ? artifacts : el('p','empty','Артефакты не записаны.')); fragment.append(evidence.details);
    $('run-detail').replaceChildren(fragment);
    if (focused) [...$('run-detail').querySelectorAll('summary')].find(node => node.dataset.focusKey === focused)?.focus({preventScroll:true});
  }
  function render() {
    if (!state.snapshot) return;
    renderNav(); renderDetail(state.snapshot.runs.find(run => run.id === state.selected));
  }
  function freshness() {
    const observed = Date.parse(state.snapshot?.observed_at);
    const stale = state.snapshot && (!Number.isFinite(observed) || Date.now() - observed > 15000 || Date.now() - state.lastOK > 15000);
    const label = state.error ? 'Нет связи · повторяем чтение' : stale ? 'Снимок устарел' : state.snapshot ? 'Связь с журналом установлена' : 'Подключение…';
    if ($('connection-state').textContent !== label) $('connection-state').textContent = label;
    $('freshness').textContent = state.snapshot ? `Снимок журнала: ${time(state.snapshot.observed_at)} · автоматическое чтение каждые 3 с` : 'Снимок ещё не получен';
    $('notice').hidden = !(state.error || stale);
    $('notice').textContent = state.error ? (state.snapshot ? 'Не удалось прочитать журнал. Показан последний полученный снимок, он может быть устаревшим.' : 'Журнал недоступен. Проверьте локальный сервер; чтение повторится автоматически.') : stale ? 'Снимок устарел: текущие сведения могут отличаться. Давняя дата запуска сама по себе не означает потерю связи.' : '';
  }
  function validSnapshot(data) {
    return data?.schema === 1 && data.read_only === true && Array.isArray(data.roles) && Array.isArray(data.runs) && data.runs.every(run => run && typeof run.id === 'string' && ['steps','roles','events','artifacts'].every(key => Array.isArray(run[key]) && run[key].every(item => item && typeof item === 'object')));
  }
  async function refresh() {
    clearTimeout(state.timer);
    if (state.inFlight) { state.queued = true; return; }
    state.inFlight = true;
    $('refresh').textContent = 'Читаем…'; $('refresh').setAttribute('aria-busy','true');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(),10000);
    try {
      const response = await fetch('/api/snapshot',{method:'GET',cache:'no-store',credentials:'same-origin',signal:controller.signal,headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Snapshot unavailable');
      const data = await response.json();
      if (!validSnapshot(data)) throw new Error('Invalid snapshot');
      // Selection is resolved at response time, never captured at request start.
      state.selected = M.selectRun(data.runs,state.selected);
      state.snapshot = data; state.lastOK = Date.now(); state.error = false;
      render();
    } catch (_) {
      state.error = true;
      if (!state.snapshot) {
        $('runs').replaceChildren(el('p','empty','Запуски пока недоступны.'));
        const empty = el('section','empty-state'); empty.append(el('h2','','Не удалось прочитать журнал'),el('p','','Данных для отображения пока нет. Можно повторить чтение кнопкой «Обновить».'));
        $('run-detail').replaceChildren(empty);
      }
    } finally {
      clearTimeout(timeout); state.inFlight = false;
      $('refresh').textContent = 'Обновить'; $('refresh').removeAttribute('aria-busy'); freshness();
      const delay = state.queued ? 0 : 3000; state.queued = false;
      state.timer = setTimeout(refresh,delay);
    }
  }
  $('refresh').addEventListener('click',refresh);
  function watchFreshness() { freshness(); setTimeout(watchFreshness,1000); }
  watchFreshness(); refresh();
})();
