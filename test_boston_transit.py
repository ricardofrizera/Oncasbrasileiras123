"""Unit tests for boston_transit.py"""

import math
import pytest
from boston_transit import (
    Stop, Route,
    haversine_km,
    build_transit_graph,
    dijkstra,
    analyze_delays,
    optimise_headways,
    score_transfer_hubs,
    SAMPLE_STOPS,
    SAMPLE_ROUTES,
)


# --- haversine_km ---

def test_haversine_same_point():
    assert haversine_km(42.35, -71.06, 42.35, -71.06) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_distance():
    # Park Street → Downtown Crossing ~0.23 km straight-line
    dist = haversine_km(42.3561, -71.0626, 42.3553, -71.0600)
    assert 0.1 < dist < 0.5


# --- build_transit_graph ---

def test_graph_has_edges():
    graph = build_transit_graph(SAMPLE_STOPS, SAMPLE_ROUTES)
    assert len(graph) > 0


def test_graph_is_symmetric():
    graph = build_transit_graph(SAMPLE_STOPS, SAMPLE_ROUTES)
    for u in graph:
        for v, w in graph[u].items():
            assert graph[v][u] == pytest.approx(w, rel=1e-6)


# --- dijkstra ---

def test_dijkstra_same_node():
    graph = build_transit_graph(SAMPLE_STOPS, SAMPLE_ROUTES)
    cost, path = dijkstra(graph, "place-pktrm", "place-pktrm")
    assert cost == pytest.approx(0.0)
    assert path == ["place-pktrm"]


def test_dijkstra_reachable():
    graph = build_transit_graph(SAMPLE_STOPS, SAMPLE_ROUTES)
    cost, path = dijkstra(graph, "place-harsq", "place-south")
    assert cost < math.inf
    assert path[0] == "place-harsq"
    assert path[-1] == "place-south"


def test_dijkstra_unreachable():
    graph: dict = {"A": {"B": 1.0}, "B": {"A": 1.0}}
    cost, path = dijkstra(graph, "A", "Z")
    assert cost == math.inf
    assert path == []


# --- analyze_delays ---

def test_analyze_delays_structure():
    report = analyze_delays(SAMPLE_ROUTES)
    assert "network_avg_delay_min" in report
    assert "recommendations" in report
    assert isinstance(report["problematic_routes"], list)


def test_analyze_delays_identifies_green():
    report = analyze_delays(SAMPLE_ROUTES)
    names = [e["route"] for e in report["problematic_routes"]]
    # Green Line has highest delay (4.1 min) — must appear
    assert "Green Line" in names


# --- optimise_headways ---

def test_optimise_headways_peak_lt_offpeak():
    route = Route("T", "Test Line", "Rail", avg_delay_min=2.0, avg_crowding=0.5)
    result = optimise_headways(route, daily_passengers=100_000)
    # Peak demand is higher → headway should be shorter (smaller number)
    assert result["recommended_peak_headway_min"] <= result["recommended_offpeak_headway_min"]


def test_optimise_headways_minimum_headway():
    route = Route("T", "Test Line", "Rail", avg_delay_min=0.0, avg_crowding=0.0)
    result = optimise_headways(route, daily_passengers=1, vehicle_capacity=1000)
    assert result["recommended_peak_headway_min"] >= 2.0


# --- score_transfer_hubs ---

def test_score_transfer_hubs_sorted():
    hubs = score_transfer_hubs(SAMPLE_STOPS)
    scores = [h["connectivity_score"] for h in hubs]
    assert scores == sorted(scores, reverse=True)


def test_score_transfer_hubs_park_street():
    hubs = score_transfer_hubs(SAMPLE_STOPS)
    top_names = [h["stop"] for h in hubs[:3]]
    assert "Park Street" in top_names
