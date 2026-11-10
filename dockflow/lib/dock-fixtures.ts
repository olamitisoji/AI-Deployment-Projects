import type { Handling, Preset, Scenario, Trailer, ZoneId } from './dock-types.ts';

// Every name, location, count and policy in these presets is fictional.
export function createScenario(preset: Preset = 'balanced', seed: number = 42): Scenario {
  if (!['balanced', 'surge', 'disruption'].includes(preset)) throw new Error('Unknown synthetic preset.');
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffff_ffff) throw new Error('Seed must be a whole number from 0 to 4294967295.');
  let randomState = seed >>> 0;
  const random = () => {
    randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
    return randomState / 0x1_0000_0000;
  };
  const surge = preset === 'surge';
  const disruption = preset === 'disruption';
  const volume = (base: number) => Math.round(base * (surge ? 1.55 : 1) * (0.9 + random() * 0.2));
  const mix = (packages: number, dominant: ZoneId): Record<ZoneId, number> => {
    const zones: ZoneId[] = ['A', 'B', 'C'];
    const index = zones.indexOf(dominant);
    const counts = [0, 0, 0];
    counts[index] = Math.round(packages * 0.68);
    counts[(index + 1) % 3] = Math.round(packages * 0.22);
    counts[(index + 2) % 3] = packages - counts[index] - counts[(index + 1) % 3];
    return { A: counts[0], B: counts[1], C: counts[2] };
  };
  const load = (id: string, carrier: string, base: number, dominant: ZoneId, handling: Handling, currentFraction: number, overrides: Partial<Trailer> = {}): Trailer => {
    const packageCount = volume(base);
    const currentUnits = Math.floor(packageCount * currentFraction);
    return {
      id, carrier, status: 'yard', arrivalMinute: 390 + Math.floor(random() * 180), handling,
      packageCount, currentUnits, nextUnits: Math.floor((packageCount - currentUnits) * 0.6),
      zoneUnits: mix(packageCount, dominant), profileKnown: true, profileUpdatedMinute: 580 + Math.floor(random() * 21),
      hold: false, currentDoorId: null, plannedDoorId: null, ...overrides,
    };
  };
  const trailers = [
    load('TR-101', 'Juniper Freight', 160, 'A', 'palletized', 0, { status: 'at_door', currentDoorId: 'A-01', hold: true, nextUnits: 0, arrivalMinute: 360 }),
    load('TR-102', 'Morrow Logistics', 220, 'B', 'cart', 0, { status: 'at_door', currentDoorId: 'B-01', arrivalMinute: 410 }),
    load('TR-103', 'Copperline Cargo', 360, 'A', 'palletized', 0.8, { plannedDoorId: 'A-01' }),
    load('TR-104', 'Cedar Road Transport', 290, 'B', 'cart', 0.75, { plannedDoorId: 'B-02' }),
    load('TR-105', 'Northstar Parcel Co.', 180, 'C', 'loose', 0, { plannedDoorId: 'C-01' }),
    load('TR-106', 'Bluebird Transfer', 240, 'B', 'crossdock', 0.65, { plannedDoorId: 'X-01' }),
    load('TR-107', 'Willow Route', 125, 'A', 'cart', 0.35, { profileKnown: false, profileUpdatedMinute: null, zoneUnits: { A: 0, B: 0, C: 0 } }),
    load('TR-108', 'Silverfern Freight', 210, 'C', 'palletized', 0.55, { profileUpdatedMinute: 505, plannedDoorId: 'C-02' }),
    load('TR-109', 'Orchard Transit', 280, 'B', 'palletized', 0.7, { status: 'expected', arrivalMinute: 625 + Math.floor(random() * 16) }),
    load('TR-110', 'Ember Lane', 90, 'A', 'loose', 0, { hold: true, plannedDoorId: 'A-02' }),
    load('TR-111', 'Linden Distribution', 200, 'A', 'palletized', surge ? 0.7 : 0),
    load('TR-112', 'Saffron Haulage', 150, 'C', 'loose', 0, { status: 'complete', nextUnits: 0, arrivalMinute: 300 }),
  ];
  // A tied A/B profile demonstrates pressure-based ranking without a fabricated winner.
  const tied = trailers[10];
  const half = Math.floor(tied.packageCount / 2);
  tied.zoneUnits = { A: half, B: half, C: tied.packageCount - 2 * half };
  if (disruption) {
    trailers[1].handling = 'loose'; // Known mismatch remains physically at B-01.
    trailers[4].hold = true;
    trailers[10].plannedDoorId = 'C-01'; // Advisory plan has the wrong destination.
  }
  return {
    version: 1, synthetic: true, seed,
    name: 'Northbank Inbound · Fictional Hub', nowMinute: 600, currentDeadlineMinute: 720, nextDeadlineMinute: 960,
    zones: [
      { id: 'A', name: 'North loop', capacityUnits: surge ? 700 : 900 },
      { id: 'B', name: 'Central loop', capacityUnits: surge ? 760 : 1000 },
      { id: 'C', name: 'South loop', capacityUnits: surge ? 600 : 800 },
    ],
    doors: [
      { id: 'A-01', zoneId: 'A', allowedHandling: ['palletized', 'cart'], enabled: true },
      { id: 'A-02', zoneId: 'A', allowedHandling: ['palletized', 'loose'], enabled: !disruption },
      { id: 'B-01', zoneId: 'B', allowedHandling: ['palletized', 'cart'], enabled: true },
      { id: 'B-02', zoneId: 'B', allowedHandling: ['palletized', 'cart'], enabled: true },
      { id: 'C-01', zoneId: 'C', allowedHandling: ['palletized', 'loose'], enabled: true },
      { id: 'C-02', zoneId: 'C', allowedHandling: ['palletized', 'loose'], enabled: true },
      { id: 'X-01', zoneId: null, allowedHandling: ['crossdock'], enabled: true },
    ],
    trailers,
  };
}
