import type {
  ActionResult, Door, DoorCandidate, Evaluation, Handling, ParseResult, PlanMode,
  PriorityDetail, Recommendation, Scenario, Trailer, TrailerStatus, Warning, Zone, ZoneId,
} from './dock-types.ts';

const ZONES: ZoneId[] = ['A', 'B', 'C'];
const HANDLING: Handling[] = ['palletized', 'cart', 'loose', 'crossdock'];
const STATUSES: TrailerStatus[] = ['expected', 'yard', 'at_door', 'complete'];
const PRIORITY_ORDER = { high: 0, medium: 1, low: 2, none: 3 } as const;
const MAX_COUNT = 1_000_000;
const FRESH_MINUTES = 60;
const byId = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
const time = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;

function cloneScenario(scenario: Scenario): Scenario {
  return {
    ...scenario,
    zones: scenario.zones.map((zone) => ({ ...zone })),
    doors: scenario.doors.map((door) => ({ ...door, allowedHandling: [...door.allowedHandling] })),
    trailers: scenario.trailers.map((trailer) => ({ ...trailer, zoneUnits: { ...trailer.zoneUnits } })),
  };
}

function priority(scenario: Scenario, trailer: Trailer): PriorityDetail {
  if (trailer.status === 'complete') return { level: 'none', reason: 'Unloaded; excluded from active work.', overdue: false };
  if (trailer.packageCount === 0) return { level: 'none', reason: 'Empty load; no packages to assign.', overdue: false };
  if (trailer.currentUnits > 0) return {
    level: 'high', reason: `${trailer.currentUnits} packages due by ${time(scenario.currentDeadlineMinute)}.`,
    overdue: scenario.nowMinute > scenario.currentDeadlineMinute,
  };
  if (trailer.nextUnits > 0) return {
    level: 'medium', reason: `${trailer.nextUnits} packages due by ${time(scenario.nextDeadlineMinute)}; none in the current deadline.`,
    overdue: scenario.nowMinute > scenario.nextDeadlineMinute,
  };
  return { level: 'low', reason: 'Positive volume with no packages in either deadline bucket.', overdue: false };
}

function dataBlock(scenario: Scenario, trailer: Trailer): string | null {
  if (trailer.status !== 'yard') {
    if (trailer.status === 'expected') return `Expected arrival at ${time(trailer.arrivalMinute)}; advance the clock before planning this load.`;
    if (trailer.status === 'at_door') return `Already at door ${trailer.currentDoorId}; physical occupancy is preserved.`;
    return 'This trailer is complete.';
  }
  if (trailer.arrivalMinute > scenario.nowMinute) return `Arrival at ${time(trailer.arrivalMinute)} has not occurred.`;
  if (trailer.hold) return 'On hold; release the hold before approving a new assignment.';
  if (trailer.packageCount === 0) return 'Empty load; no packages to assign.';
  if (!trailer.profileKnown || trailer.profileUpdatedMinute === null) return 'Destination profile is missing; supply a valid synthetic profile before assignment. Timestamp refresh cannot fill missing data.';
  if (trailer.profileUpdatedMinute > scenario.nowMinute) return 'Profile timestamp is in the future; correct the scenario before assignment.';
  const age = scenario.nowMinute - trailer.profileUpdatedMinute;
  if (age > FRESH_MINUTES) return `Profile is stale (${age} minutes old; maximum ${FRESH_MINUTES}); refresh before assignment.`;
  return null;
}

function dominantZones(trailer: Trailer): ZoneId[] {
  const maximum = Math.max(...ZONES.map((zone) => trailer.zoneUnits[zone]));
  return maximum > 0 ? ZONES.filter((zone) => trailer.zoneUnits[zone] === maximum) : [];
}

function handlingMatches(door: Door, trailer: Trailer): boolean {
  return door.allowedHandling.includes(trailer.handling)
    && (trailer.handling === 'crossdock' ? door.zoneId === null : door.zoneId !== null);
}

function destinationMatches(door: Door, trailer: Trailer): boolean {
  if (trailer.handling === 'crossdock') return door.zoneId === null;
  return door.zoneId !== null && dominantZones(trailer).includes(door.zoneId);
}

function occupancy(scenario: Scenario): Map<string, Trailer[]> {
  const result = new Map<string, Trailer[]>();
  for (const trailer of scenario.trailers) {
    if (trailer.status !== 'at_door' || trailer.currentDoorId === null) continue;
    const residents = result.get(trailer.currentDoorId) ?? [];
    residents.push(trailer);
    result.set(trailer.currentDoorId, residents);
  }
  return result;
}

// A full load physically occupies its door's zone, regardless of its profile or hold.
// Destination-split demand is a separate measure in evaluate().
function physicalPressure(scenario: Scenario): Map<ZoneId, number> {
  const result = new Map<ZoneId, number>(ZONES.map((zone) => [zone, 0]));
  const doors = new Map(scenario.doors.map((door) => [door.id, door]));
  for (const trailer of scenario.trailers) {
    if (trailer.status !== 'at_door' || trailer.currentDoorId === null) continue;
    const zone = doors.get(trailer.currentDoorId)?.zoneId;
    if (zone) result.set(zone, (result.get(zone) ?? 0) + trailer.packageCount);
  }
  return result;
}

function candidates(
  scenario: Scenario,
  trailer: Trailer,
  reserved: ReadonlySet<string> = new Set(),
  proposedUnits: ReadonlyMap<ZoneId, number> = new Map(),
): DoorCandidate[] {
  if (dataBlock(scenario, trailer)) return [];
  const occupied = occupancy(scenario);
  const physical = physicalPressure(scenario);
  const capacities = new Map(scenario.zones.map((zone) => [zone.id, zone.capacityUnits]));
  return scenario.doors
    .filter((door) => door.enabled && !occupied.has(door.id) && !reserved.has(door.id)
      && handlingMatches(door, trailer) && destinationMatches(door, trailer))
    .map((door): DoorCandidate => {
      if (door.zoneId === null) return {
        doorId: door.id, zoneId: null, zoneMatchPercent: null, projectedPressurePercent: null,
        rationale: ['Crossdock handling is compatible with this dedicated transfer door.', 'Destination match and zone workload proxy do not apply to transfer doors.'],
      };
      const match = trailer.zoneUnits[door.zoneId] / trailer.packageCount * 100;
      const units = (physical.get(door.zoneId) ?? 0) + (proposedUnits.get(door.zoneId) ?? 0) + trailer.packageCount;
      const capacity = capacities.get(door.zoneId)!;
      const pressure = units / capacity * 100;
      return {
        doorId: door.id, zoneId: door.zoneId, zoneMatchPercent: match, projectedPressurePercent: pressure,
        rationale: [
          `${trailer.handling} handling is permitted at this door.`,
          `Zone ${door.zoneId} is a dominant destination (${match.toFixed(1)}% of this load).`,
          `Projected zone workload: ${units} full-load packages / ${capacity} capacity units = ${pressure.toFixed(1)}%; includes physical loads and earlier proposals. This is a synthetic workload proxy.`,
        ],
      };
    })
    .sort((a, b) => (b.zoneMatchPercent ?? 0) - (a.zoneMatchPercent ?? 0)
      || (a.projectedPressurePercent ?? 0) - (b.projectedPressurePercent ?? 0)
      || byId(a.doorId, b.doorId));
}

export function feasibleDoors(scenario: Scenario, trailerId: string): DoorCandidate[] {
  const trailer = scenario.trailers.find((item) => item.id === trailerId);
  return trailer ? candidates(scenario, trailer) : [];
}

function blockedReason(scenario: Scenario, trailer: Trailer, reserved: ReadonlySet<string>): string {
  const blocked = dataBlock(scenario, trailer);
  if (blocked) return blocked;
  const handlingDoors = scenario.doors.filter((door) => handlingMatches(door, trailer));
  if (handlingDoors.length === 0) return trailer.handling === 'crossdock'
    ? 'No dedicated transfer door permits crossdock handling; ordinary doors cannot be substituted.'
    : `No ordinary door permits ${trailer.handling} handling.`;
  const matching = handlingDoors.filter((door) => destinationMatches(door, trailer));
  if (matching.length === 0) return `No door combines ${trailer.handling} handling with dominant destination zone${dominantZones(trailer).length > 1 ? 's' : ''} ${dominantZones(trailer).join('/')}.`;
  const occupied = occupancy(scenario);
  const reasons = matching.sort((a, b) => byId(a.id, b.id)).map((door) => {
    const blockers: string[] = [];
    if (!door.enabled) blockers.push('disabled');
    if (occupied.has(door.id)) blockers.push(`occupied by ${occupied.get(door.id)!.map((load) => load.id).join(', ')}`);
    if (reserved.has(door.id)) blockers.push('reserved by an earlier proposal');
    return `${door.id} ${blockers.join(' and ') || 'unavailable'}`;
  });
  return `Compatible ${trailer.handling === 'crossdock' ? 'transfer ' : ''}doors unavailable: ${reasons.join('; ')}.`;
}

function collectWarnings(scenario: Scenario, priorities: Record<string, PriorityDetail>): Warning[] {
  const warnings: Warning[] = [];
  const occupied = occupancy(scenario);
  const doors = new Map(scenario.doors.map((door) => [door.id, door]));
  for (const [doorId, trailers] of occupied) {
    if (trailers.length > 1) warnings.push({
      code: 'duplicate-occupancy', severity: 'critical', doorId, trailerIds: trailers.map((item) => item.id),
      message: `${doorId} has ${trailers.length} simultaneous physical occupants. Resolve the conflicting locations; the door remains reserved.`,
    });
  }
  for (const trailer of scenario.trailers) {
    if (trailer.status === 'complete') continue;
    if (!trailer.profileKnown || trailer.profileUpdatedMinute === null) warnings.push({
      code: 'missing-profile', severity: 'warning', trailerIds: [trailer.id],
      message: `${trailer.id} has no destination profile; ${trailer.packageCount} packages remain visible as unmapped work.`,
    });
    else if (scenario.nowMinute - trailer.profileUpdatedMinute > FRESH_MINUTES) warnings.push({
      code: 'stale-profile', severity: 'warning', trailerIds: [trailer.id],
      message: `${trailer.id}'s profile is ${scenario.nowMinute - trailer.profileUpdatedMinute} minutes old; new assignments require a profile no older than ${FRESH_MINUTES} minutes.`,
    });
    const references: Array<{ id: string; physical: boolean }> = [];
    if (trailer.status === 'at_door' && trailer.currentDoorId) references.push({ id: trailer.currentDoorId, physical: true });
    if (trailer.plannedDoorId) references.push({ id: trailer.plannedDoorId, physical: false });
    for (const reference of references) {
      const door = doors.get(reference.id);
      if (!door) continue;
      const label = reference.physical ? 'Physical location' : 'Planned door advisory';
      if (!handlingMatches(door, trailer)) warnings.push({
        code: reference.physical ? 'wrong-handling' : 'planned-handling', severity: 'warning', doorId: door.id, trailerIds: [trailer.id],
        message: `${label}: ${trailer.id} at ${door.id} does not meet ${trailer.handling} handling requirements.`,
      });
      if (trailer.profileKnown && !destinationMatches(door, trailer)) warnings.push({
        code: reference.physical ? 'wrong-destination' : 'planned-destination', severity: 'warning', doorId: door.id, trailerIds: [trailer.id],
        message: `${label}: ${door.id} does not match ${trailer.id}'s dominant destination${trailer.handling === 'crossdock' ? ' / dedicated transfer requirement' : ` zone ${dominantZones(trailer).join('/')}`}.`,
      });
      if (reference.physical && !door.enabled) warnings.push({
        code: 'disabled-occupied-door', severity: 'warning', doorId: door.id, trailerIds: [trailer.id],
        message: `${door.id} is disabled but physically occupied by ${trailer.id}; its workload and reservation remain.`,
      });
    }
  }
  const highWaiting = scenario.trailers.filter((trailer) => priorities[trailer.id]?.level === 'high' && !dataBlock(scenario, trailer));
  for (const [doorId, residents] of occupied) {
    const door = doors.get(doorId);
    if (!door?.enabled) continue;
    const lower = residents.filter((trailer) => PRIORITY_ORDER[priorities[trailer.id].level] > PRIORITY_ORDER.high);
    if (!lower.length) continue;
    const waiting = highWaiting.filter((trailer) => handlingMatches(door, trailer) && destinationMatches(door, trailer));
    if (waiting.length) warnings.push({
      code: 'priority-inversion', severity: 'warning', doorId, trailerIds: [...lower, ...waiting].map((trailer) => trailer.id),
      message: `${doorId} holds lower-priority work while compatible high-priority ${waiting.map((trailer) => trailer.id).join(', ')} waits. This is an advisory only; no swap is proposed or authorized.`,
    });
  }
  return warnings;
}

export function evaluate(scenario: Scenario, mode: PlanMode = 'priority'): Evaluation {
  const priorities: Record<string, PriorityDetail> = Object.create(null);
  for (const trailer of scenario.trailers) priorities[trailer.id] = priority(scenario, trailer);
  const queue = [...scenario.trailers].sort((a, b) =>
    Number(priorities[a.id].level === 'none') - Number(priorities[b.id].level === 'none')
    || (mode === 'priority' ? PRIORITY_ORDER[priorities[a.id].level] - PRIORITY_ORDER[priorities[b.id].level] || b.currentUnits - a.currentUnits : 0)
    || a.arrivalMinute - b.arrivalMinute || byId(a.id, b.id));
  const reserved = new Set<string>();
  const proposedUnits = new Map<ZoneId, number>();
  const recommendations: Recommendation[] = [];
  for (const [index, trailer] of queue.entries()) {
    if (trailer.status !== 'yard') continue;
    const eligible = candidates(scenario, trailer, reserved, proposedUnits);
    const primary = eligible[0] ?? null;
    recommendations.push({
      trailerId: trailer.id, rank: index + 1, priority: priorities[trailer.id].level, primary,
      alternatives: [], reason: primary ? primary.rationale.join(' ') : blockedReason(scenario, trailer, reserved),
    });
    if (primary) {
      reserved.add(primary.doorId);
      if (primary.zoneId) proposedUnits.set(primary.zoneId, (proposedUnits.get(primary.zoneId) ?? 0) + trailer.packageCount);
    }
  }
  // Final-primary exclusions are applied only after the full allocation pass.
  // Earlier proposals keep their original pressure context, never double-counting themselves.
  const priorUnits = new Map<ZoneId, number>();
  const trailersById = new Map(scenario.trailers.map((trailer) => [trailer.id, trailer]));
  for (const recommendation of recommendations) {
    const trailer = trailersById.get(recommendation.trailerId)!;
    recommendation.alternatives = recommendation.primary ? candidates(scenario, trailer, reserved, priorUnits) : [];
    if (recommendation.primary?.zoneId) priorUnits.set(recommendation.primary.zoneId, (priorUnits.get(recommendation.primary.zoneId) ?? 0) + trailer.packageCount);
  }
  const active = scenario.trailers.filter((trailer) => trailer.status !== 'complete');
  const occupied = occupancy(scenario);
  const zones = scenario.zones.map((zone) => {
    let onDoorUnits = 0, yardUnits = 0, expectedUnits = 0, heldUnits = 0;
    for (const trailer of active) {
      if (!trailer.profileKnown) continue;
      const units = trailer.zoneUnits[zone.id];
      if (trailer.status === 'at_door') onDoorUnits += units;
      if (trailer.status === 'yard') yardUnits += units;
      if (trailer.status === 'expected') expectedUnits += units;
      if (trailer.hold) heldUnits += units;
    }
    return {
      zoneId: zone.id, onDoorUnits, yardUnits, expectedUnits, heldUnits,
      totalUnits: onDoorUnits + yardUnits + expectedUnits, capacityUnits: zone.capacityUnits,
      pressurePercent: (onDoorUnits + yardUnits + expectedUnits) / zone.capacityUnits * 100,
    };
  });
  return {
    mode, priorities, queueIds: queue.map((trailer) => trailer.id), recommendations, zones,
    warnings: collectWarnings(scenario, priorities),
    metrics: {
      activeTrailers: active.length, yardTrailers: active.filter((trailer) => trailer.status === 'yard').length,
      urgentTrailers: active.filter((trailer) => trailer.currentUnits > 0).length,
      availableDoors: scenario.doors.filter((door) => door.enabled && !occupied.has(door.id)).length,
      totalPackages: active.reduce((sum, trailer) => sum + trailer.packageCount, 0),
      currentDuePackages: active.reduce((sum, trailer) => sum + trailer.currentUnits, 0),
      unmappedPackages: active.filter((trailer) => !trailer.profileKnown).reduce((sum, trailer) => sum + trailer.packageCount, 0),
      recommendationCount: recommendations.filter((recommendation) => recommendation.primary !== null).length,
      blockedCount: recommendations.filter((recommendation) => recommendation.primary === null).length,
    },
  };
}

export function applyAssignment(scenario: Scenario, trailerId: string, doorId: string, reason?: string): ActionResult {
  const trailer = scenario.trailers.find((item) => item.id === trailerId);
  if (!trailer) throw new Error(`Unknown trailer ${trailerId}; assignment was not applied.`);
  const block = dataBlock(scenario, trailer);
  if (block) throw new Error(block);
  const door = scenario.doors.find((item) => item.id === doorId);
  if (!door) throw new Error(`Unknown door ${doorId}; assignment was not applied.`);
  if (!door.enabled) throw new Error(`Door ${doorId} is disabled.`);
  if (occupancy(scenario).has(doorId)) throw new Error(`Door ${doorId} is physically occupied; recalculate before approving.`);
  if (!handlingMatches(door, trailer)) throw new Error(`Door ${doorId} is not compatible with ${trailer.handling} handling.`);
  if (!destinationMatches(door, trailer)) throw new Error(`Door ${doorId} is not compatible with the trailer's dominant destination.`);
  const next = cloneScenario(scenario);
  const updated = next.trailers.find((item) => item.id === trailerId)!;
  updated.status = 'at_door';
  updated.currentDoorId = doorId;
  return { scenario: next, event: { action: 'assign', trailerId, doorId, atMinute: scenario.nowMinute, reason: reason?.trim() || 'Operator approved a currently feasible synthetic assignment.' } };
}

export function completeTrailer(scenario: Scenario, trailerId: string): ActionResult {
  const trailer = scenario.trailers.find((item) => item.id === trailerId);
  if (!trailer) throw new Error(`Unknown trailer ${trailerId}.`);
  if (trailer.status !== 'at_door' || !trailer.currentDoorId) throw new Error('Only a trailer physically at a door can be marked unloaded.');
  const next = cloneScenario(scenario);
  const updated = next.trailers.find((item) => item.id === trailerId)!;
  updated.status = 'complete';
  updated.currentDoorId = null;
  return { scenario: next, event: { action: 'complete', trailerId, doorId: trailer.currentDoorId, atMinute: scenario.nowMinute, reason: 'Operator marked the synthetic load unloaded; physical location released.' } };
}

export function advanceClock(scenario: Scenario, minutes: number = 30): Scenario {
  if (!Number.isSafeInteger(minutes) || minutes < 0) throw new Error('Clock minutes must be a non-negative whole number.');
  const next = cloneScenario(scenario);
  next.nowMinute = Math.min(1440, scenario.nowMinute + minutes);
  for (const trailer of next.trailers) if (trailer.status === 'expected' && trailer.arrivalMinute <= next.nowMinute) trailer.status = 'yard';
  return next;
}

export function refreshSyntheticProfiles(scenario: Scenario): Scenario {
  const next = cloneScenario(scenario);
  for (const trailer of next.trailers) {
    if (trailer.profileKnown) trailer.profileUpdatedMinute = next.nowMinute;
  }
  return next;
}

type InputRecord = Record<string, unknown>;
const hasOwn = (object: InputRecord, key: string) => Object.prototype.hasOwnProperty.call(object, key);
function own(object: InputRecord, key: string): unknown {
  const descriptor = Object.getOwnPropertyDescriptor(object, key);
  if (!descriptor || !('value' in descriptor)) return undefined;
  return descriptor.value;
}
function isRecord(value: unknown): value is InputRecord {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function parseScenario(input: unknown): ParseResult {
  const errors: string[] = [];
  try {
    const record = (value: unknown, path: string): InputRecord => {
      if (!isRecord(value)) { errors.push(`${path} must be a plain object.`); return {}; }
      return value;
    };
    const integer = (value: unknown, path: string, maximum = MAX_COUNT, minimum = 0): number => {
      if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum || value > maximum) {
        errors.push(`${path} must be a whole number from ${minimum} to ${maximum}.`); return minimum;
      }
      return value;
    };
    const text = (value: unknown, path: string): string => {
      if (typeof value !== 'string' || !value.trim() || value.length > 80) { errors.push(`${path} must be 1–80 characters.`); return ''; }
      return value;
    };
    const identifier = (value: unknown, path: string): string => {
      if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,40}$/.test(value) || ['__proto__', 'constructor', 'prototype'].includes(value.toLowerCase())) {
        errors.push(`${path} must be a safe 1–40 character identifier.`); return '';
      }
      return value;
    };
    const bool = (value: unknown, path: string): boolean => {
      if (typeof value !== 'boolean') { errors.push(`${path} must be true or false.`); return false; }
      return value;
    };
    const enumeration = <T extends string>(value: unknown, options: readonly T[], path: string): T => {
      if (typeof value !== 'string' || !options.includes(value as T)) { errors.push(`${path} must be one of ${options.join(', ')}.`); return options[0]; }
      return value as T;
    };
    const list = (value: unknown, path: string, limit: number): unknown[] => {
      if (!Array.isArray(value)) { errors.push(`${path} must be an array.`); return []; }
      if (value.length > limit) { errors.push(`${path} may contain at most ${limit} entries.`); return value.slice(0, limit); }
      for (let index = 0; index < value.length; index++) {
        if (!Object.hasOwn(value, index)) errors.push(`${path} cannot contain missing entries.`);
      }
      return value;
    };
    const unique = (ids: string[], path: string) => {
      if (new Set(ids).size !== ids.length) errors.push(`${path} must have unique identifiers.`);
    };
    const source = record(input, 'Scenario');
    if (own(source, 'version') !== 1) errors.push('Scenario version must be 1.');
    if (own(source, 'synthetic') !== true) errors.push('Only explicitly synthetic scenarios can be imported.');
    const seed = integer(own(source, 'seed'), 'Seed', 0xffff_ffff);
    const name = text(own(source, 'name'), 'Facility name');
    const nowMinute = integer(own(source, 'nowMinute'), 'Current minute', 1440);
    const currentDeadlineMinute = integer(own(source, 'currentDeadlineMinute'), 'Current deadline', 1440);
    const nextDeadlineMinute = integer(own(source, 'nextDeadlineMinute'), 'Next deadline', 1440);
    if (nextDeadlineMinute <= currentDeadlineMinute) errors.push('The next deadline must be later than the current deadline.');
    const zones: Zone[] = list(own(source, 'zones'), 'Zones', 3).map((value, index) => {
      const zone = record(value, `Zone ${index + 1}`);
      return {
        id: enumeration(own(zone, 'id'), ZONES, `Zone ${index + 1} ID`),
        name: text(own(zone, 'name'), `Zone ${index + 1} name`),
        capacityUnits: integer(own(zone, 'capacityUnits'), `Zone ${index + 1} capacity`, MAX_COUNT, 1),
      };
    });
    if (zones.length !== 3 || new Set(zones.map((zone) => zone.id)).size !== 3) errors.push('Exactly one zone each of A, B and C is required.');
    const doors: Door[] = list(own(source, 'doors'), 'Doors', 30).map((value, index) => {
      const path = `Door ${index + 1}`;
      const door = record(value, path);
      const zoneId = own(door, 'zoneId') === null ? null : enumeration(own(door, 'zoneId'), ZONES, `${path} zone`);
      const allowedHandling = list(own(door, 'allowedHandling'), `${path} handling`, 4).map((item) => enumeration(item, HANDLING, `${path} handling`));
      if (!allowedHandling.length || new Set(allowedHandling).size !== allowedHandling.length) errors.push(`${path} requires unique, nonempty handling categories.`);
      if (zoneId === null ? allowedHandling.length !== 1 || allowedHandling[0] !== 'crossdock' : allowedHandling.includes('crossdock')) errors.push(`${path}: transfer doors must have null zone and only crossdock handling; ordinary doors require an A/B/C zone and ordinary handling.`);
      return { id: identifier(own(door, 'id'), `${path} ID`), zoneId, allowedHandling, enabled: bool(own(door, 'enabled'), `${path} enabled`) };
    });
    unique(doors.map((door) => door.id), 'Doors');
    const doorIds = new Set(doors.map((door) => door.id));
    const trailers: Trailer[] = list(own(source, 'trailers'), 'Trailers', 100).map((value, index) => {
      const path = `Trailer ${index + 1}`;
      const load = record(value, path);
      const nullableDoor = (key: string): string | null => {
        if (own(load, key) === null) return null;
        const id = identifier(own(load, key), `${path} ${key}`);
        if (!doorIds.has(id)) errors.push(`${path} ${key} references an unknown door.`);
        return id;
      };
      const zoneSource = record(own(load, 'zoneUnits'), `${path} destination units`);
      const zoneUnits = {
        A: integer(own(zoneSource, 'A'), `${path} zone A units`),
        B: integer(own(zoneSource, 'B'), `${path} zone B units`),
        C: integer(own(zoneSource, 'C'), `${path} zone C units`),
      };
      const profileKnown = bool(own(load, 'profileKnown'), `${path} profileKnown`);
      const profileUpdatedMinute = own(load, 'profileUpdatedMinute') === null ? null : integer(own(load, 'profileUpdatedMinute'), `${path} profile timestamp`, 1440);
      const packageCount = integer(own(load, 'packageCount'), `${path} package count`);
      const currentUnits = integer(own(load, 'currentUnits'), `${path} current deadline units`);
      const nextUnits = integer(own(load, 'nextUnits'), `${path} next deadline units`);
      if (currentUnits + nextUnits > packageCount) errors.push(`${path} deadline units cannot exceed its package count.`);
      const zoneTotal = zoneUnits.A + zoneUnits.B + zoneUnits.C;
      if (profileKnown && (zoneTotal !== packageCount || profileUpdatedMinute === null)) errors.push(`${path} known profile requires destination units equal to package count and a timestamp.`);
      if (!profileKnown && (zoneTotal !== 0 || profileUpdatedMinute !== null)) errors.push(`${path} unknown profile requires zero destination units and a null timestamp.`);
      if (profileUpdatedMinute !== null && profileUpdatedMinute > nowMinute) errors.push(`${path} profile timestamp cannot be in the future.`);
      const status = enumeration(own(load, 'status'), STATUSES, `${path} status`);
      const currentDoorId = nullableDoor('currentDoorId');
      if (status === 'at_door' ? currentDoorId === null : currentDoorId !== null) errors.push(`${path} must have a current door exactly when its status is at_door.`);
      return {
        id: identifier(own(load, 'id'), `${path} ID`), carrier: text(own(load, 'carrier'), `${path} carrier`),
        status, arrivalMinute: integer(own(load, 'arrivalMinute'), `${path} arrival`, 1440),
        handling: enumeration(own(load, 'handling'), HANDLING, `${path} handling`), packageCount, currentUnits, nextUnits,
        zoneUnits, profileKnown, profileUpdatedMinute, hold: bool(own(load, 'hold'), `${path} hold`),
        currentDoorId, plannedDoorId: nullableDoor('plannedDoorId'),
      };
    });
    unique(trailers.map((trailer) => trailer.id), 'Trailers');
    // Accessors/inherited fields never satisfy required schema fields; unknown fields are discarded.
    for (const field of ['version', 'synthetic', 'seed', 'name', 'nowMinute', 'currentDeadlineMinute', 'nextDeadlineMinute', 'zones', 'doors', 'trailers']) {
      if (!hasOwn(source, field)) errors.push(`Missing scenario field: ${field}.`);
    }
    return errors.length ? { ok: false, errors } : {
      ok: true, scenario: { version: 1, synthetic: true, seed, name, nowMinute, currentDeadlineMinute, nextDeadlineMinute, zones, doors, trailers },
    };
  } catch {
    return { ok: false, errors: ['Scenario could not be safely read. Import a plain synthetic JSON object.'] };
  }
}

export function exportScenarioCsv(scenario: Scenario, evaluation: Evaluation): string {
  const recommendations = new Map(evaluation.recommendations.map((item) => [item.trailerId, item]));
  const rows: Array<Array<string | number | boolean | null>> = [[
    'synthetic', 'facility', 'simulation_minute', 'plan_mode', 'trailer_id', 'carrier', 'status', 'handling',
    'priority', 'packages', 'current_deadline_packages', 'next_deadline_packages', 'hold', 'profile_known',
    'physical_door', 'planned_door_advisory', 'proposed_door', 'proposal_reason',
  ]];
  for (const trailer of scenario.trailers) {
    const proposal = recommendations.get(trailer.id);
    rows.push([
      true, scenario.name, scenario.nowMinute, evaluation.mode, trailer.id, trailer.carrier, trailer.status, trailer.handling,
      Object.prototype.hasOwnProperty.call(evaluation.priorities, trailer.id) ? evaluation.priorities[trailer.id].level : 'none',
      trailer.packageCount, trailer.currentUnits, trailer.nextUnits, trailer.hold, trailer.profileKnown,
      trailer.currentDoorId, trailer.plannedDoorId, proposal?.primary?.doorId ?? null,
      proposal?.reason ?? 'No new proposal for this state.',
    ]);
  }
  const cell = (value: string | number | boolean | null): string => {
    let content = value === null ? '' : String(value);
    // Quoting alone does not stop spreadsheet formula execution.
    if (/^\s*[=+@-]/.test(content) || /^[\t\r\n]/.test(content)) content = `'${content}`;
    return `"${content.replaceAll('"', '""')}"`;
  };
  return rows.map((row) => row.map(cell).join(',')).join('\r\n');
}
