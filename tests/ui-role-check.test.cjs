const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('role checks show the tested role rather than generic project completion', () => {
  const context = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../teamflow/ui/ui-model.js'), 'utf8'), context);
  assert.equal(context.TeamflowModel.runLabel({kind: 'role-check', headline: 'Проверка · Дизайнер'}), 'Проверка · Дизайнер');
});
