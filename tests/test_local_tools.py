"""Tests for the helper scripts, the parts that need no database and no network.

    pytest tests/test_local_tools.py -v

make_readonly_role.py   writes a connection string into .env, the file that holds every secret of the
                        project. Pinned down here: it only ever adds or replaces its own line.
seed_local.py           copies cloud data to this machine. Pinned down here: what counts as "this machine".
bench.py                turns request times into p50 / p95. Pinned down here: which request "p95" is.
"""

import string
import sys

import pytest

import bench
import make_readonly_role as role
import seed_local


# ----------------------------------------------------------------------------- make_readonly_role.py
def test_a_generated_password_is_long_mixed_and_safe_inside_a_url():
    allowed = set(string.ascii_letters + string.digits + "-_")
    passwords = {role.new_password() for _ in range(20)}
    assert len(passwords) == 20                                     # never the same one twice
    for pw in passwords:
        assert len(pw) == 32 and set(pw) <= allowed                 # nothing that would need escaping in a URL
        assert any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)


def test_the_api_connection_string_differs_from_the_owners_only_in_user_and_password():
    owner = "postgresql://owner:OWNERPASS@db.example.com/neondb?sslmode=require&channel_binding=require"
    api = role.url_for_role(owner, "aqi_api", "NEWPASS")
    assert api == "postgresql://aqi_api:NEWPASS@db.example.com/neondb?sslmode=require&channel_binding=require"
    assert "OWNERPASS" not in api and "owner" not in api
    assert role.url_for_role("postgresql://aqi:localdev@127.0.0.1:5433/aqi", "aqi_api", "p") == \
        "postgresql://aqi_api:p@127.0.0.1:5433/aqi"                 # a port is kept too


def test_saving_to_env_replaces_only_its_own_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keys\nOPENAQ_KEY=abc\n\nDATABASE_URL=postgresql://owner\n"
                   "API_DATABASE_URL=old\nAPI_DATABASE_URL_NOTE=keep me\n")
    role.save_to_env("API_DATABASE_URL", "new", path=env)
    assert env.read_text().splitlines() == ["# keys", "OPENAQ_KEY=abc", "", "DATABASE_URL=postgresql://owner",
                                            "API_DATABASE_URL_NOTE=keep me", "API_DATABASE_URL=new"]
    role.save_to_env("API_DATABASE_URL", "newer", path=env)         # again: still exactly one line for the key
    assert env.read_text().count("API_DATABASE_URL=") == 1 and env.read_text().endswith("API_DATABASE_URL=newer\n")
    assert [p.name for p in tmp_path.iterdir()] == [".env"]         # no half-written temporary file left behind


def test_saving_to_env_creates_the_file_if_there_is_none(tmp_path):
    env = tmp_path / ".env"
    role.save_to_env("API_DATABASE_URL", "x", path=env)
    assert env.read_text() == "API_DATABASE_URL=x\n"


# ----------------------------------------------------------------------------- seed_local.py
def test_the_copy_only_accepts_a_target_on_this_machine():
    assert seed_local.is_local("postgresql://aqi:localdev@127.0.0.1:5433/aqi")
    assert seed_local.is_local("postgresql://aqi:localdev@localhost/aqi")
    assert not seed_local.is_local("postgresql://user:pass@db.example.com/neondb")
    assert seed_local.is_local(seed_local.LOCAL_TARGET)             # the default target passes its own rule


def test_the_copy_script_stops_before_connecting_if_the_direction_looks_wrong(monkeypatch):
    """Cloud -> this machine is the only direction. Both checks happen before any connection is opened."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com/neondb")
    monkeypatch.setattr(sys, "argv", ["seed_local.py", "--target", "postgresql://user:pass@other.example.com/x"])
    with pytest.raises(SystemExit, match="refusing"):               # the target is not this machine
        seed_local.main()

    monkeypatch.setenv("DATABASE_URL", seed_local.LOCAL_TARGET)
    monkeypatch.setattr(sys, "argv", ["seed_local.py"])
    with pytest.raises(SystemExit, match="expected the cloud database"):   # the source is this machine
        seed_local.main()


# ----------------------------------------------------------------------------- bench.py
def test_p95_is_the_request_that_95_percent_are_at_or_below():
    """Nearest rank, rounded up. With 30 requests that is the 29th: 28 of 30 would only be 93%."""
    assert bench.percentile(range(1, 21), 0.95) == 19               # 19 of 20 = 95%
    assert bench.percentile(range(1, 31), 0.95) == 29               # round(28.5) is 28 in Python: the old bug
    assert bench.percentile(range(1, 101), 0.95) == 95
    assert bench.percentile(range(1, 101), 0.07) == 7               # 0.07 * 100 is 7.000000000000001: still 7
    assert bench.percentile([30, 10, 20], 0.5) == 20                # order of arrival does not matter
    assert bench.percentile([7], 0.95) == 7
    assert bench.percentile(range(1, 31), 0.0) == 1 and bench.percentile(range(1, 31), 1.0) == 30


def test_a_summary_reports_the_first_request_apart_and_skips_failed_ones(monkeypatch):
    answers = iter([(900.0, 200, 600.0)]                                      # the first request: slow, asked the database
                   + [(float(ms), 200, 1.0) for ms in range(100, 119)]        # 19 normal ones: 100 ... 118 ms
                   + [(5000.0, 503, None)])                                   # and one that failed
    monkeypatch.setattr(bench, "timed_get", lambda url: next(answers))
    r = bench.measure("http://example.test", "/health", n=20)
    assert (r["first_ms"], r["first_server_ms"]) == (900, 600.0)
    assert (r["ok"], r["n"]) == (19, 20)                                      # the failure is counted ...
    assert (r["p50_ms"], r["p95_ms"], r["max_ms"]) == (109, 118, 118)         # ... but not averaged in
    assert r["server_p50_ms"] == 1.0


def test_server_time_is_read_from_the_header():
    assert bench.server_ms({"Server-Timing": "app;dur=3.2"}) == 3.2
    assert bench.server_ms({"Server-Timing": "app;dur=12.5, db;dur=4"}) == 12.5   # the first entry
    assert bench.server_ms({"Server-Timing": "app;dur=fast"}) is None             # not a number
    assert bench.server_ms({"Server-Timing": "miss"}) is None
    assert bench.server_ms({}) is None and bench.server_ms(None) is None          # a request that never answered
