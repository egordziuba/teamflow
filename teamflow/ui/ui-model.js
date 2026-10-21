'use strict';
globalThis.TeamflowModel = (() => {
  function selectRun(runs, selectedId) {
    if (runs.some(run => run.id === selectedId)) return selectedId;
    const newest = [...runs].sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0));
    return (newest.find(run => run.status === 'blocked') || newest[0])?.id ?? null;
  }
  function runLabel(run) {
    if (run.kind === 'role-check') return typeof run.headline === 'string' ? run.headline.slice(0, 100) : 'Проверка роли';
    return ({csv:'Обработка CSV', specialists:'Команда специалистов'})[run.kind] || 'Запуск';
  }
  function stateLabel(item) {
    return item.state_label || ({completed:'Завершён', pending:'PENDING · результат не записан', failed:'Ошибка', planned:'Запланирован', idle:'Не участвовал'})[item.state] || 'Неизвестно';
  }
  return Object.freeze({selectRun, runLabel, stateLabel});
})();
