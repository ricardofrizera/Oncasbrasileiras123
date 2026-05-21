"""
Boston Road Traffic Management System
Covers I-93, I-90 (Mass Pike), and Route 1 with adaptive signal control,
congestion-aware rerouting (Dijkstra), and incident detection.
"""

import math
import heapq
import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class Intersection:
    id: str
    name: str
    lat: float
    lon: float
    has_signal: bool = True


@dataclass
class Road:
    id: str
    name: str
    from_id: str
    to_id: str
    length_km: float
    speed_limit_kmh: float
    congestion: float       # 0.0 = free flow, 1.0 = standstill
    lanes: int = 2
    highway: bool = False

    @property
    def free_flow_time_min(self) -> float:
        return (self.length_km / self.speed_limit_kmh) * 60

    @property
    def actual_time_min(self) -> float:
        # BPR (Bureau of Public Roads) volume-delay function
        alpha, beta = 0.15, 4
        return self.free_flow_time_min * (1 + alpha * self.congestion ** beta)

    @property
    def congestion_label(self) -> str:
        if self.congestion < 0.40: return "Free"
        if self.congestion < 0.65: return "Moderate"
        if self.congestion < 0.85: return "Heavy"
        return "Standstill"


@dataclass
class Incident:
    road_id: str
    type: str           # accident, debris, construction, stall
    severity: float     # 0–1; blocks this fraction of capacity
    description: str
    active: bool = True


@dataclass
class SignalPhase:
    direction: str      # N-S or E-W
    green_sec: int
    yellow_sec: int = 4
    red_sec: int = 0    # computed from total cycle

    @property
    def cycle_share(self) -> float:
        return self.green_sec / (self.green_sec + self.yellow_sec)


# ── Sample Boston Highway Network ─────────────────────────────────────────────

INTERSECTIONS: dict[str, Intersection] = {
    "zakim":         Intersection("zakim",         "Zakim Bridge / I-93 N",       42.3693, -71.0654, has_signal=False),
    "leverett":      Intersection("leverett",      "Leverett Circle",              42.3648, -71.0674),
    "govt_center":   Intersection("govt_center",   "Government Center",            42.3601, -71.0590),
    "south_bay":     Intersection("south_bay",     "South Bay Interchange I-93/90",42.3340, -71.0580, has_signal=False),
    "allston":       Intersection("allston",       "I-90 Allston/Brighton Exit",   42.3533, -71.1198, has_signal=False),
    "mass_pike_east":Intersection("mass_pike_east","I-90 Prudential / Copley",     42.3462, -71.0834, has_signal=False),
    "kenmore":       Intersection("kenmore",       "Kenmore Square",               42.3484, -71.0975),
    "longfellow":    Intersection("longfellow",    "Longfellow Bridge",            42.3614, -71.0740, has_signal=False),
    "harvard_bridge":Intersection("harvard_bridge","Harvard Bridge / Mass Ave",    42.3494, -71.0825, has_signal=False),
    "route1_north":  Intersection("route1_north",  "Route 1 N — Revere/Chelsea",   42.3893, -71.0350, has_signal=False),
    "route1_south":  Intersection("route1_south",  "Route 1 S — Dedham",           42.2650, -71.0954, has_signal=False),
    "neponset":      Intersection("neponset",      "I-93 S — Neponset Exit",       42.2820, -71.0520, has_signal=False),
    "sullivan":      Intersection("sullivan",      "Sullivan Square / I-93 N",     42.3835, -71.0760),
    "copley":        Intersection("copley",        "Copley Square",                42.3496, -71.0773),
}

ROADS: list[Road] = [
    # I-93 backbone
    Road("i93_zakim_leverett",  "I-93 S — Zakim→Leverett",   "zakim",          "leverett",       0.6,  88, congestion=0.55, lanes=4, highway=True),
    Road("i93_leverett_sb",     "I-93 S — Leverett→SouthBay","leverett",       "south_bay",      3.8,  88, congestion=0.82, lanes=4, highway=True),
    Road("i93_sb_neponset",     "I-93 S — SouthBay→Neponset","south_bay",      "neponset",       5.1,  88, congestion=0.45, lanes=4, highway=True),
    Road("i93_zakim_sullivan",  "I-93 N — Zakim→Sullivan",   "zakim",          "sullivan",       2.9,  88, congestion=0.68, lanes=4, highway=True),
    Road("i93_sullivan_route1", "I-93 N — Sullivan→Route1N", "sullivan",       "route1_north",   4.2,  88, congestion=0.40, lanes=3, highway=True),

    # I-90 (Mass Pike)
    Road("i90_allston_east",    "I-90 E — Allston→Prudential","allston",       "mass_pike_east", 4.8,  88, congestion=0.75, lanes=3, highway=True),
    Road("i90_east_sb",         "I-90 E — Prudential→SouthBay","mass_pike_east","south_bay",     1.6,  88, congestion=0.88, lanes=3, highway=True),

    # Route 1
    Road("rt1_north_sullivan",  "Route 1 N — Chelsea→Sullivan","route1_north", "sullivan",       3.1,  72, congestion=0.60, lanes=3, highway=True),
    Road("rt1_south_neponset",  "Route 1 S — Neponset→Dedham","neponset",      "route1_south",   6.8,  72, congestion=0.35, lanes=2, highway=True),

    # Urban arterials
    Road("storrow_w",           "Storrow Dr W — Leverett→Kenmore","leverett",  "kenmore",        3.5,  56, congestion=0.72, lanes=2),
    Road("comm_ave",            "Commonwealth Ave",            "kenmore",       "mass_pike_east", 1.8,  48, congestion=0.65, lanes=2),
    Road("longfellow_bridge",   "Longfellow Bridge",           "leverett",      "longfellow",     0.9,  48, congestion=0.50, lanes=2),
    Road("harvard_bridge_rd",   "Harvard Bridge",              "longfellow",    "harvard_bridge", 0.8,  48, congestion=0.48, lanes=2),
    Road("mass_ave_south",      "Mass Ave S — Harvard→Copley", "harvard_bridge","copley",         2.1,  48, congestion=0.60, lanes=2),
    Road("boylston",            "Boylston St",                 "copley",        "govt_center",    1.5,  40, congestion=0.78, lanes=2),
    Road("tremont",             "Tremont St",                  "govt_center",   "south_bay",      2.2,  40, congestion=0.70, lanes=2),
]

SAMPLE_INCIDENTS: list[Incident] = [
    Incident("i93_leverett_sb",  "accident",     0.50, "Multi-vehicle collision near exit 26 — 2 lanes blocked"),
    Incident("i90_east_sb",      "construction", 0.35, "Lane closure for bridge deck repair — delays expected"),
    Incident("boylston",         "stall",        0.25, "Disabled vehicle blocking right lane near Arlington St"),
]


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_road_graph(
    roads: list[Road],
    incidents: Optional[list[Incident]] = None,
) -> dict[str, dict[str, float]]:
    """Weighted directed graph; edge weight = actual travel time in minutes."""
    blocked: dict[str, float] = {}
    if incidents:
        for inc in incidents:
            if inc.active:
                blocked[inc.road_id] = inc.severity

    graph: dict[str, dict[str, float]] = defaultdict(dict)
    for road in roads:
        t = road.actual_time_min
        if road.id in blocked:
            t *= 1 + blocked[road.id] * 2   # incident penalty
        # bidirectional
        graph[road.from_id][road.to_id] = t
        graph[road.to_id][road.from_id] = t

    return graph


# ── Shortest / Fastest Path (Dijkstra) ───────────────────────────────────────

def dijkstra(
    graph: dict[str, dict[str, float]],
    source: str,
    target: str,
) -> tuple[float, list[str]]:
    dist: dict[str, float] = defaultdict(lambda: math.inf)
    prev: dict[str, Optional[str]] = {}
    dist[source] = 0.0
    pq: list[tuple[float, str]] = [(0.0, source)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == target:
            break
        for v, w in graph.get(u, {}).items():
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    path: list[str] = []
    node: Optional[str] = target
    while node is not None:
        path.append(node)
        node = prev.get(node)
    path.reverse()
    if not path or path[0] != source:
        return math.inf, []
    return dist[target], path


def fastest_route(
    source: str,
    target: str,
    with_incidents: bool = True,
) -> dict:
    """Return fastest route with and without active incidents for comparison."""
    incs = SAMPLE_INCIDENTS if with_incidents else []
    graph_normal   = build_road_graph(ROADS)
    graph_incident = build_road_graph(ROADS, incs)

    t_normal,   path_normal   = dijkstra(graph_normal,   source, target)
    t_incident, path_incident = dijkstra(graph_incident, source, target)

    return {
        "source": INTERSECTIONS[source].name,
        "target": INTERSECTIONS[target].name,
        "fastest_path": [INTERSECTIONS[n].name for n in path_incident],
        "fastest_time_min": round(t_incident, 1),
        "baseline_time_min": round(t_normal, 1),
        "incident_delay_min": round(max(0, t_incident - t_normal), 1),
    }


# ── Congestion Analysis ───────────────────────────────────────────────────────

def analyze_congestion(roads: list[Road]) -> dict:
    avg_cong = sum(r.congestion for r in roads) / len(roads)
    jammed   = [r for r in roads if r.congestion >= 0.75]
    moderate = [r for r in roads if 0.45 <= r.congestion < 0.75]

    recs: list[str] = []
    for r in jammed:
        if r.highway:
            recs.append(f"{r.name}: activate variable message signs — recommend alternate route.")
        else:
            recs.append(f"{r.name}: extend green phases on parallel corridors to absorb overflow.")

    return {
        "network_avg_congestion": round(avg_cong, 2),
        "jammed_roads":    [{"road": r.name, "congestion": f"{r.congestion*100:.0f}%", "status": r.congestion_label} for r in jammed],
        "moderate_roads":  [{"road": r.name, "congestion": f"{r.congestion*100:.0f}%"} for r in moderate],
        "recommendations": recs,
    }


# ── Adaptive Signal Timing ────────────────────────────────────────────────────

def optimize_signal(
    intersection_id: str,
    vehicle_counts: dict[str, int],   # {"N-S": count, "E-W": count}
    total_cycle_sec: int = 90,
) -> dict:
    """
    Allocate green time proportionally to vehicle counts.
    Reserves 4 s yellow per phase and enforces 10 s minimum green.
    """
    yellow_per_phase = 4
    n_phases = len(vehicle_counts)
    available = total_cycle_sec - yellow_per_phase * n_phases
    total_vehicles = sum(vehicle_counts.values()) or 1

    phases = {}
    for direction, count in vehicle_counts.items():
        raw = max(10, int(available * count / total_vehicles))
        phases[direction] = {"green_sec": raw, "yellow_sec": yellow_per_phase}

    # Normalise so phases sum exactly to total_cycle_sec
    total_assigned = sum(p["green_sec"] + p["yellow_sec"] for p in phases.values())
    overflow = total_assigned - total_cycle_sec
    if overflow != 0:
        first_dir = list(phases.keys())[0]
        phases[first_dir]["green_sec"] = max(10, phases[first_dir]["green_sec"] - overflow)

    return {
        "intersection": INTERSECTIONS[intersection_id].name,
        "total_cycle_sec": total_cycle_sec,
        "phases": phases,
        "green_wave_compatible": total_cycle_sec in (60, 90, 120),
    }


# ── Green Wave Calculator ─────────────────────────────────────────────────────

def green_wave_offsets(
    corridor: list[str],
    target_speed_kmh: float,
    cycle_sec: int = 90,
) -> list[dict]:
    """
    Calculate signal offset (seconds from cycle start) for each intersection
    along a corridor so a vehicle travelling at target_speed receives green at
    every light.
    """
    results = []
    elapsed_sec = 0.0
    for i, node_id in enumerate(corridor):
        if i > 0:
            prev = corridor[i - 1]
            # find road segment
            seg = next((r for r in ROADS if {r.from_id,r.to_id} == {prev, node_id}), None)
            if seg:
                travel_sec = (seg.length_km / target_speed_kmh) * 3600
                elapsed_sec += travel_sec
        offset = int(elapsed_sec % cycle_sec)
        results.append({
            "intersection": INTERSECTIONS[node_id].name if node_id in INTERSECTIONS else node_id,
            "offset_sec": offset,
        })
    return results


# ── Incident Detection ────────────────────────────────────────────────────────

def detect_incidents(roads: list[Road], threshold: float = 0.80) -> list[dict]:
    """
    Flag roads whose congestion exceeds the threshold as likely incidents.
    In a live system this compares expected vs actual speeds from probe vehicles.
    """
    alerts = []
    for road in roads:
        if road.congestion >= threshold:
            # Speed ratio: actual speed vs free-flow speed
            actual_speed = road.speed_limit_kmh * (1 - road.congestion * 0.85)
            ratio = actual_speed / road.speed_limit_kmh
            alerts.append({
                "road": road.name,
                "congestion": f"{road.congestion*100:.0f}%",
                "expected_speed_kmh": road.speed_limit_kmh,
                "estimated_speed_kmh": round(actual_speed, 1),
                "speed_ratio": round(ratio, 2),
                "likely_cause": "incident or blockage" if ratio < 0.20 else "heavy volume",
                "action": "Dispatch traffic unit + activate VMS diversion" if ratio < 0.20
                          else "Adjust signal timing on parallel corridors",
            })
    return alerts


# ── Main Demo ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  Boston Road Traffic Management System")
    print("  Highways: I-93 · I-90 (Mass Pike) · Route 1")
    print("=" * 65)

    # Congestion analysis
    print("\n[Congestion Analysis]")
    report = analyze_congestion(ROADS)
    print(f"  Network avg congestion : {report['network_avg_congestion']*100:.0f}%")
    print("  Jammed roads :")
    for r in report["jammed_roads"]:
        print(f"    ⚠  {r['road']} — {r['congestion']} ({r['status']})")
    print("  Recommendations :")
    for rec in report["recommendations"]:
        print(f"    → {rec}")

    # Incident detection
    print("\n[Incident Detection]")
    alerts = detect_incidents(ROADS)
    for a in alerts:
        print(f"  ⛔ {a['road']} | speed {a['estimated_speed_kmh']} km/h ({a['speed_ratio']*100:.0f}% of limit) | {a['likely_cause']}")
        print(f"     Action: {a['action']}")

    # Known active incidents
    print("\n[Active Incidents]")
    for inc in SAMPLE_INCIDENTS:
        road = next((r for r in ROADS if r.id == inc.road_id), None)
        print(f"  🚨 [{inc.type.upper()}] {road.name if road else inc.road_id} — {inc.description}")

    # Fastest route with vs without incidents
    print("\n[Optimal Routing — Sullivan Square → Copley Square]")
    route = fastest_route("sullivan", "copley", with_incidents=True)
    print(f"  Path     : {' → '.join(route['fastest_path'])}")
    print(f"  Time     : {route['fastest_time_min']} min  (baseline {route['baseline_time_min']} min)")
    print(f"  Incident delay: +{route['incident_delay_min']} min")

    # Adaptive signal timing
    print("\n[Adaptive Signal — Kenmore Square]")
    sig = optimize_signal("kenmore", {"N-S (Comm Ave)": 420, "E-W (Brookline Ave)": 180})
    for direction, phase in sig["phases"].items():
        print(f"  {direction}: green {phase['green_sec']}s + yellow {phase['yellow_sec']}s")
    print(f"  Green-wave compatible: {sig['green_wave_compatible']}")

    # Green wave on Storrow Dr corridor
    print("\n[Green Wave — Storrow Drive Corridor]")
    corridor = ["leverett", "longfellow", "harvard_bridge", "kenmore"]
    offsets = green_wave_offsets(corridor, target_speed_kmh=48, cycle_sec=90)
    for o in offsets:
        print(f"  {o['intersection']:35s} offset: {o['offset_sec']:3d} s")

    print("\n[Done]")


if __name__ == "__main__":
    main()
