import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLifecycle } from '../src/controllers/lifecycle.js';

test('disposal unsubscribes and is idempotent across application boots', () => {
  const target = new EventTarget();
  let calls = 0;
  const first = createLifecycle();
  first.listen(target, 'change', () => calls++);
  target.dispatchEvent(new Event('change'));
  first.dispose(); first.dispose();
  target.dispatchEvent(new Event('change'));
  assert.equal(calls, 1);
  const second = createLifecycle();
  second.listen(target, 'change', () => calls++);
  target.dispatchEvent(new Event('change'));
  assert.equal(calls, 2);
  second.dispose();
});
test('resources dispose in reverse order and late subscriptions cannot leak', () => {
  const scope = createLifecycle(); const order = [];
  scope.own(() => order.push('map'));
  scope.own(() => order.push('view'));
  scope.dispose();
  scope.own(() => order.push('late'));
  assert.deepEqual(order, ['view', 'map', 'late']);
  assert.equal(scope.disposed, true);
});
