from __future__ import annotations

import sqlite3

import pytest

from pinger import hosts


def test_positions_auto_increment(conn):
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    pages = hosts.list_pages(conn)
    assert [p["id"] for p in pages] == [p1, p2]
    assert [p["position"] for p in pages] == [0, 1]

    t1 = hosts.create_target(conn, p1, "t1")
    t2 = hosts.create_target(conn, p1, "t2")
    assert [t["id"] for t in hosts.list_targets(conn, p1)] == [t1, t2]
    assert [t["position"] for t in hosts.list_targets(conn, p1)] == [0, 1]


def test_list_pages_only_enabled(conn):
    p1 = hosts.create_page(conn, "on", enabled=True)
    hosts.create_page(conn, "off", enabled=False)
    enabled = hosts.list_pages(conn, only_enabled=True)
    assert [p["id"] for p in enabled] == [p1]


def test_enabled_probe_targets_filters_disabled(conn):
    p_on = hosts.create_page(conn, "on", enabled=True)
    p_off = hosts.create_page(conn, "off", enabled=False)
    t_on = hosts.create_target(conn, p_on)
    t_off = hosts.create_target(conn, p_off)

    a_on = hosts.create_address(conn, p_on, t_on, "10.0.0.1", enabled=True)
    hosts.create_address(conn, p_on, t_on, "10.0.0.2", enabled=False)
    hosts.create_address(conn, p_off, t_off, "10.0.0.3", enabled=True)

    targets = hosts.enabled_probe_targets(conn)
    assert [(t["address_id"], t["address"]) for t in targets] == [
        (a_on, "10.0.0.1")
    ]


def test_unique_address_per_page_but_not_across_pages(conn):
    p1 = hosts.create_page(conn, "p1")
    p2 = hosts.create_page(conn, "p2")
    t1 = hosts.create_target(conn, p1)
    t2 = hosts.create_target(conn, p2)
    hosts.create_address(conn, p1, t1, "10.0.0.1")
    with pytest.raises(sqlite3.IntegrityError):
        hosts.create_address(conn, p1, t1, "10.0.0.1")
    # на другой странице тот же IP допустим
    hosts.create_address(conn, p2, t2, "10.0.0.1")


def test_find_address_in_page(conn):
    p1 = hosts.create_page(conn, "p1")
    t1 = hosts.create_target(conn, p1, "row")
    hosts.create_address(conn, p1, t1, "10.0.0.5")
    found = hosts.find_address_in_page(conn, p1, "10.0.0.5")
    assert found is not None
    assert hosts.find_address_in_page(conn, p1, "10.0.0.6") is None


def test_update_and_delete_page(conn):
    p1 = hosts.create_page(conn, "p1")
    hosts.update_page(conn, p1, name="renamed", enabled=False, position=7)
    page = hosts.get_page(conn, p1)
    assert page["name"] == "renamed"
    assert page["enabled"] == 0
    assert page["position"] == 7
    hosts.delete_page(conn, p1)
    assert hosts.get_page(conn, p1) is None


def test_update_address(conn):
    p1 = hosts.create_page(conn, "p1")
    t1 = hosts.create_target(conn, p1)
    a1 = hosts.create_address(conn, p1, t1, "10.0.0.1")
    hosts.update_address(conn, a1, address="10.0.0.9", enabled=False)
    row = hosts.get_address(conn, a1)
    assert row["address"] == "10.0.0.9"
    assert row["enabled"] == 0