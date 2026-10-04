const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createContextStore } = require('../stores/context');
test('family/child switches and clear invalidate captured requests', () => {
  const c = createContextStore();
  c.select({ familyId: '9007199254740993', childId: '2' });
  const t = c.capture();
  c.select({ familyId: '3', childId: '2' });
  assert.equal(c.isCurrent(t), false);
  const next = c.capture(); c.clear();
  assert.equal(c.isCurrent(next), false);
});
test('captured context cannot mutate live state', () => {
  const c = createContextStore(); const input = { familyId: '1' };
  c.select(input); input.familyId = '2';
  assert.equal(c.capture().current.familyId, '1');
});
