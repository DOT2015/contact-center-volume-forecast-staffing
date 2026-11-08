"""Erlang C, implemented from the Erlang B recursion (numerically stable, vectorized).

For an M/M/c queue with offered load A = arrival_rate x AHT (Erlangs) and n agents:
  Erlang B: B(0) = 1, B(k) = A B(k-1) / (k + A B(k-1))
  Erlang C: P(wait > 0) = n B(n) / (n - A (1 - B(n)))          for n > A
  Service level: P(wait <= T) = 1 - C exp(-(n - A) T / AHT)
"""
from __future__ import annotations

import numpy as np


def erlang_c(traffic, agents):
    """Probability an arriving call waits. traffic (Erlangs) and agents are broadcastable arrays."""
    a = np.asarray(traffic, dtype=float)
    n = np.asarray(agents, dtype=int)
    a, n = np.broadcast_arrays(a, n)
    b = np.ones(a.shape)
    out = np.ones(a.shape)
    nmax = int(n.max()) if n.size else 0
    for k in range(1, nmax + 1):
        b = a * b / (k + a * b)
        hit = n == k
        if hit.any():
            denom = k - a[hit] * (1 - b[hit])
            out[hit] = np.where(k > a[hit], k * b[hit] / np.where(denom > 0, denom, 1), 1.0)
    out[n <= a] = 1.0
    out[a <= 0] = 0.0
    return np.clip(out, 0, 1)


def service_level(traffic, agents, aht_sec, target_sec):
    a = np.asarray(traffic, dtype=float)
    n = np.asarray(agents, dtype=float)
    c = erlang_c(a, n)
    sl = 1 - c * np.exp(-(n - a) * target_sec / np.asarray(aht_sec, dtype=float))
    return np.where(n > a, sl, 0.0)


def agents_required(calls, aht_sec, interval_sec=1800, sl_target=0.80, target_sec=60, max_agents=200):
    """Minimum agents per interval to reach the service-level target. calls = expected calls in interval."""
    calls = np.asarray(calls, dtype=float)
    aht = np.broadcast_to(np.asarray(aht_sec, dtype=float), calls.shape)
    a = calls * aht / interval_sec
    need = np.where(calls > 0, np.maximum(np.floor(a) + 1, 1), 0).astype(int)
    for _ in range(max_agents):
        sl = service_level(a, need, aht, target_sec)
        short = (calls > 0) & (sl < sl_target)
        if not short.any():
            break
        need = need + short
    return need
