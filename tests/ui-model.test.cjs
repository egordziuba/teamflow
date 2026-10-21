'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sourcePath = path.join(__dirname, '../teamflow/ui/ui-model.js');
function model() {
  const context = {};
  if (fs.existsSync(sourcePath)) vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context);
  return context.TeamflowModel || {};
}
const M = model();
test('semantic labels are bounded; API pending label is preserved without liveness claim', () => {
  assert.equal(typeof M.runLabel, 'function');
  assert.equal(M.runLabel({kind:'csv'}), 'Обработка CSV');
  assert.equal(M.runLabel({kind:'specialists'}), 'Команда специалистов');
  assert.equal(M.runLabel({kind:'other'}), 'Запуск');
  assert.equal(M.stateLabel({state:'pending', state_label:'PENDING · нет результата'}), 'PENDING · нет результата');
  assert.equal(M.stateLabel({state:'pending'}), 'PENDING · результат не записан');
  assert.equal(M.stateLabel({state:'idle'}), 'Не участвовал');
  assert.equal(M.stateLabel({state:'unrecognized'}), 'Неизвестно');
});
const runs = [
  {id:'new', status:'accepted', updated_at:'2026-10-04T12:00:00Z'},
  {id:'blocked-old', status:'blocked', updated_at:'2026-10-02T12:00:00Z'},
  {id:'blocked-new', status:'blocked', updated_at:'2026-10-03T12:00:00Z'}
];
test('initial selection prefers newest blocked; explicit selection survives refresh', () => {
  assert.equal(typeof M.selectRun, 'function', 'selection function must exist');
  assert.equal(M.selectRun(runs, null), 'blocked-new');
  assert.equal(M.selectRun(runs, 'new'), 'new');
  assert.equal(M.selectRun(runs, 'deleted'), 'blocked-new');
  assert.equal(M.selectRun(runs.slice(0, 1), null), 'new');
  assert.equal(M.selectRun([], 'new'), null);
});
