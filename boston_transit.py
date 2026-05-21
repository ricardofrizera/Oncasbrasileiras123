"""
Boston Transit Improvement System
Analyzes MBTA data and suggests optimizations for routes, schedules, and capacity.
"""

import json
import math
import heapq
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional


# --- Data Models ---

@dataclass
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    routes: list[str] = field(default_factory=list)


@dataclass
class Route:
    id: str
    name: str
    line: str  # Red, Green, Orange, Blue, Silver, Bus
    stops: list[str] = field(default_factory=list)
    avg_delay_min: float = 0.0
    avg_crowding: float = 0.0  # 0.0–1.0


@dataclass
class TripRecord:
    route_id: str
    stop_id: str
    scheduled: datetime
    actual: datetime

    @property
    def delay_minutes(self) -> float:
        return (self.actual - self.scheduled).total_seconds() / 60


# --- Sample MBTA Data (subset for demonstration) ---

SAMPLE_STOPS: dict[str, Stop] = {
    "place-pktrm": Stop("place-pktrm", "Park Street",       42.3561, -71.0626, ["Red", "Green"]),
    "place-dwnxg": Stop("place-dwnxg", "Downtown Crossing", 42.3553, -71.0600, ["Red", "Orange"]),
    "place-knncl": Stop("place-knncl", "Kendall/MIT",       42.3625, -71.0861, ["Red"]),
    "place-harsq": Stop("place-harsq", "Harvard Square",    42.3736, -71.1190, ["Red"]),
    "place-bbsta": Stop("place-bbsta", "Back Bay",          42.3470, -71.0754, ["Orange", "CR"]),
    "place-north": Stop("place-north", "North Station",     42.3654, -71.0601, ["Green", "Orange", "CR"]),
    "place-south": Stop("place-south", "South Station",     42.3519, -71.0551, ["Red", "CR", "Silver"]),
    "place-boyls": Stop("place-boyls", "Boylston",          42.3515, -71.0665, ["Green"]),
    "place-armnl": Stop("place-armnl", "Arlington",         42.3511, -71.0702, ["Green"]),
    "place-coecl": Stop("place-coecl", "Copley",            42.3500, -71.0773, ["Green"]),
}

SAMPLE_ROUTES: list[Route] = [
    Route("Red",    "Red Line",    "Rail",   ["place-harsq","place-knncl","place-pktrm","place-dwnxg","place-south"], avg_delay_min=2.3, avg_crowding=0.78),
    Route("Green",  "Green Line",  "Rail",   ["place-north","place-boyls","place-armnl","place-coecl","place-pktrm"], avg_delay_min=4.1, avg_crowding=0.85),
    Route("Orange", "Orange Line", "Rail",   ["place-north","place-bbsta","place-dwnxg"],                             avg_delay_min=3.0, avg_crowding=0.70),
    Route("Silver", "Silver Line", "Bus",    ["place-south"],                                                         avg_delay_min=5.5, avg_crowding=0.60),
]


# --- Utility Functions ---

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# --- Graph Builder ---

def build_transit_graph(stops: dict[str, Stop], routes: list[Route]) -> dict[str, dict[str, float]]:
    """Build weighted adjacency graph.  Edge weight = travel-time proxy (km + delay penalty)."""
    graph: dict[str, dict[str, float]] = defaultdict(dict)

    for route in routes:
        delay_penalty = route.avg_delay_min / 10  # normalise to a distance-like cost
        for i in range(len(route.stops) - 1):
            a, b = route.stops[i], route.stops[i + 1]
            if a not in stops or b not in stops:
                continue
            dist = haversine_km(stops[a].lat, stops[a].lon, stops[b].lat, stops[b].lon)
            cost = dist + delay_penalty
            # keep the cheapest edge if multiple routes connect the same pair
            if b not in graph[a] or graph[a][b] > cost:
                graph[a][b] = cost
                graph[b][a] = cost

    return graph


# --- Shortest Path (Dijkstra) ---

def dijkstra(graph: dict[str, dict[str, float]], source: str, target: str) -> tuple[float, list[str]]:
    """Return (cost, path) from source to target."""
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


# --- Delay Analysis ---

def analyze_delays(routes: list[Route]) -> dict:
    """Identify routes with above-average delays and crowding."""
    avg_delay = sum(r.avg_delay_min for r in routes) / len(routes)
    avg_crowd = sum(r.avg_crowding for r in routes) / len(routes)

    report: dict = {
        "network_avg_delay_min": round(avg_delay, 2),
        "network_avg_crowding": round(avg_crowd, 2),
        "problematic_routes": [],
        "recommendations": [],
    }

    for route in routes:
        issues: list[str] = []
        if route.avg_delay_min > avg_delay * 1.2:
            issues.append(f"high delay ({route.avg_delay_min:.1f} min)")
        if route.avg_crowding > 0.80:
            issues.append(f"overcrowded ({route.avg_crowding * 100:.0f}%)")

        if issues:
            report["problematic_routes"].append({
                "route": route.name,
                "issues": issues,
            })

    # Generate actionable recommendations
    for entry in report["problematic_routes"]:
        name = entry["route"]
        for issue in entry["issues"]:
            if "delay" in issue:
                report["recommendations"].append(
                    f"{name}: increase service frequency and add signal priority at key intersections."
                )
            if "overcrowded" in issue:
                report["recommendations"].append(
                    f"{name}: deploy longer consists or add express service during peak hours."
                )

    return report


# --- Headway Optimiser ---

def optimise_headways(route: Route, daily_passengers: int, vehicle_capacity: int = 150) -> dict:
    """
    Suggest peak/off-peak headways to balance load.
    Peak = 07:00-09:00 and 16:00-19:00 (assumes 60 % of daily demand).
    """
    peak_passengers   = daily_passengers * 0.60
    offpeak_passengers = daily_passengers * 0.40

    peak_hours     = 4   # hours
    offpeak_hours  = 20  # hours

    def headway_minutes(passengers: float, hours: float) -> float:
        trips_needed = passengers / vehicle_capacity
        return max(2.0, (hours * 60) / trips_needed)

    peak_hw    = headway_minutes(peak_passengers, peak_hours)
    offpeak_hw = headway_minutes(offpeak_passengers, offpeak_hours)

    return {
        "route": route.name,
        "daily_passengers": daily_passengers,
        "vehicle_capacity": vehicle_capacity,
        "recommended_peak_headway_min":    round(peak_hw, 1),
        "recommended_offpeak_headway_min": round(offpeak_hw, 1),
        "current_avg_delay_min":           route.avg_delay_min,
    }


# --- Transfer Hub Scoring ---

def score_transfer_hubs(stops: dict[str, Stop]) -> list[dict]:
    """Rank stops by number of lines they serve — high-connectivity nodes are transfer hubs."""
    scored = [
        {"stop": s.name, "routes": s.routes, "connectivity_score": len(s.routes)}
        for s in stops.values()
    ]
    return sorted(scored, key=lambda x: x["connectivity_score"], reverse=True)


# --- Main Demo ---

def main() -> None:
    print("=" * 60)
    print("  Boston Transit Improvement System")
    print("=" * 60)

    # Build graph
    graph = build_transit_graph(SAMPLE_STOPS, SAMPLE_ROUTES)

    # Shortest path: Harvard → South Station
    cost, path = dijkstra(graph, "place-harsq", "place-south")
    stop_names = [SAMPLE_STOPS[s].name for s in path if s in SAMPLE_STOPS]
    print("\n[Optimal Route] Harvard Square → South Station")
    print(f"  Path  : {' → '.join(stop_names)}")
    print(f"  Cost  : {cost:.2f} (distance + delay index)")

    # Delay analysis
    print("\n[Delay & Crowding Analysis]")
    report = analyze_delays(SAMPLE_ROUTES)
    print(f"  Network avg delay  : {report['network_avg_delay_min']} min")
    print(f"  Network avg crowding: {report['network_avg_crowding'] * 100:.0f}%")
    print("  Problematic routes :")
    for entry in report["problematic_routes"]:
        print(f"    - {entry['route']}: {', '.join(entry['issues'])}")
    print("  Recommendations    :")
    for rec in report["recommendations"]:
        print(f"    * {rec}")

    # Headway optimisation for Green Line (busiest)
    print("\n[Headway Optimisation — Green Line]")
    green = next(r for r in SAMPLE_ROUTES if r.id == "Green")
    hw = optimise_headways(green, daily_passengers=280_000)
    print(f"  Peak headway   : every {hw['recommended_peak_headway_min']} min")
    print(f"  Off-peak headway: every {hw['recommended_offpeak_headway_min']} min")

    # Transfer hub ranking
    print("\n[Transfer Hub Ranking]")
    hubs = score_transfer_hubs(SAMPLE_STOPS)
    for hub in hubs[:5]:
        print(f"  {hub['stop']:25s} — lines: {', '.join(hub['routes'])}  (score: {hub['connectivity_score']})")

    print("\n[Done]")


if __name__ == "__main__":
    main()
