"""Draw flowcharts as PNG images with a simple layered layout (no Graphviz needed)."""
from __future__ import annotations

import io
import textwrap
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

COLORS = {
    "start": ("#1F3B5A", "white"),
    "end": ("#1F3B5A", "white"),
    "process": ("#E8EFF7", "#111111"),
    "decision": ("#FCEFD9", "#111111"),
}


def _levels(nodes, edges):
    ids = [n["id"] for n in nodes]
    children = defaultdict(list)
    indeg = {i: 0 for i in ids}
    for e in edges:
        if e["from"] in indeg and e["to"] in indeg:
            children[e["from"]].append(e["to"])
    # remove back edges with a DFS so cycles do not break the layout
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for v in children[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2
    for i in ids:
        if i not in state:
            dfs(i)
    fwd = [(e["from"], e["to"]) for e in edges if e["from"] in indeg and e["to"] in indeg and (e["from"], e["to"]) not in back]
    for _, v in fwd:
        indeg[v] += 1
    level = {i: 0 for i in ids}
    order = [i for i in ids if indeg[i] == 0]
    q = list(order)
    deg = dict(indeg)
    while q:
        u = q.pop(0)
        for a, b in fwd:
            if a == u:
                level[b] = max(level[b], level[u] + 1)
                deg[b] -= 1
                if deg[b] == 0:
                    q.append(b)
    return level, back


def render_flowchart(spec: dict) -> bytes:
    nodes = spec.get("nodes") or []
    edges = [e for e in (spec.get("edges") or []) if e.get("from") and e.get("to")]
    if not nodes:
        raise ValueError("Flowchart has no nodes")
    level, back = _levels(nodes, edges)
    by_level = defaultdict(list)
    for n in nodes:
        by_level[level[n["id"]]].append(n["id"])
    depth = max(by_level) + 1
    widest = max(len(v) for v in by_level.values())
    lr = widest > 4 and depth <= 5

    # order nodes in each level by their parents' positions (one barycentre pass)
    pos_index = {}
    for lv in range(depth):
        ids = by_level[lv]
        if lv > 0:
            def bary(i):
                ps = [pos_index[e["from"]] for e in edges if e["to"] == i and e["from"] in pos_index]
                return sum(ps) / len(ps) if ps else 0
            ids.sort(key=bary)
        for k, i in enumerate(ids):
            pos_index[i] = k - (len(ids) - 1) / 2

    wrap = 26 if lr else 22
    text = {n["id"]: textwrap.fill(str(n.get("text", "")), wrap) for n in nodes}
    kind = {n["id"]: (n.get("kind") or "process").lower() for n in nodes}
    lines = {i: t.count("\n") + 1 for i, t in text.items()}
    box_w = 3.0 if lr else 2.7
    line_h = 0.24
    box_h = {i: 0.35 + line_h * lines[i] for i in text}
    max_h = max(box_h.values())

    xy = {}
    if lr:
        gap_x, gap_y = box_w + 1.1, max_h + 0.45
        for lv in range(depth):
            for i in by_level[lv]:
                xy[i] = (lv * gap_x, -pos_index[i] * gap_y)
        fw, fh = max(6.0, depth * gap_x * 0.95), max(3.0, widest * gap_y * 0.95)
    else:
        gap_x, gap_y = box_w + 0.5, max_h + 0.75
        for lv in range(depth):
            for i in by_level[lv]:
                xy[i] = (pos_index[i] * gap_x, -lv * gap_y)
        fw, fh = max(5.0, widest * gap_x * 0.95), max(3.0, depth * gap_y * 0.9)

    fig, ax = plt.subplots(figsize=(min(fw, 11), min(fh, 14)), dpi=200)
    ax.set_aspect("equal")
    ax.axis("off")

    for e in edges:
        a, b = e["from"], e["to"]
        if a not in xy or b not in xy:
            continue
        (x1, y1), (x2, y2) = xy[a], xy[b]
        if lr:
            p1, p2 = (x1 + box_w / 2, y1), (x2 - box_w / 2, y2)
        else:
            p1, p2 = (x1, y1 - box_h[a] / 2), (x2, y2 + box_h[b] / 2)
        style = "arc3,rad=0.35" if (a, b) in back or (not lr and y2 >= y1) or (lr and x2 <= x1) else "arc3,rad=0"
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=12, lw=1.1,
                                     color="#3A4A5C", connectionstyle=style, shrinkA=2, shrinkB=2))
        if e.get("label"):
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            ax.text(mx, my, e["label"], fontsize=8, ha="center", va="center", style="italic",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

    for i, (x, y) in xy.items():
        fc, tc = COLORS.get(kind[i], COLORS["process"])
        h = box_h[i]
        rs = 0.45 if kind[i] in ("start", "end") else 0.12
        ax.add_patch(FancyBboxPatch((x - box_w / 2, y - h / 2), box_w, h,
                                    boxstyle=f"round,pad=0.02,rounding_size={rs}",
                                    fc=fc, ec="#1F3B5A", lw=1.2 if kind[i] != "decision" else 1.6))
        ax.text(x, y, text[i], ha="center", va="center", fontsize=8.6, color=tc,
                fontweight="bold" if kind[i] in ("start", "end", "decision") else "normal",
                family="DejaVu Serif")

    xs = [p[0] for p in xy.values()]
    ys = [p[1] for p in xy.values()]
    ax.set_xlim(min(xs) - box_w / 2 - 0.4, max(xs) + box_w / 2 + 0.4)
    ax.set_ylim(min(ys) - max_h / 2 - 0.4, max(ys) + max_h / 2 + 0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
