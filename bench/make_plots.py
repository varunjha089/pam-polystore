"""Day 4: bar charts of benchmark medians + storage comparison."""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CSV  = os.path.expanduser("~/claude_db_project/bench/results_fair.csv")
OUT_DIR = os.path.expanduser("~/claude_db_project/bench")

# --- load ---
rows = list(csv.DictReader(open(CSV)))
queries = []
seen = set()
for r in rows:
    if r["query_id"] not in seen:
        queries.append((r["query_id"], r["query_label"]))
        seen.add(r["query_id"])

def med(qid, arch):
    for r in rows:
        if r["query_id"] == qid and r["arch"] == arch:
            return float(r["median_ms"])
    return 0.0

qids   = [q[0] for q in queries]
labels = [q[1] for q in queries]
pg     = [med(q, "pure_pg") for q in qids]
v2     = [med(q, "v2")      for q in qids]

# --- plot 1: latency bar chart ---
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(qids)); w = 0.38
b1 = ax.bar(x - w/2, pg, w, label="pure-PG (grid_flat)", color="#5b8def")
b2 = ax.bar(x + w/2, v2, w, label="v2 polystore (TileDB+IMS)", color="#22a06b")
ax.set_xticks(x)
ax.set_xticklabels([f"{q.replace('_',' ')}\n{lab}" for q,lab in zip(qids,labels)],
                   fontsize=8, rotation=0, ha="center")
ax.set_ylabel("Median time (ms, lower is better)")
ax.set_title("PAM Day 4 — query latency (10 warm runs each, in-process)")
ax.legend(loc="upper left")
ax.grid(axis="y", linestyle="--", alpha=0.4)

# annotate values
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 1, f"{h:.0f}",
                ha="center", va="bottom", fontsize=8)

# annotate speedup
for i,(p,vv) in enumerate(zip(pg, v2)):
    if p > 0 and vv > 0:
        ratio = p / vv
        tag = f"{ratio:.2f}×" + (" v2" if ratio > 1 else " PG")
        y = max(p, vv) + 6
        ax.text(i, y, tag, ha="center", fontsize=8,
                color=("#22a06b" if ratio > 1 else "#5b8def"),
                fontweight="bold")

plt.tight_layout()
out1 = os.path.join(OUT_DIR, "latency_chart.png")
plt.savefig(out1, dpi=150, bbox_inches="tight")
print(f"[OK] {out1}")
plt.close()

# --- plot 2: storage comparison ---
fig, ax = plt.subplots(figsize=(6, 4))
storage = [314.0, 11.0]
labels2 = ["pure-PG\n(grid_flat)", "v2 polystore\n(TileDB)"]
colors2 = ["#5b8def", "#22a06b"]
bars = ax.bar(labels2, storage, color=colors2, width=0.55)
ax.set_ylabel("Disk usage (MB, lower is better)")
ax.set_title("PAM Day 4 — on-disk storage for COCL × 16 months")
ax.grid(axis="y", linestyle="--", alpha=0.4)
for bar, val in zip(bars, storage):
    ax.text(bar.get_x() + bar.get_width()/2, val + 5, f"{val:.0f} MB",
            ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.text(0.5, 250, "28× smaller", ha="center", fontsize=11,
        color="#22a06b", fontweight="bold",
        transform=ax.transData)
ax.annotate("", xy=(1, 30), xytext=(0, 280),
            arrowprops=dict(arrowstyle="->", color="#22a06b", lw=1.5))
plt.tight_layout()
out2 = os.path.join(OUT_DIR, "storage_chart.png")
plt.savefig(out2, dpi=150, bbox_inches="tight")
print(f"[OK] {out2}")
plt.close()

print("Done.")
