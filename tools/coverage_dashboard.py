#!/usr/bin/env python3
"""Generate a tiny coverage-over-time dashboard from pipeline metrics.

This script can read per-run JSON metrics stored in the `pipeline-metrics`
branch under `metrics/<run_id>.json` (the workflow created these), or it can
read a local directory of metric JSON files (convenient for testing).

Usage:
  # Use remote branch (default)
  python tools/coverage_dashboard.py --repo-root . --out coverage_trend.png

  # Or point at a local metrics directory
  python tools/coverage_dashboard.py --local-metrics-dir pipeline-metrics/metrics --out coverage_trend.png

The script requires `matplotlib` (already present in `requirements.txt`).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib.pyplot as plt


def run(cmd: List[str], cwd: Optional[str] = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def fetch_metrics_via_git(repo_root: str, branch: str = "pipeline-metrics") -> List[Dict]:
    """Try to fetch the remote `pipeline-metrics` branch and read JSON metrics files.

    Returns a list of parsed JSON objects.
    """
    cwd = os.path.abspath(repo_root)
    # Ensure we have the branch locally (create or fetch)
    try:
        # Try to fetch and create local branch from origin
        run(["git", "fetch", "origin", f"{branch}:{branch}"], cwd=cwd)
        tree_ref = branch
    except Exception:
        # Fall back to referencing the remote branch
        try:
            run(["git", "fetch", "origin", branch], cwd=cwd)
            tree_ref = f"origin/{branch}"
        except Exception:
            raise RuntimeError(f"Unable to fetch branch '{branch}' from origin")

    # List files in the branch
    try:
        files = run(["git", "ls-tree", "-r", "--name-only", tree_ref], cwd=cwd).splitlines()
    except Exception as e:
        raise RuntimeError(f"Failed to list files for {tree_ref}: {e}")

    metrics_files = [f for f in files if f.startswith("metrics/") and f.endswith('.json')]
    results = []
    for mf in metrics_files:
        try:
            content = run(["git", "show", f"{tree_ref}:{mf}"], cwd=cwd)
            results.append(json.loads(content))
        except Exception:
            # Skip unreadable files
            continue
    return results


def read_local_metrics_dir(path: str) -> List[Dict]:
    items = []
    for fn in sorted(os.listdir(path)):
        if not fn.endswith('.json'):
            continue
        p = os.path.join(path, fn)
        try:
            with open(p, 'r') as f:
                items.append(json.load(f))
        except Exception:
            continue
    return items


def parse_metrics(items: List[Dict]) -> List[Dict]:
    rows = []
    for it in items:
        cov = it.get('coverage_percent')
        ts = it.get('timestamp') or it.get('time') or it.get('date')
        run_id = it.get('run_id') or it.get('id') or it.get('commit')
        if cov is None:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00')) if ts else None
        except Exception:
            dt = None
        rows.append({'run_id': run_id, 'ts': dt, 'coverage': float(cov)})
    # Sort by timestamp when available, else by run_id
    rows.sort(key=lambda r: (r['ts'] or datetime.min, r['run_id']))
    return rows


def plot_coverage(rows: List[Dict], out: str) -> None:
    if not rows:
        print("No metrics to plot", file=sys.stderr)
        return
    xs = [r['ts'] if r['ts'] is not None else datetime.utcnow() for r in rows]
    ys = [r['coverage'] for r in rows]
    plt.figure(figsize=(8, 3.5))
    plt.plot(xs, ys, marker='o')
    plt.ylim(0, 100)
    plt.grid(axis='y', alpha=0.3)
    plt.title('Test Coverage Over Time')
    plt.xlabel('Run')
    plt.ylabel('Coverage (%)')
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    print(f"Wrote coverage trend to {out}")


def main() -> int:
    p = argparse.ArgumentParser(description="Generate coverage trend from pipeline metrics")
    p.add_argument('--repo-root', default='.', help='Path to repo root')
    p.add_argument('--branch', default='pipeline-metrics', help='Metrics branch name')
    p.add_argument('--local-metrics-dir', default=None, help='Use a local metrics directory instead of git branch')
    p.add_argument('--out', default='coverage_trend.png', help='Output PNG path')
    args = p.parse_args()

    if args.local_metrics_dir:
        if not os.path.isdir(args.local_metrics_dir):
            print(f"Local metrics dir not found: {args.local_metrics_dir}", file=sys.stderr)
            return 2
        items = read_local_metrics_dir(args.local_metrics_dir)
    else:
        try:
            items = fetch_metrics_via_git(args.repo_root, branch=args.branch)
        except Exception as e:
            print(f"Failed to fetch metrics via git: {e}", file=sys.stderr)
            return 3

    rows = parse_metrics(items)
    plot_coverage(rows, args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
