"""Erlang C implementation checks against textbook values and identities."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from erlang import agents_required, erlang_c, service_level  # noqa: E402


def test_erlang_c_known_value():
    # A = 10 Erlangs, 13 agents: P(wait) ~= 0.2853 (standard Erlang C tables)
    assert abs(erlang_c(10, 13) - 0.2853) < 0.001
    # A = 2, n = 3: C = 4/9 ~= 0.4444 (closed form)
    assert abs(erlang_c(2, 3) - 4 / 9) < 1e-9


def test_unstable_queue_always_waits():
    assert erlang_c(5, 5) == 1.0 and erlang_c(6, 5) == 1.0
    assert service_level(6, 5, 300, 60) == 0.0


def test_agents_required_meets_target_minimally():
    calls, aht = np.array([5, 40, 120]), 300
    n = agents_required(calls, aht)
    a = calls * aht / 1800
    assert np.all(service_level(a, n, aht, 60) >= 0.8)
    assert np.all(service_level(a, n - 1, aht, 60) < 0.8)


def test_zero_calls_zero_agents():
    assert agents_required(np.array([0.0]), 300)[0] == 0
