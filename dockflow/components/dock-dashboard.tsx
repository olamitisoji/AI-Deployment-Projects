"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Activity, ArrowDownToLine, ArrowRight, Check, ChevronRight, Clock3, DoorOpen, FlaskConical, LayoutDashboard, ListOrdered, Package, RefreshCw, Search, Settings2, ShieldCheck, Truck, Undo2, Upload, Warehouse } from "lucide-react";
import { advanceClock, applyAssignment, completeTrailer, evaluate, exportScenarioCsv, feasibleDoors, parseScenario, refreshSyntheticProfiles } from "@/lib/dock-engine";
import { createScenario } from "@/lib/dock-fixtures";
import type { AuditEvent, PlanMode, Preset, Scenario, Trailer } from "@/lib/dock-types";

type View = "overview" | "queue" | "doors" | "assumptions";
type Session = { scenario: Scenario; audit: AuditEvent[] };
const STORAGE_KEY = "dockflow.synthetic.v1";
const number = (value: number) => value.toLocaleString("en-US");
const time = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const label = (value: string) => value === "at_door" ? "At door" : value.charAt(0).toUpperCase() + value.slice(1);
const initial = (): Session => ({ scenario: createScenario(), audit: [] });

// Files and browser storage are untrusted inputs: validate before using them.
function readSession(value: unknown): Session {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Choose a synthetic Dockflow JSON snapshot.");
  const record = value as Record<string, unknown>;
  const parsed = parseScenario(Object.hasOwn(record, "scenario") ? record.scenario : record);
  if (!parsed.ok) throw new Error(parsed.errors.slice(0, 3).join(" "));
  const sourceAudit = Object.hasOwn(record, "audit") ? record.audit : [];
  if (!Array.isArray(sourceAudit) || sourceAudit.length > 1000) throw new Error("Snapshot audit must contain at most 1,000 events.");
  const audit: AuditEvent[] = sourceAudit.map((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid audit event.");
    const event = raw as Record<string, unknown>;
    const fields = ["action", "trailerId", "doorId", "atMinute", "reason"];
    if (!fields.every((key) => Object.hasOwn(event, key)) || !["assign", "complete"].includes(event.action as string)
      || typeof event.trailerId !== "string" || !parsed.scenario.trailers.some((trailer) => trailer.id === event.trailerId)
      || typeof event.doorId !== "string" || !parsed.scenario.doors.some((door) => door.id === event.doorId)
      || !Number.isInteger(event.atMinute) || (event.atMinute as number) < 0 || (event.atMinute as number) > parsed.scenario.nowMinute
      || typeof event.reason !== "string" || event.reason.length > 500) throw new Error("Snapshot has an invalid audit event.");
    return { action: event.action as AuditEvent["action"], trailerId: event.trailerId, doorId: event.doorId, atMinute: event.atMinute as number, reason: event.reason };
  });
  return { scenario: parsed.scenario, audit };
}

function download(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export default function DockDashboard() {
  const [session, setSession] = useState<Session>(initial);
  const [history, setHistory] = useState<Session[]>([]);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState("Explore a fictional shift. Select a trailer to inspect its next move.");
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("overview");
  const [mode, setMode] = useState<PlanMode>("priority");
  const [preset, setPreset] = useState<Preset>("balanced");
  const [seed, setSeed] = useState("42");
  const [selectedId, setSelectedId] = useState("TR-103");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [chosenDoor, setChosenDoor] = useState("");
  const [reason, setReason] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const scenario = session.scenario;
  const result = useMemo(() => evaluate(scenario, mode), [scenario, mode]);
  const selected = scenario.trailers.find((trailer) => trailer.id === selectedId);
  const proposal = result.recommendations.find((item) => item.trailerId === selectedId);
  const eligible = useMemo(() => feasibleDoors(scenario, selectedId), [scenario, selectedId]);
  const targetDoor = eligible.some((door) => door.doorId === chosenDoor) ? chosenDoor : proposal?.primary?.doorId ?? eligible[0]?.doorId ?? "";
  const target = proposal?.primary?.doorId === targetDoor ? proposal.primary : eligible.find((door) => door.doorId === targetDoor);
  const manual = !!targetDoor && targetDoor !== proposal?.primary?.doorId;
  const visibleTrailers = result.queueIds.map((id) => scenario.trailers.find((trailer) => trailer.id === id)!).filter((trailer) => {
    const matchesFilter = filter === "all" || trailer.status === filter || (filter === "high" && result.priorities[trailer.id].level === "high");
    return matchesFilter && `${trailer.id} ${trailer.carrier} ${trailer.handling}`.toLowerCase().includes(search.toLowerCase());
  });

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        if (saved.length > 2_000_000) throw new Error("Saved snapshot is too large.");
        const restored = readSession(JSON.parse(saved));
        setSession(restored);
        setSeed(String(restored.scenario.seed));
        setNotice("Restored your synthetic snapshot from this browser.");
      }
    } catch { setError("Saved browser data could not be restored. A fresh fictional scenario is loaded."); }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(session)); }
    catch { setError("Browser storage is unavailable. Export JSON to keep this snapshot."); }
  }, [session, ready]);

  function commit(next: Session, message: string) {
    setHistory((previous) => [...previous.slice(-29), session]);
    setSession(next);
    setError("");
    setNotice(message);
  }
  function changeScenario(next: Scenario, message: string) {
    const parsed = parseScenario(next);
    if (!parsed.ok) { setError(parsed.errors.join(" ")); return; }
    commit({ ...session, scenario: parsed.scenario }, message);
  }
  function inspect(id: string) { setSelectedId(id); setChosenDoor(""); setReason(""); }
  function accept() {
    if (!selected || !targetDoor) return;
    if (manual && !reason.trim()) { setError("Add a reason for choosing a different feasible door."); return; }
    try {
      const action = applyAssignment(scenario, selected.id, targetDoor, reason || `Accepted ${mode}-order proposal after reviewing its constraints.`);
      commit({ scenario: action.scenario, audit: [...session.audit, action.event].slice(-1000) }, `${selected.id} assigned to ${targetDoor} in the simulation.`);
      setChosenDoor(""); setReason("");
    } catch (caught) { setError((caught as Error).message); }
  }
  function finish() {
    if (!selected) return;
    try {
      const action = completeTrailer(scenario, selected.id);
      commit({ scenario: action.scenario, audit: [...session.audit, action.event].slice(-1000) }, `${selected.id} marked unloaded. Its physical door is released.`);
    } catch (caught) { setError((caught as Error).message); }
  }
  function reset() {
    try {
      const numericSeed = Number(seed);
      if (!seed.trim()) throw new Error("Enter a whole-number seed.");
      commit({ scenario: createScenario(preset, numericSeed), audit: [] }, `Loaded ${preset} scenario with seed ${numericSeed}.`);
      inspect("TR-103"); setFilter("all"); setSearch("");
    } catch (caught) { setError((caught as Error).message); }
  }
  async function importFile(file?: File) {
    if (!file) return;
    try {
      if (file.size > 2_000_000) throw new Error("Choose a JSON file smaller than 2 MB.");
      const imported = readSession(JSON.parse(await file.text()));
      commit(imported, "Imported and validated a synthetic snapshot. Imported history is supplied by the file, not verified operational evidence.");
      setSeed(String(imported.scenario.seed)); setSelectedId(imported.scenario.trailers[0]?.id ?? "");
      setSearch(""); setFilter("all"); setChosenDoor(""); setReason("");
    } catch (caught) { setError(`Import rejected. ${(caught as Error).message} Your scenario is unchanged.`); }
    if (fileRef.current) fileRef.current.value = "";
  }

  const nav: { id: View; title: string; icon: typeof Warehouse }[] = [
    { id: "overview", title: "Shift overview", icon: LayoutDashboard },
    { id: "queue", title: "Priority queue", icon: ListOrdered },
    { id: "doors", title: "Door plan", icon: Warehouse },
    { id: "assumptions", title: "Rules & scenarios", icon: Settings2 },
  ];

  const queue = <section className="panel queue-panel" aria-label="Trailer queue">
    <div className="panel-heading"><div><span className="eyebrow">THE NEXT MOVE</span><h2>Inbound queue <span className="count">{visibleTrailers.length}</span></h2></div><Badge tone="teal">{result.metrics.recommendationCount} proposals</Badge></div>
    <div className="queue-tools"><label className="search"><Search size={16} /><input aria-label="Search trailers" placeholder="Search trailer or carrier…" value={search} onChange={(event) => setSearch(event.target.value)} /></label><select aria-label="Filter trailers" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All trailers</option><option value="yard">In yard</option><option value="at_door">At door</option><option value="expected">Expected</option><option value="complete">Completed</option><option value="high">High priority</option></select></div>
    <div className="table-scroll"><table><thead><tr><th>Trailer / carrier</th><th>Priority</th><th>Status</th><th>Due now*</th><th>Packages</th><th>Next door</th></tr></thead><tbody>
      {visibleTrailers.map((trailer) => {
        const recommendation = result.recommendations.find((item) => item.trailerId === trailer.id);
        return <tr key={trailer.id} className={selectedId === trailer.id ? "selected" : ""}><td><button className="row-select" onClick={() => inspect(trailer.id)} aria-label={`Inspect ${trailer.id}`}><strong>{trailer.id}</strong><span>{trailer.carrier}</span></button></td><td><Badge tone={result.priorities[trailer.id].level}>{label(result.priorities[trailer.id].level)}</Badge>{result.priorities[trailer.id].overdue && <small className="late">Overdue</small>}</td><td><span className={`status-dot ${trailer.status}`} />{label(trailer.status)}{trailer.hold && <small className="held">On hold</small>}</td><td className="numeric">{number(trailer.currentUnits)}</td><td className="numeric">{number(trailer.packageCount)}</td><td>{trailer.status === "yard" ? recommendation?.primary ? <button className="door-link" onClick={() => inspect(trailer.id)}>{recommendation.primary.doorId}<ArrowRight size={13} /></button> : <span className="muted">Review</span> : <span className="muted">{trailer.currentDoorId ?? "—"}</span>}</td></tr>;
      })}
    </tbody></table>{!visibleTrailers.length && <p className="empty">No trailers match this view. Change the filter or search.</p>}</div>
    <div className="panel-foot">*Current deadline bucket · due by {time(scenario.currentDeadlineMinute)}. Summary totals include all active trailers, regardless of filters.</div>
  </section>;

  const inspector = <aside className="panel inspector" aria-label="Trailer inspector"><div className="panel-heading"><span className="eyebrow">DECISION INSPECTOR</span><ShieldCheck size={18} /></div>{selected ? <>
    <div className="inspector-title"><div><h2>{selected.id}</h2><p>{selected.carrier}</p></div><Badge tone={result.priorities[selected.id].level}>{label(result.priorities[selected.id].level)}</Badge></div>
    <div className="detail-grid"><div><span>Handling</span><strong>{label(selected.handling)}</strong></div><div><span>Arrival</span><strong>{time(selected.arrivalMinute)}</strong></div><div><span>Next deadline</span><strong>{number(selected.nextUnits)} packages</strong></div><div><span>Imported plan</span><strong>{selected.plannedDoorId ?? "None"}</strong></div></div>
    <div className="inspector-block"><h3>Why this priority?</h3><p>{result.priorities[selected.id].reason}</p></div>
    <div className="profile"><span>Destination profile</span><Badge tone={!selected.profileKnown || scenario.nowMinute - (selected.profileUpdatedMinute ?? 0) > 60 ? "medium" : "teal"}>{!selected.profileKnown ? "Unknown" : `${scenario.nowMinute - selected.profileUpdatedMinute!}m old`}</Badge></div>
    <div className="mix">{scenario.zones.map((zone) => <div key={zone.id}><small>Zone {zone.id}</small><strong>{selected.profileKnown ? number(selected.zoneUnits[zone.id]) : "—"}</strong></div>)}</div>
    {selected.status === "yard" ? <div className="recommendation"><span className="eyebrow">{proposal?.primary ? "SUGGESTED NEXT MOVE" : "REVIEW REQUIRED"}</span><h3>{proposal?.primary ? `Assign to ${proposal.primary.doorId}` : "No proposed door"}</h3><p>{proposal?.reason}</p>{eligible.length > 0 && <>
      <label className="field">Choose a currently feasible door<select aria-label="Assignment door" value={targetDoor} onChange={(event) => setChosenDoor(event.target.value)}>{eligible.map((door) => <option key={door.doorId} value={door.doorId}>{door.doorId}{door.doorId === proposal?.primary?.doorId ? " · proposed" : " · manual choice"}</option>)}</select></label>
      <div className="candidate-stats"><span>Destination match <strong>{target?.zoneMatchPercent == null ? "N/A · transfer" : `${Math.round(target.zoneMatchPercent)}%`}</strong></span><span>{manual ? "Load after this assignment" : "Projected door-zone load"} <strong>{target?.projectedPressurePercent == null ? "N/A · transfer" : `${Math.round(target.projectedPressurePercent)}%`}</strong></span></div>
      <label className="field">{manual ? "Reason for manual choice (required)" : "Decision note (optional)"}<textarea aria-label="Decision note" maxLength={500} rows={2} placeholder="What informed this decision?" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      {manual && <p className="small-note">A manual choice may use another trailer’s proposed door. The full plan recalculates after acceptance.</p>}
      <button className="button primary full" disabled={!ready || (manual && !reason.trim())} onClick={accept}><Check size={16} />Accept simulated assignment</button>
    </>}</div> : selected.status === "at_door" ? <div className="recommendation"><span className="eyebrow">PHYSICAL OCCUPANCY</span><h3>At {selected.currentDoorId}</h3><p>This door stays occupied while the load is on hold. Mark unloaded to complete its simulated work.</p><button className="button primary full" disabled={!ready} onClick={finish}><Check size={16} />Mark unloaded</button></div> : <div className="inspector-block"><h3>{selected.status === "expected" ? "Awaiting arrival" : "Work completed"}</h3><p>{selected.status === "expected" ? "Advance the simulated clock to its arrival time before assigning a door." : "This trailer is excluded from active workload and new door proposals."}</p></div>}
    {selected.status !== "complete" && <label className="hold-toggle"><input type="checkbox" checked={selected.hold} onChange={() => changeScenario({ ...scenario, trailers: scenario.trailers.map((trailer) => trailer.id === selected.id ? { ...trailer, hold: !trailer.hold } : trailer) }, `${selected.id} planning hold ${selected.hold ? "removed" : "applied"}. Physical occupancy is unchanged.`)} />Planning hold <span>Blocks new assignments</span></label>}
    <div className="inspector-block"><h3>Assignment history</h3>{session.audit.filter((event) => event.trailerId === selected.id).slice(-4).reverse().map((event, index) => <div className="audit-event" key={`${event.atMinute}-${index}`}><span>{time(event.atMinute)}</span><div><strong>{event.action === "assign" ? `Assigned to ${event.doorId}` : `Unloaded from ${event.doorId}`}</strong><p>{event.reason}</p></div></div>)}{!session.audit.some((event) => event.trailerId === selected.id) && <p>No simulated actions recorded yet.</p>}</div>
  </> : <p className="empty">Select a trailer in the queue or door plan.</p>}</aside>;

  const doorPlan = <section className="panel"><div className="panel-heading"><div><span className="eyebrow">PHYSICAL STATE</span><h2>Door plan</h2></div><Badge>{result.metrics.availableDoors} enabled & empty</Badge></div><div className="door-grid">{scenario.doors.map((door) => {
    const occupants = scenario.trailers.filter((trailer) => trailer.status === "at_door" && trailer.currentDoorId === door.id);
    const recommended = result.recommendations.find((item) => item.primary?.doorId === door.id);
    return <article key={door.id} className={`door-card ${!door.enabled ? "disabled-door" : occupants.length ? "occupied" : "open"}`}><div className="door-top"><DoorOpen size={22} /><strong>{door.id}</strong><Badge tone={occupants.length > 1 ? "high" : occupants.length ? "neutral" : door.enabled ? "teal" : "medium"}>{occupants.length ? "Occupied" : door.enabled ? "Available" : "Disabled"}</Badge></div><p>{door.zoneId ? `Zone ${door.zoneId}` : "Dedicated transfer"} · {door.allowedHandling.map(label).join(" / ")}</p>{occupants.map((trailer) => <button className="occupant" key={trailer.id} onClick={() => inspect(trailer.id)}><Truck size={16} /><span>{trailer.id}{trailer.hold ? " · held" : ""}</span><ChevronRight size={16} /></button>)}{!occupants.length && (recommended ? <button className="proposed-load" onClick={() => inspect(recommended.trailerId)}>Proposed: {recommended.trailerId} <ArrowRight size={14} /></button> : <div className="no-proposal">No proposal</div>)}<label className="door-toggle"><input type="checkbox" aria-label={`Enable ${door.id} for new assignments`} checked={door.enabled} onChange={() => changeScenario({ ...scenario, doors: scenario.doors.map((item) => item.id === door.id ? { ...item, enabled: !item.enabled } : item) }, `${door.id} ${door.enabled ? "disabled" : "enabled"}. Existing physical occupancy is preserved.`)} />Enabled for new assignments</label></article>;
  })}</div><div className="panel-foot">Proposals are advisory. Empty doors remain physically empty until an operator accepts an assignment.</div></section>;

  return <div className="dock-shell"><aside className="sidebar"><a className="brand" href="#main"><span className="brand-mark"><Warehouse size={24} /></span><span>dockflow<span className="brand-sub">INBOUND OPERATIONS LAB</span></span></a><div className="workspace-label">WORKSPACE</div><div className="facility"><span className="facility-icon"><Warehouse size={18} /></span><div><strong>{scenario.name.split(" · ")[0]}</strong><span>Fictional facility</span></div></div><nav aria-label="Main navigation">{nav.map(({ id, title, icon: Icon }) => <button key={id} aria-current={view === id ? "page" : undefined} className={view === id ? "active" : ""} onClick={() => setView(id)}><Icon size={18} />{title}{view === id && <span className="nav-indicator" />}</button>)}</nav><div className="sidebar-bottom"><FlaskConical size={21} /><strong>Built to explore</strong><p>Synthetic data. Transparent rules. You make the final call.</p><span className="lab-version">INDEPENDENT DEMO · V0.1</span></div></aside>
    <main id="main"><header className="topbar"><div><span className="breadcrumb">Operations lab</span><ChevronRight size={13} /><strong>{nav.find((item) => item.id === view)?.title}</strong></div><Badge tone="teal"><span className="live-dot" />Synthetic sandbox</Badge></header>
    <div className="main-content"><div className="page-heading"><div><span className="eyebrow">MAKE THE NEXT MOVE CLEAR</span><h1>{view === "overview" ? "A clearer view of inbound." : nav.find((item) => item.id === view)?.title}</h1><p>Prioritize the work. Match the door. Keep the operator in control.</p></div><div className="clock"><Clock3 size={18} /><strong>{time(scenario.nowMinute)}</strong><span>Simulated time</span></div></div>
      <div className="command-bar"><div className="command-group"><label>Load preset<select aria-label="Scenario preset" value={preset} onChange={(event) => setPreset(event.target.value as Preset)}><option value="balanced">Balanced</option><option value="surge">Volume surge</option><option value="disruption">Disruption</option></select></label><label className="seed-label">Seed<input aria-label="Scenario seed" value={seed} inputMode="numeric" onChange={(event) => setSeed(event.target.value)} /></label><button className="button" disabled={!ready} onClick={reset}><RefreshCw size={14} />Load / reset</button></div><div className="command-group"><button className="button" disabled={!ready || scenario.nowMinute >= 1440} onClick={() => changeScenario(advanceClock(scenario), "Clock advanced by up to 30 minutes. Eligible arrivals moved into the yard.")}><Clock3 size={14} />+30 min</button><button className="button" disabled={!ready} onClick={() => changeScenario(refreshSyntheticProfiles(scenario), "Known synthetic profiles refreshed. Unknown profiles remain unknown.")}><RefreshCw size={14} />Refresh profiles</button><button className="button" disabled={!history.length} onClick={() => { const previous = history[history.length - 1]; if (previous) { setSession(previous); setHistory(history.slice(0, -1)); setSeed(String(previous.scenario.seed)); setNotice("Previous scenario and action history restored."); setError(""); } }}><Undo2 size={14} />Undo</button></div></div>
      <div role="status" className={`notice ${error ? "notice-error" : ""}`}><Activity size={15} /><span>{error || notice}</span></div>
      <div className="metrics">{[
        { title: "Active trailers", value: number(result.metrics.activeTrailers), foot: `${result.metrics.yardTrailers} waiting in yard`, icon: Truck },
        { title: "Current-deadline packages", value: number(result.metrics.currentDuePackages), foot: `Due by ${time(scenario.currentDeadlineMinute)}`, icon: Clock3 },
        { title: "Available doors", value: `${result.metrics.availableDoors} / ${scenario.doors.length}`, foot: "Enabled and physically empty", icon: DoorOpen },
        { title: "Blocked yard loads", value: number(result.metrics.blockedCount), foot: `${number(result.metrics.unmappedPackages)} unmapped packages`, icon: ShieldCheck },
      ].map(({ title, value, foot, icon: Icon }) => <section className="metric" key={title}><div><span>{title}</span><Icon size={17} /></div><strong>{value}</strong><small>{foot}</small></section>)}</div>

      {view === "overview" && <div className="overview-grid"><section className="panel demand"><div className="panel-heading"><div><span className="eyebrow">WHERE THE VOLUME IS GOING</span><h2>Destination demand</h2></div><span className="legend"><i />At door <i />Yard <i />Expected</span></div><div className="zone-list">{result.zones.map((zone) => <div className="zone-row" key={zone.zoneId}><div className="zone-name"><span>{zone.zoneId}</span><div><strong>{scenario.zones.find((item) => item.id === zone.zoneId)?.name}</strong><small>{number(zone.totalUnits)} / {number(zone.capacityUnits)} configured capacity</small></div></div><div className="zone-chart"><div className="bar">{[zone.onDoorUnits, zone.yardUnits, zone.expectedUnits].map((units, index) => <span key={index} style={{ width: `${zone.totalUnits ? units / zone.totalUnits * Math.min(zone.pressurePercent, 100) : 0}%` }} />)}</div><small>{number(zone.heldUnits)} held packages included</small></div><strong className={zone.pressurePercent > 100 ? "over-capacity" : ""}>{Math.round(zone.pressurePercent)}%</strong></div>)}</div><div className="panel-foot">Known destination demand ÷ fictional capacity. Unmapped volume is shown separately. This is not measured utilization.</div></section><section className="panel exceptions"><div className="panel-heading"><div><span className="eyebrow">NEEDS A CLOSER LOOK</span><h2>Exceptions <span className="count">{result.warnings.length}</span></h2></div></div><div className="exception-list">{result.warnings.map((warning, index) => <button key={`${warning.code}-${index}`} onClick={() => inspect(warning.trailerIds[0] ?? "")} className="exception"><span className={`exception-dot ${warning.severity}`} /><span><strong>{warning.code.replaceAll("_", " ")}</strong><span>{warning.message}</span></span><ChevronRight size={15} /></button>)}{!result.warnings.length && <p className="empty">No configured exceptions in this snapshot.</p>}</div></section></div>}

      {(view === "overview" || view === "queue") && <><div className="section-bar"><div><h2>Plan the next move</h2><p>Queue order changes proposals. Every assignment still passes the same constraints.</p></div><label className="mode-switch">Plan order<select aria-label="Plan order" value={mode} onChange={(event) => setMode(event.target.value as PlanMode)}><option value="priority">Deadline priority</option><option value="arrival">Arrival order</option></select></label></div><div className="workspace-grid">{queue}{inspector}</div></>}
      {view === "doors" && <div className="workspace-grid doors-workspace">{doorPlan}{inspector}</div>}
      {view === "assumptions" && <div className="assumptions-grid"><section className="panel rules"><div className="panel-heading"><div><span className="eyebrow">THE POLICY IS VISIBLE</span><h2>How a proposal is made</h2></div></div><ol><li><strong>Order the work.</strong> Current-deadline volume comes first, then next-deadline volume, then other unfinished work. Compare with arrival order.</li><li><strong>Check eligibility.</strong> The trailer must be in the yard, arrived, nonempty, unheld, and have a known profile no older than 60 simulated minutes.</li><li><strong>Respect physical constraints.</strong> Doors must be enabled and empty. Ordinary loads require both compatible handling and a dominant destination zone. Crossdock uses the dedicated transfer door.</li><li><strong>Propose, then recheck.</strong> The greedy planner picks a free door in queue order. Accepting a proposal rechecks the latest state and records a local event.</li></ol><div className="rule-note"><FlaskConical size={20} /><p>These are invented demonstration policies. Capacity ratios are descriptive, not throughput forecasts. The clock covers one fictional day; it does not model calendars, overnight shifts, unloading duration or staffing.</p></div></section><section className="panel rules"><div className="panel-heading"><div><span className="eyebrow">TRY A DIFFERENT ASSUMPTION</span><h2>Zone capacities</h2></div></div><p>Change the fictional denominator used in demand and proposed door-zone load ratios.</p>{scenario.zones.map((zone) => <label className="capacity-field" key={`${zone.id}-${zone.capacityUnits}`}>Zone {zone.id} · {zone.name}<input aria-label={`Zone ${zone.id} capacity`} type="number" min="1" max="1000000" defaultValue={zone.capacityUnits} onBlur={(event) => { const value = Number(event.target.value); if (value !== zone.capacityUnits) changeScenario({ ...scenario, zones: scenario.zones.map((item) => item.id === zone.id ? { ...item, capacityUnits: value } : item) }, `Zone ${zone.id} capacity updated.`); }} /></label>)}<p className="small-note">Capacity saves when you leave a field. Door enablement is editable in Door plan; trailer holds are editable in the inspector.</p><div className="rule-note"><Package size={20} /><p>Refresh profiles only updates known synthetic timestamps. Missing information remains missing. No operational service is contacted.</p></div></section><section className="panel rules full-span"><div className="panel-heading"><h2>Local action history <span className="count">{session.audit.length}</span></h2></div>{session.audit.length ? <div className="table-scroll"><table><thead><tr><th>Time</th><th>Action</th><th>Trailer</th><th>Door</th><th>Decision note</th></tr></thead><tbody>{[...session.audit].reverse().map((event, index) => <tr key={index}><td>{time(event.atMinute)}</td><td>{label(event.action)}</td><td>{event.trailerId}</td><td>{event.doorId}</td><td>{event.reason}</td></tr>)}</tbody></table></div> : <p>No assignments or completions recorded yet. Accept a proposal to begin.</p>}<p className="small-note">Stored in this browser only, up to 1,000 events. Undo restores the previous snapshot. This is an editable simulation history, not an operational audit system.</p></section></div>}

      <footer className="footer"><div><strong>Independent rebuild · entirely synthetic</strong><span>No live feeds, external dispatch or AI API required. Saved in this browser.</span></div><div className="export-actions"><button className="button" onClick={() => download(JSON.stringify(session, null, 2), "dockflow-synthetic-snapshot.json", "application/json")}><ArrowDownToLine size={14} />JSON</button><button className="button" onClick={() => download(exportScenarioCsv(scenario, result), "dockflow-synthetic-queue.csv", "text/csv")}><ArrowDownToLine size={14} />CSV</button><button className="button" disabled={!ready} onClick={() => fileRef.current?.click()}><Upload size={14} />Import JSON</button><input className="visually-hidden" type="file" accept=".json,application/json" ref={fileRef} aria-label="Import synthetic snapshot" onChange={(event) => void importFile(event.target.files?.[0])} /></div></footer>
    </div></main>
  </div>;
}
