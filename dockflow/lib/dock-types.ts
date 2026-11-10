export type ZoneId = 'A' | 'B' | 'C';
export type Handling = 'palletized' | 'cart' | 'loose' | 'crossdock';
export type TrailerStatus = 'yard' | 'expected' | 'at_door' | 'complete';
export type Priority = 'high' | 'medium' | 'low' | 'none';
export type PlanMode = 'priority' | 'arrival';
export type Preset = 'balanced' | 'surge' | 'disruption';

export interface Zone { id: ZoneId; name: string; capacityUnits: number }
export interface Door { id: string; zoneId: ZoneId | null; allowedHandling: Handling[]; enabled: boolean }
export interface Trailer {
  id: string;
  carrier: string;
  status: TrailerStatus;
  arrivalMinute: number;
  handling: Handling;
  packageCount: number;
  currentUnits: number;
  nextUnits: number;
  zoneUnits: Record<ZoneId, number>;
  profileKnown: boolean;
  profileUpdatedMinute: number | null;
  hold: boolean;
  currentDoorId: string | null;
  plannedDoorId: string | null;
}
export interface Scenario {
  version: 1;
  synthetic: true;
  seed: number;
  name: string;
  nowMinute: number;
  currentDeadlineMinute: number;
  nextDeadlineMinute: number;
  zones: Zone[];
  doors: Door[];
  trailers: Trailer[];
}
export interface PriorityDetail { level: Priority; reason: string; overdue: boolean }
export interface DoorCandidate {
  doorId: string;
  zoneId: ZoneId | null;
  zoneMatchPercent: number | null;
  projectedPressurePercent: number | null;
  rationale: string[];
}
export interface Recommendation {
  trailerId: string;
  rank: number;
  priority: Priority;
  primary: DoorCandidate | null;
  alternatives: DoorCandidate[];
  reason: string;
}
export interface ZoneDemand {
  zoneId: ZoneId;
  onDoorUnits: number;
  yardUnits: number;
  expectedUnits: number;
  heldUnits: number;
  totalUnits: number;
  capacityUnits: number;
  pressurePercent: number;
}
export interface Warning {
  code: string;
  severity: 'warning' | 'critical';
  message: string;
  trailerIds: string[];
  doorId?: string;
}
export interface Evaluation {
  mode: PlanMode;
  priorities: Record<string, PriorityDetail>;
  queueIds: string[];
  recommendations: Recommendation[];
  zones: ZoneDemand[];
  warnings: Warning[];
  metrics: {
    activeTrailers: number;
    yardTrailers: number;
    urgentTrailers: number;
    availableDoors: number;
    totalPackages: number;
    currentDuePackages: number;
    unmappedPackages: number;
    recommendationCount: number;
    blockedCount: number;
  };
}
export interface AuditEvent {
  action: 'assign' | 'complete';
  trailerId: string;
  doorId: string;
  atMinute: number;
  reason: string;
}
export interface ActionResult { scenario: Scenario; event: AuditEvent }
export type ParseResult = { ok: true; scenario: Scenario } | { ok: false; errors: string[] };
