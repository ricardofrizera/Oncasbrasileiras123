"""Unit tests for boston_traffic.py"""

import math
import pytest
from boston_traffic import (
    Road, Incident,
    build_road_graph,
    dijkstra,
    analyze_congestion,
    optimize_signal,
    green_wave_offsets,
    detect_incidents,
    fastest_route,
    ROADS, INTERSECTIONS, SAMPLE_INCIDENTS,
)


# ── Road model ────────────────────────────────────────────────────────────────

def test_free_flow_time():
    r = Road("t", "Test", "a", "b", length_km=10, speed_limit_kmh=60, congestion=0)
    assert r.free_flow_time_min == pytest.approx(10.0, rel=1e-6)


def test_actual_time_exceeds_free_flow_under_congestion():
    r = Road("t", "Test", "a", "b", length_km=10, speed_limit_kmh=60, congestion=0.9)
    assert r.actual_time_min > r.free_flow_time_min


def test_congestion_label_standstill():
    r = Road("t", "Test", "a", "b", 1, 60, congestion=0.9)
    assert r.congestion_label == "Standstill"


def test_congestion_label_free():
    r = Road("t", "Test", "a", "b", 1, 60, congestion=0.2)
    assert r.congestion_label == "Free"


# ── Graph builder ─────────────────────────────────────────────────────────────

def test_graph_non_empty():
    g = build_road_graph(ROADS)
    assert len(g) > 0


def test_graph_symmetric():
    g = build_road_graph(ROADS)
    for u in g:
        for v, w in g[u].items():
            assert g[v][u] == pytest.approx(w, rel=1e-5)


def test_incident_increases_edge_weight():
    inc = Incident("i93_leverett_sb", "accident", 0.5, "test")
    g_base = build_road_graph(ROADS)
    g_inc  = build_road_graph(ROADS, [inc])
    assert g_inc["leverett"]["south_bay"] > g_base["leverett"]["south_bay"]


# ── Dijkstra ──────────────────────────────────────────────────────────────────

def test_dijkstra_same_node():
    g = build_road_graph(ROADS)
    cost, path = dijkstra(g, "zakim", "zakim")
    assert cost == pytest.approx(0.0)
    assert path == ["zakim"]


def test_dijkstra_reachable():
    g = build_road_graph(ROADS)
    cost, path = dijkstra(g, "sullivan", "copley")
    assert cost < math.inf
    assert path[0] == "sullivan"
    assert path[-1] == "copley"


def test_dijkstra_unreachable():
    g = {"A": {"B": 1.0}, "B": {"A": 1.0}}
    cost, path = dijkstra(g, "A", "Z")
    assert cost == math.inf
    assert path == []


def test_incident_path_avoidance():
    # With a near-blocking incident on the direct I-93 S segment, time must increase
    incs = [Incident("i93_leverett_sb", "accident", 0.99, "near block")]
    g_inc  = build_road_graph(ROADS, incs)
    g_base = build_road_graph(ROADS)
    t_inc, _  = dijkstra(g_inc,  "leverett", "south_bay")
    t_base, _ = dijkstra(g_base, "leverett", "south_bay")
    assert t_inc >= t_base


# ── Congestion analysis ───────────────────────────────────────────────────────

def test_analyze_congestion_structure():
    report = analyze_congestion(ROADS)
    for key in ("network_avg_congestion", "jammed_roads", "moderate_roads", "recommendations"):
        assert key in report


def test_jammed_roads_threshold():
    report = analyze_congestion(ROADS)
    for entry in report["jammed_roads"]:
        pct = float(entry["congestion"].strip("%"))
        assert pct >= 75


# ── Adaptive signal ───────────────────────────────────────────────────────────

def test_signal_cycle_total():
    result = optimize_signal("kenmore", {"N-S": 300, "E-W": 100}, total_cycle_sec=90)
    total = sum(p["green_sec"] + p["yellow_sec"] for p in result["phases"].values())
    assert total == 90


def test_signal_minimum_green():
    result = optimize_signal("kenmore", {"N-S": 999, "E-W": 1}, total_cycle_sec=90)
    for p in result["phases"].values():
        assert p["green_sec"] >= 10


# ── Green wave ────────────────────────────────────────────────────────────────

def test_green_wave_length():
    corridor = ["leverett", "longfellow", "harvard_bridge", "kenmore"]
    offsets = green_wave_offsets(corridor, target_speed_kmh=48, cycle_sec=90)
    assert len(offsets) == len(corridor)


def test_green_wave_first_offset_zero():
    corridor = ["leverett", "longfellow"]
    offsets = green_wave_offsets(corridor, target_speed_kmh=48, cycle_sec=90)
    assert offsets[0]["offset_sec"] == 0


def test_green_wave_offsets_within_cycle():
    corridor = ["leverett", "longfellow", "harvard_bridge", "kenmore"]
    offsets = green_wave_offsets(corridor, 48, 90)
    for o in offsets:
        assert 0 <= o["offset_sec"] < 90


# ── Incident detection ────────────────────────────────────────────────────────

def test_detect_incidents_returns_jammed():
    alerts = detect_incidents(ROADS, threshold=0.80)
    assert all(float(a["congestion"].strip("%")) >= 80 for a in alerts)


def test_detect_incidents_empty_on_high_threshold():
    alerts = detect_incidents(ROADS, threshold=1.0)
    assert alerts == []


# ── fastest_route ─────────────────────────────────────────────────────────────

def test_fastest_route_structure():
    r = fastest_route("sullivan", "copley")
    for key in ("fastest_path", "fastest_time_min", "baseline_time_min", "incident_delay_min"):
        assert key in r


def test_fastest_route_incident_delay_nonneg():
    r = fastest_route("sullivan", "copley", with_incidents=True)
    assert r["incident_delay_min"] >= 0
