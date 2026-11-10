import test from 'node:test';
import assert from 'node:assert/strict';
import {
  evaluate, feasibleDoors, applyAssignment, completeTrailer, advanceClock,
  refreshSyntheticProfiles, parseScenario, exportScenarioCsv,
} from '../lib/dock-engine.ts';
import { createScenario } from '../lib/dock-fixtures.ts';

function trailer(id, overrides = {}) {
  return {
    id, carrier: 'Fictional Freight', status: 'yard', arrivalMinute: 500,
    handling: 'palletized', packageCount: 100, currentUnits: 40, nextUnits: 30,
    zoneUnits: { A: 60, B: 30, C: 10 }, profileKnown: true,
    profileUpdatedMinute: 600, hold: false, currentDoorId: null,
    plannedDoorId: null, ...overrides,
  };
}
function scenario(trailers = [], doors = undefined) {
  return {
    version: 1, synthetic: true, seed: 42, name: 'Fictional Harbor', nowMinute: 600,
    currentDeadlineMinute: 720, nextDeadlineMinute: 960,
    zones: [
      { id: 'A', name: 'North', capacityUnits: 200 },
      { id: 'B', name: 'Central', capacityUnits: 400 },
      { id: 'C', name: 'South', capacityUnits: 300 },
    ],
    doors: doors ?? [
      { id: 'A1', zoneId: 'A', allowedHandling: ['palletized'], enabled: true },
      { id: 'A2', zoneId: 'A', allowedHandling: ['palletized', 'cart'], enabled: true },
      { id: 'B1', zoneId: 'B', allowedHandling: ['palletized', 'loose'], enabled: true },
      { id: 'C1', zoneId: 'C', allowedHandling: ['loose'], enabled: true },
      { id: 'X1', zoneId: null, allowedHandling: ['crossdock'], enabled: true },
    ],
    trailers,
  };
}
const copy = (value) => structuredClone(value);
function freeze(value) {
  if (value && typeof value === 'object') {
    Object.freeze(value);
    for (const child of Object.values(value)) freeze(child);
  }
  return value;
}
const rec = (evaluation, id) => evaluation.recommendations.find((item) => item.trailerId === id);

test('priority boundaries exclude complete and empty work and report overdue deadlines', () => {
  const state = scenario([
    trailer('high', { currentUnits: 1 }),
    trailer('medium', { currentUnits: 0, nextUnits: 1 }),
    trailer('low', { currentUnits: 0, nextUnits: 0 }),
    trailer('done', { status: 'complete' }),
    trailer('empty', { packageCount: 0, currentUnits: 0, nextUnits: 0, zoneUnits: { A: 0, B: 0, C: 0 } }),
  ]);
  const result = evaluate(state);
  assert.deepEqual(Object.fromEntries(Object.entries(result.priorities).map(([id, p]) => [id, p.level])), {
    high: 'high', medium: 'medium', low: 'low', done: 'none', empty: 'none',
  });
  state.nowMinute = 720;
  assert.equal(evaluate(state).priorities.high.overdue, false);
  state.nowMinute = 721;
  assert.equal(evaluate(state).priorities.high.overdue, true);
  assert.equal(evaluate(state).priorities.medium.overdue, false);
  state.nowMinute = 961;
  assert.equal(evaluate(state).priorities.medium.overdue, true);
});

test('priority and arrival queues have stable, independent ordering', () => {
  const state = scenario([
    trailer('z', { arrivalMinute: 450, currentUnits: 30 }),
    trailer('a', { arrivalMinute: 450, currentUnits: 30 }),
    trailer('urgent', { arrivalMinute: 550, currentUnits: 90, nextUnits: 0 }),
    trailer('old', { arrivalMinute: 400, currentUnits: 0 }),
    trailer('done', { arrivalMinute: 1, status: 'complete' }),
    trailer('empty', { arrivalMinute: 2, packageCount: 0, currentUnits: 0, nextUnits: 0, zoneUnits: { A: 0, B: 0, C: 0 } }),
  ]);
  assert.deepEqual(evaluate(state).queueIds, ['urgent', 'a', 'z', 'old', 'done', 'empty']);
  assert.deepEqual(evaluate(state, 'arrival').queueIds, ['old', 'a', 'z', 'urgent', 'done', 'empty']);
});

test('a held physical occupant reserves its door and remains in active volume', () => {
  const state = scenario([
    trailer('occupied', { status: 'at_door', hold: true, currentDoorId: 'A1', currentUnits: 0 }),
    trailer('waiting'),
  ]);
  assert.deepEqual(feasibleDoors(state, 'waiting').map((door) => door.doorId), ['A2']);
  const result = evaluate(state);
  assert.equal(result.metrics.totalPackages, 200);
  assert.equal(result.metrics.availableDoors, 4);
  assert.equal(result.zones.find((zone) => zone.zoneId === 'A').onDoorUnits, 60);
  assert.equal(result.zones.find((zone) => zone.zoneId === 'A').heldUnits, 60);
  assert.equal(result.zones.find((zone) => zone.zoneId === 'A').pressurePercent, 60);
});

test('handling AND dominant destination are required and destination ties remain eligible', () => {
  const state = scenario([
    trailer('cart', { handling: 'cart', zoneUnits: { A: 10, B: 80, C: 10 } }),
    trailer('tie', { zoneUnits: { A: 50, B: 50, C: 0 } }),
  ]);
  assert.deepEqual(feasibleDoors(state, 'cart'), []);
  assert.deepEqual(feasibleDoors(state, 'tie').map((door) => door.doorId), ['B1', 'A1', 'A2']);
  assert.equal(feasibleDoors(state, 'tie')[0].zoneMatchPercent, 50);
  assert.equal(feasibleDoors(state, 'tie')[0].projectedPressurePercent, 25);
  assert.match(rec(evaluate(state), 'cart').reason, /handling|cart/i);
});

test('crossdock uses only an available dedicated transfer door', () => {
  const state = scenario([trailer('transfer', { handling: 'crossdock' })]);
  const candidates = feasibleDoors(state, 'transfer');
  assert.deepEqual(candidates.map((door) => door.doorId), ['X1']);
  assert.equal(candidates[0].zoneMatchPercent, null);
  assert.equal(candidates[0].projectedPressurePercent, null);
  state.doors.find((door) => door.id === 'X1').enabled = false;
  assert.deepEqual(feasibleDoors(state, 'transfer'), []);
  assert.match(rec(evaluate(state), 'transfer').reason, /transfer.*disabled|disabled.*X1/i);
});

test('unknown, stale, held, future and empty loads cannot acquire a new door', () => {
  const state = scenario([
    trailer('unknown', { profileKnown: false, profileUpdatedMinute: null, zoneUnits: { A: 0, B: 0, C: 0 } }),
    trailer('stale', { profileUpdatedMinute: 539 }),
    trailer('boundary', { profileUpdatedMinute: 540 }),
    trailer('held', { hold: true }),
    trailer('future', { status: 'expected', arrivalMinute: 630 }),
    trailer('empty', { packageCount: 0, currentUnits: 0, nextUnits: 0, zoneUnits: { A: 0, B: 0, C: 0 } }),
  ]);
  for (const id of ['unknown', 'stale', 'held', 'future', 'empty']) assert.equal(feasibleDoors(state, id).length, 0);
  assert.equal(feasibleDoors(state, 'boundary').length, 2);
  const result = evaluate(state);
  assert.match(rec(result, 'unknown').reason, /missing|unknown/i);
  assert.match(rec(result, 'stale').reason, /61.*minute|stale/i);
  assert.match(rec(result, 'held').reason, /hold/i);
  assert.match(rec(result, 'empty').reason, /empty|no packages/i);
  assert.equal(rec(result, 'future'), undefined);
  assert.equal(result.metrics.blockedCount, 4);
  assert.equal(result.metrics.unmappedPackages, 100);
});

test('duplicate physical occupancy is critical and never frees that door', () => {
  const state = scenario([
    trailer('one', { status: 'at_door', currentDoorId: 'A1', hold: true }),
    trailer('two', { status: 'at_door', currentDoorId: 'A1', profileUpdatedMinute: 500 }),
    trailer('waiting'),
  ]);
  const result = evaluate(state);
  assert.ok(result.warnings.some((warning) => warning.severity === 'critical' && warning.doorId === 'A1' && warning.trailerIds.length === 2));
  assert.equal(result.metrics.availableDoors, 4);
  assert.ok(feasibleDoors(state, 'waiting').every((door) => door.doorId !== 'A1'));
  assert.equal(parseScenario(state).ok, true);
  const afterOneCompletion = completeTrailer(state, 'one');
  assert.equal(afterOneCompletion.event.doorId, 'A1');
  assert.ok(feasibleDoors(afterOneCompletion.scenario, 'waiting').every((door) => door.doorId !== 'A1'));
});

test('candidate pressure counts every physical full load and advisory plans never reserve a door', () => {
  const state = scenario([
    trailer('held', { status: 'at_door', currentDoorId: 'A1', hold: true, profileUpdatedMinute: 500 }),
    trailer('unknown', { status: 'at_door', currentDoorId: 'A1', profileKnown: false, profileUpdatedMinute: null, zoneUnits: { A: 0, B: 0, C: 0 } }),
    trailer('wrong-zone', { status: 'at_door', currentDoorId: 'A1', zoneUnits: { A: 0, B: 0, C: 100 } }),
    trailer('waiting', { plannedDoorId: 'A1' }),
    trailer('future-plan', { status: 'expected', arrivalMinute: 800, plannedDoorId: 'A2' }),
  ]);
  state.doors[0].enabled = false;
  const available = feasibleDoors(state, 'waiting');
  assert.deepEqual(available.map((item) => item.doorId), ['A2']);
  assert.equal(available[0].projectedPressurePercent, 200);
  assert.equal(evaluate(state).metrics.availableDoors, 4);
});

test('wrong physical doors are warned about but remain occupied', () => {
  const state = scenario([
    trailer('wrong', { status: 'at_door', currentDoorId: 'C1', handling: 'cart' }),
    trailer('south', { handling: 'loose', zoneUnits: { A: 0, B: 0, C: 100 } }),
  ]);
  const result = evaluate(state);
  assert.ok(result.warnings.some((warning) => /handling/i.test(warning.message) && warning.trailerIds.includes('wrong')));
  assert.ok(result.warnings.some((warning) => /destination/i.test(warning.message) && warning.trailerIds.includes('wrong')));
  assert.equal(rec(result, 'south').primary, null);
  assert.match(rec(result, 'south').reason, /C1.*occupied|occupied.*C1/i);
});

test('sequential proposals reserve doors and alternates exclude every final primary', () => {
  const state = scenario([
    trailer('first', { currentUnits: 80, nextUnits: 0 }),
    trailer('second', { currentUnits: 60, nextUnits: 0 }),
    trailer('third', { currentUnits: 20, nextUnits: 0 }),
  ]);
  const result = evaluate(state);
  assert.equal(rec(result, 'first').primary.doorId, 'A1');
  assert.equal(rec(result, 'second').primary.doorId, 'A2');
  assert.equal(rec(result, 'first').primary.projectedPressurePercent, 50);
  assert.equal(rec(result, 'second').primary.projectedPressurePercent, 100);
  assert.equal(rec(result, 'third').primary, null);
  assert.match(rec(result, 'third').reason, /reserved|proposed/i);
  const primaryIds = new Set(result.recommendations.flatMap((item) => item.primary ? [item.primary.doorId] : []));
  assert.ok(result.recommendations.every((item) => item.alternatives.every((door) => !primaryIds.has(door.doorId))));
});

test('alternates remain usable when no other primary claims them', () => {
  const state = scenario([trailer('only')]);
  const proposal = rec(evaluate(state), 'only');
  assert.equal(proposal.primary.doorId, 'A1');
  assert.deepEqual(proposal.alternatives.map((door) => door.doorId), ['A2']);
  assert.equal(applyAssignment(state, 'only', 'A2', 'Operator selected alternate').scenario.trailers[0].currentDoorId, 'A2');
});

test('priority inversion warning requires real handling and destination compatibility', () => {
  const compatible = scenario([
    trailer('low', { status: 'at_door', currentDoorId: 'A1', currentUnits: 0, nextUnits: 0 }),
    trailer('high'),
  ]);
  assert.ok(evaluate(compatible).warnings.some((warning) => warning.code === 'priority-inversion'));
  const wrongDestination = copy(compatible);
  wrongDestination.trailers[1].zoneUnits = { A: 0, B: 100, C: 0 };
  assert.ok(evaluate(wrongDestination).warnings.every((warning) => warning.code !== 'priority-inversion'));
  const held = copy(compatible);
  held.trailers[1].hold = true;
  assert.ok(evaluate(held).warnings.every((warning) => warning.code !== 'priority-inversion'));
  assert.equal(compatible.trailers[0].currentDoorId, 'A1');
});

test('assignment rechecks conflicts and data freshness and never changes the input', () => {
  const original = freeze(scenario([trailer('one'), trailer('two')]));
  const result = applyAssignment(original, 'one', 'A1', 'Manual approval');
  assert.equal(original.trailers[0].status, 'yard');
  assert.equal(result.scenario.trailers[0].status, 'at_door');
  assert.deepEqual(result.event, { action: 'assign', trailerId: 'one', doorId: 'A1', atMinute: 600, reason: 'Manual approval' });
  assert.throws(() => applyAssignment(result.scenario, 'two', 'A1'), /occupied/i);
  assert.throws(() => applyAssignment(original, 'one', 'B1'), /destination|eligible|compatible/i);
  assert.throws(() => applyAssignment(advanceClock(original, 61), 'one', 'A1'), /stale/i);
  assert.throws(() => applyAssignment(original, 'missing', 'A1'), /not found|unknown trailer/i);
});

test('completing a physically held trailer releases its door and preserves undo input', () => {
  const original = freeze(scenario([trailer('one', { status: 'at_door', currentDoorId: 'A1', hold: true })]));
  const result = completeTrailer(original, 'one');
  assert.equal(result.scenario.trailers[0].status, 'complete');
  assert.equal(result.scenario.trailers[0].currentDoorId, null);
  assert.equal(result.event.doorId, 'A1');
  assert.equal(evaluate(result.scenario).metrics.totalPackages, 0);
  assert.equal(original.trailers[0].currentDoorId, 'A1');
  assert.throws(() => completeTrailer(result.scenario, 'one'), /at a door|at-door/i);
});

test('clock advancement releases arrivals, preserves deadlines, clamps at day end and is immutable', () => {
  const original = freeze(scenario([
    trailer('arrives', { status: 'expected', arrivalMinute: 630 }),
    trailer('later', { status: 'expected', arrivalMinute: 631 }),
  ]));
  const next = advanceClock(original);
  assert.equal(next.nowMinute, 630);
  assert.equal(next.trailers[0].status, 'yard');
  assert.equal(next.trailers[1].status, 'expected');
  assert.equal(next.currentDeadlineMinute, 720);
  assert.equal(next.nextDeadlineMinute, 960);
  assert.equal(original.trailers[0].status, 'expected');
  assert.equal(advanceClock(next, 1440).nowMinute, 1440);
  assert.throws(() => advanceClock(original, -1), /non-negative|positive|minutes/i);
});

test('refresh updates known timestamps while missing profiles stay visibly unknown', () => {
  const original = freeze(scenario([
    trailer('unknown', { profileKnown: false, profileUpdatedMinute: null, zoneUnits: { A: 0, B: 0, C: 0 } }),
    trailer('stale', { profileUpdatedMinute: 500 }),
  ]));
  const updated = refreshSyntheticProfiles(original);
  assert.deepEqual(updated, refreshSyntheticProfiles(original));
  assert.equal(updated.trailers[0].profileKnown, false);
  assert.equal(updated.trailers[0].profileUpdatedMinute, null);
  assert.deepEqual(updated.trailers[0].zoneUnits, { A: 0, B: 0, C: 0 });
  assert.equal(updated.trailers[0].packageCount, 100);
  assert.equal(updated.trailers[0].currentUnits, 40);
  assert.equal(updated.trailers[1].profileUpdatedMinute, 600);
  assert.deepEqual(updated.trailers[1].zoneUnits, original.trailers[1].zoneUnits);
  assert.equal(original.trailers[0].profileKnown, false);
});

test('metrics name active work and split unmapped packages from known destination demand', () => {
  const state = scenario([
    trailer('door', { status: 'at_door', currentDoorId: 'A1', hold: true }),
    trailer('yard'),
    trailer('future', { status: 'expected', arrivalMinute: 630 }),
    trailer('unknown', { profileKnown: false, profileUpdatedMinute: null, zoneUnits: { A: 0, B: 0, C: 0 } }),
    trailer('done', { status: 'complete' }),
  ]);
  const result = evaluate(state);
  assert.equal(result.metrics.activeTrailers, 4);
  assert.equal(result.metrics.yardTrailers, 2);
  assert.equal(result.metrics.urgentTrailers, 4);
  assert.equal(result.metrics.totalPackages, 400);
  assert.equal(result.metrics.currentDuePackages, 160);
  assert.equal(result.metrics.unmappedPackages, 100);
  assert.deepEqual(result.zones[0], { zoneId: 'A', onDoorUnits: 60, yardUnits: 60, expectedUnits: 60, heldUnits: 60, totalUnits: 180, capacityUnits: 200, pressurePercent: 90 });
});

test('empty scenarios produce no NaN, proposals or active work', () => {
  const result = evaluate(scenario());
  assert.equal(result.metrics.totalPackages, 0);
  assert.equal(result.metrics.blockedCount, 0);
  assert.deepEqual(result.recommendations, []);
  assert.ok(result.zones.every((zone) => zone.pressurePercent === 0));
  assert.equal(parseScenario(scenario()).ok, true);
});

test('parse reconstructs known fields and rejects non-synthetic, malformed, excessive or inconsistent data', () => {
  const valid = scenario([trailer('valid')]);
  valid.extra = 'discard';
  valid.trailers[0].extra = 'discard';
  const result = parseScenario(valid);
  assert.equal(result.ok, true);
  assert.equal(Object.hasOwn(result.scenario, 'extra'), false);
  assert.equal(Object.hasOwn(result.scenario.trailers[0], 'extra'), false);
  assert.notEqual(result.scenario.trailers[0], valid.trailers[0]);
  const mutations = [
    (s) => { s.synthetic = false; },
    (s) => { s.seed = 4294967296; },
    (s) => { s.zones[0].capacityUnits = 0; },
    (s) => { s.zones[1].id = 'A'; },
    (s) => { s.trailers[0].packageCount = -1; },
    (s) => { s.trailers[0].currentUnits = 90; s.trailers[0].nextUnits = 20; },
    (s) => { s.trailers[0].zoneUnits.A = 59; },
    (s) => { s.trailers[0].profileUpdatedMinute = 601; },
    (s) => { s.trailers[0].currentDoorId = 'missing'; s.trailers[0].status = 'at_door'; },
    (s) => { s.trailers[0].hold = 'false'; },
    (s) => { s.trailers[0].profileKnown = false; },
    (s) => { s.trailers[0].profileUpdatedMinute = null; },
    (s) => { s.doors[0].allowedHandling = ['crossdock']; },
    (s) => { s.doors[4].allowedHandling = ['palletized']; },
    (s) => { s.trailers.push(copy(s.trailers[0])); },
    (s) => { s.doors.push(copy(s.doors[0])); },
    (s) => { s.trailers = Array.from({ length: 101 }, (_, i) => trailer(`T${i}`)); },
    (s) => { s.doors = Array.from({ length: 31 }, (_, i) => ({ ...s.doors[0], id: `D${i}` })); },
  ];
  for (const mutate of mutations) {
    const invalid = copy(valid); mutate(invalid);
    const parsed = parseScenario(invalid);
    assert.equal(parsed.ok, false);
    assert.ok(parsed.errors.length > 0);
  }
  for (const invalid of [null, [], 'text', 3, { get version() { throw new Error('untrusted accessor'); } }]) {
    assert.doesNotThrow(() => parseScenario(invalid));
    assert.equal(parseScenario(invalid).ok, false);
  }
});

test('parse rejects sparse record arrays instead of silently accepting absent records', () => {
  for (const field of ['doors', 'trailers']) {
    const state = scenario();
    state[field] = new Array(1);
    assert.equal(parseScenario(state).ok, false);
  }
});

test('unsafe identifiers and inherited fields cannot inject object keys', () => {
  for (const unsafe of ['__proto__', 'constructor', 'prototype', 'bad id', '../x', '']) {
    const state = scenario([trailer(unsafe)]);
    assert.equal(parseScenario(state).ok, false);
  }
  const inherited = Object.create(scenario([trailer('one')]));
  assert.equal(parseScenario(inherited).ok, false);
  const valid = parseScenario(JSON.parse(JSON.stringify(scenario([trailer('one')])).replace('"name":', '"__proto__":{"polluted":true},"name":')));
  assert.equal(valid.ok, true);
  assert.equal({}.polluted, undefined);
  assert.equal(Object.hasOwn(valid.scenario, '__proto__'), false);
});

test('CSV safely quotes commas, quotes, line breaks and spreadsheet formulas', () => {
  const state = scenario([trailer('one', { carrier: '=SUM(1,2)\n"fictional"' })]);
  const csv = exportScenarioCsv(state, evaluate(state));
  assert.ok(csv.includes('"\'=SUM(1,2)\n""fictional"""'));
  assert.match(csv, /synthetic/i);
  assert.match(csv, /one/);
});

test('fictional fixtures are deterministic, varied, valid and have all demonstration populations', () => {
  for (const preset of ['balanced', 'surge', 'disruption']) {
    const state = createScenario(preset, 7);
    assert.deepEqual(state, createScenario(preset, 7));
    assert.notDeepEqual(state, createScenario(preset, 8));
    assert.equal(state.trailers.length, 12);
    assert.equal(state.doors.length, 7);
    assert.equal(state.zones.length, 3);
    assert.equal(parseScenario(state).ok, true, JSON.stringify(parseScenario(state)));
    assert.ok(state.trailers.some((item) => item.status === 'at_door' && item.hold));
    assert.ok(state.trailers.some((item) => !item.profileKnown));
    assert.ok(state.trailers.some((item) => item.status === 'expected'));
    assert.ok(state.trailers.some((item) => item.handling === 'crossdock' && feasibleDoors(state, item.id).length > 0));
  }
  assert.notDeepEqual(createScenario('balanced', 7), createScenario('surge', 7));
  assert.notDeepEqual(createScenario('balanced', 7), createScenario('disruption', 7));
});

test('every fixture proposal obeys independently checked physical and hard constraints', () => {
  for (const preset of ['balanced', 'surge', 'disruption']) for (const seed of [0, 1, 2, 42, 4294967295]) for (const mode of ['priority', 'arrival']) {
    const state = freeze(createScenario(preset, seed));
    const result = evaluate(state, mode);
    const occupied = new Set(state.trailers.filter((item) => item.status === 'at_door').map((item) => item.currentDoorId));
    const claimed = new Set();
    for (const recommendation of result.recommendations) {
      if (!recommendation.primary) { assert.ok(recommendation.reason.length > 10); continue; }
      const load = state.trailers.find((item) => item.id === recommendation.trailerId);
      const door = state.doors.find((item) => item.id === recommendation.primary.doorId);
      assert.equal(load.status, 'yard');
      assert.equal(load.hold, false);
      assert.equal(load.profileKnown, true);
      assert.ok(state.nowMinute - load.profileUpdatedMinute <= 60);
      assert.ok(load.packageCount > 0 && door.enabled);
      assert.ok(door.allowedHandling.includes(load.handling));
      assert.ok(!occupied.has(door.id) && !claimed.has(door.id));
      if (load.handling === 'crossdock') assert.equal(door.zoneId, null);
      else assert.equal(load.zoneUnits[door.zoneId], Math.max(...Object.values(load.zoneUnits)));
      claimed.add(door.id);
    }
    for (const recommendation of result.recommendations) for (const door of recommendation.alternatives) {
      assert.ok(!claimed.has(door.doorId));
      assert.ok(!occupied.has(door.doorId));
    }
  }
});
