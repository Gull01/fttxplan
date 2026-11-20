"""Capacity-constrained clustering and splitter placement."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.spatial import cKDTree
from sklearn.cluster import KMeans

from .network import RoadNetwork


def capacitated_clusters(xy: np.ndarray, capacity: int, seed: int = 0, n_iter: int = 20, k_near: int = 24) -> np.ndarray:
    """Group points into clusters of at most ``capacity`` members.

    Starts from k-means with ``k = ceil(n / capacity)`` and then repeats a capacity-respecting
    assignment: points with the most to lose (largest regret between their nearest and
    second-nearest centre) choose first. Returns a label per point, numbered from 0.
    """
    xy = np.asarray(xy, dtype=float)
    n = len(xy)
    if capacity < 1:
        raise ValueError("capacity must be at least 1")
    if n == 0:
        return np.zeros(0, dtype=int)
    k = math.ceil(n / capacity)
    if k == 1:
        return np.zeros(n, dtype=int)
    centers = KMeans(n_clusters=k, n_init=4, random_state=seed).fit(xy).cluster_centers_
    labels = np.full(n, -1)
    for _ in range(n_iter):
        m = min(k, k_near)
        dist, order = cKDTree(centers).query(xy, k=m)
        dist, order = dist.reshape(n, m), order.reshape(n, m)
        regret = (dist[:, 1] - dist[:, 0]) if m > 1 else np.zeros(n)
        left = np.full(k, capacity)
        new = np.full(n, -1)
        for i in np.argsort(-regret, kind="stable"):
            for c in order[i]:
                if left[c] > 0:
                    new[i] = c
                    left[c] -= 1
                    break
            else:  # all nearby centres are full: take the nearest centre with room
                free = np.flatnonzero(left > 0)
                c = free[np.argmin(np.hypot(*(centers[free] - xy[i]).T))]
                new[i] = c
                left[c] -= 1
        if np.array_equal(new, labels):
            break
        labels = new
        for c in range(k):
            members = labels == c
            if members.any():
                centers[c] = xy[members].mean(axis=0)
    # renumber compactly (drops clusters that ended up empty)
    _, labels = np.unique(labels, return_inverse=True)
    return labels


def network_clusters(net: RoadNetwork, nodes, capacity: int, seed: int = 0, n_iter: int = 5, radius: float = 3000.0) -> tuple[np.ndarray, list[int]]:
    """Capacity-constrained clustering by *road* distance (capacitated k-medoids).

    Straight-line clustering can put two homes in one group even when a river or a railway
    makes them kilometres apart by road. This starts from :func:`capacitated_clusters`, puts
    each splitter at the network medoid of its group, then alternates between reassigning
    items to splitters by road distance (respecting capacity) and moving each splitter to its
    group's new medoid. Returns ``(labels, splitter_nodes)``.
    """
    nodes = np.asarray(nodes, dtype=int)
    n = len(nodes)
    xy = np.array([net.xy(int(m)) for m in nodes])
    labels = capacitated_clusters(xy, capacity, seed=seed)
    k = int(labels.max()) + 1 if n else 0
    medoids = [network_medoid(net, nodes[labels == c], radius) for c in range(k)]
    if k <= 1:
        return labels, medoids
    for _ in range(n_iter):
        # road distances from every splitter to every item, ignoring anything beyond the radius
        uniq = np.unique(nodes)
        D = net.distance_matrix(medoids, uniq, limit=radius).T  # (unique items, splitters)
        m = min(k, 32)
        near = np.argpartition(D, m - 1, axis=1)[:, :m] if m < k else np.tile(np.arange(k), (len(uniq), 1))
        cand: dict[int, list[tuple[float, int]]] = {}
        for j, (u, row) in enumerate(zip(uniq, near)):
            cand[int(u)] = sorted((float(D[j, c]), int(c)) for c in row if np.isfinite(D[j, c]))
        regret = np.array([(cand[x][1][0] - cand[x][0][0]) if len(cand[x]) > 1 else (np.inf if cand[x] else -1.0) for x in nodes])
        left = np.full(k, capacity)
        new = np.full(n, -1)
        mxy = np.array([net.xy(int(m)) for m in medoids])
        for i in np.argsort(-regret, kind="stable"):
            for _, c in cand[int(nodes[i])]:
                if left[c] > 0:
                    new[i] = c
                    left[c] -= 1
                    break
            else:
                free = np.flatnonzero(left > 0)
                c = free[np.argmin(np.hypot(*(mxy[free] - xy[i]).T))]
                new[i] = c
                left[c] -= 1
        if np.array_equal(new, labels):
            break
        _, labels = np.unique(new, return_inverse=True)
        k = int(labels.max()) + 1
        medoids = [network_medoid(net, nodes[labels == c], radius) for c in range(k)]
    return labels, medoids


def network_medoid(net: RoadNetwork, members: Sequence[int], radius: float = 3000.0) -> int:
    """Return the member node with the smallest total road distance to all members.

    That is where a splitter serving those members should sit.
    """
    uniq = list(dict.fromkeys(int(m) for m in members))
    if len(uniq) == 1:
        return uniq[0]
    # roads rarely detour more than ~3x the straight distance, so bound each search by that
    pts = np.array([net.xy(m) for m in uniq])
    spread = float(np.max(np.hypot(*(pts - pts.mean(axis=0)).T))) * 2
    members = [int(m) for m in members]
    for limit in (min(radius, 3 * spread + 300), np.inf):
        cost = net.distance_matrix(uniq, members, limit=limit).sum(axis=1)
        if np.isfinite(cost.min()):
            return uniq[int(np.argmin(cost))]
    return uniq[0]
