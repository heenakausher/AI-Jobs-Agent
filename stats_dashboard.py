#!/usr/bin/env python3
"""Statistics dashboard for AI Jobs Agent.

Generates:
  - Console summary of last 30 days
  - stats_report.html with Plotly charts

Usage:
  python3 stats_dashboard.py
"""

import json
import os
import sys
from collections import defaultdict

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("Plotly not installed. Run: pip install plotly")
    sys.exit(1)

STATS_FILE = "agent_stats.json"


def load_stats():
    if not os.path.exists(STATS_FILE):
        print(f"No stats file found at {STATS_FILE}")
        return []
    with open(STATS_FILE, "r") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    return data


def _safe(val, default=0):
    if val is None:
        return default
    if isinstance(val, dict):
        return val
    return val


def generate_dashboard():
    all_stats = load_stats()
    if not all_stats:
        print("No stats data available.")
        return

    last_30 = all_stats[-30:] if len(all_stats) > 30 else all_stats

    print("=" * 60)
    print("  AI JOBS AGENT — STATISTICS DASHBOARD")
    print("=" * 60)
    print(f"  Period: {last_30[0].get('date', 'N/A')} to {last_30[-1].get('date', 'N/A')}")
    print(f"  Days:   {len(last_30)}")
    print()

    total_jobs = sum(
        entry.get("total", {}).get("jobs_found", 0) for entry in last_30
    )
    total_scored = sum(
        entry.get("total", {}).get("jobs_scored", 0) for entry in last_30
    )
    total_recommended = sum(
        entry.get("total", {}).get("recommended", 0) for entry in last_30
    )
    total_cv = sum(
        entry.get("total", {}).get("cv_generated", 0) for entry in last_30
    )
    total_cl = sum(
        entry.get("total", {}).get("cover_letters", 0) for entry in last_30
    )
    total_uploaded = sum(
        entry.get("total", {}).get("uploaded_to_sheet", 0) for entry in last_30
    )
    total_failed = sum(
        entry.get("total", {}).get("failed_uploads", 0) for entry in last_30
    )
    total_duplicates = sum(
        entry.get("total", {}).get("duplicates", 0) for entry in last_30
    )

    jobs_per_source = defaultdict(int)
    jobs_per_city = defaultdict(int)
    for entry in last_30:
        for src in ["naukri", "indeed", "linkedin"]:
            src_data = entry.get(src, {})
            if isinstance(src_data, dict):
                jobs_per_source[src.capitalize()] += src_data.get("jobs_found", 0)

    all_scores = []
    score_cache = "score_cache.json"
    if os.path.exists(score_cache):
        try:
            with open(score_cache) as f:
                scores = json.load(f)
            for s in scores:
                sc = s.get("score", 0)
                if isinstance(sc, int):
                    all_scores.append(sc)
        except (json.JSONDecodeError, TypeError):
            pass

    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    success_rate = (total_uploaded / (total_uploaded + total_failed) * 100) if (total_uploaded + total_failed) > 0 else 0
    dup_pct = (total_duplicates / (total_jobs + total_duplicates) * 100) if (total_jobs + total_duplicates) > 0 else 0
    gen_pct = (total_cv / total_recommended * 100) if total_recommended > 0 else 0
    sheet_pct = (total_uploaded / total_cv * 100) if total_cv > 0 else 0

    print(f"  Total jobs scraped:     {total_jobs}")
    print(f"  Jobs scored:            {total_scored}")
    print(f"  Average AI score:       {avg_score:.1f}/10")
    print(f"  Recommended:            {total_recommended}")
    print(f"  CV generated:           {total_cv}")
    print(f"  Cover letters:          {total_cl}")
    print(f"  Sheet uploads:          {total_uploaded}")
    print(f"  Failed uploads:         {total_failed}")
    print(f"  Duplicate %:            {dup_pct:.1f}%")
    print(f"  Generation %:           {gen_pct:.1f}%")
    print(f"  Sheet upload %:         {sheet_pct:.1f}%")
    print(f"  Success rate:           {success_rate:.1f}%")
    print()

    dates = [e.get("date", "N/A") for e in last_30]
    jobs_per_day = [e.get("total", {}).get("jobs_found", 0) for e in last_30]
    scored_per_day = [e.get("total", {}).get("jobs_scored", 0) for e in last_30]
    cv_per_day = [e.get("total", {}).get("cv_generated", 0) for e in last_30]

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Jobs Scraped per Day", "Jobs by Source",
            "CVs Generated per Day", "Jobs Scored & Recommended",
            "Scraper Queries", "Scraper Health — Response Times"
        ),
        vertical_spacing=0.12,
        horizontal_spacing=0.1,
    )

    fig.add_trace(
        go.Bar(x=dates, y=jobs_per_day, name="Jobs Found", marker_color="#1f77b4"),
        row=1, col=1,
    )

    source_names = list(jobs_per_source.keys())
    source_vals = list(jobs_per_source.values())
    colors = ["#ff7f0e", "#2ca02c", "#d62728"]
    fig.add_trace(
        go.Bar(x=source_names, y=source_vals, name="Source", marker_color=colors[:len(source_names)]),
        row=1, col=2,
    )

    fig.add_trace(
        go.Bar(x=dates, y=cv_per_day, name="CVs", marker_color="#9467bd"),
        row=2, col=1,
    )

    scored_total = sum(scored_per_day)
    recommended_total = sum(
        e.get("total", {}).get("recommended", 0) for e in last_30
    )
    fig.add_trace(
        go.Bar(x=["Scored", "Recommended"], y=[scored_total, recommended_total],
               marker_color=["#17becf", "#bcbd22"]),
        row=2, col=2,
    )

    queries_per_source = defaultdict(list)
    for entry in last_30:
        for src in ["naukri", "indeed", "linkedin"]:
            sd = entry.get(src, {})
            if isinstance(sd, dict):
                queries_per_source[src.capitalize()].append(sd.get("queries", 0))

    for src_name, vals in queries_per_source.items():
        if vals:
            fig.add_trace(
                go.Scatter(x=dates, y=vals, mode="lines+markers", name=f"{src_name} Queries"),
                row=3, col=1,
            )

    resp_per_source = {}
    for entry in last_30:
        for src in ["naukri", "indeed", "linkedin"]:
            sd = entry.get(src, {})
            if isinstance(sd, dict):
                durations = sd.get("durations", []) or []
                avg = sum(durations) / len(durations) if durations else 0
                if src not in resp_per_source:
                    resp_per_source[src] = []
                resp_per_source[src].append(avg)

    for src_name, vals in resp_per_source.items():
        if vals:
            fig.add_trace(
                go.Scatter(x=dates, y=vals, mode="lines+markers", name=f"{src_name.capitalize()} Avg Resp (s)"),
                row=3, col=2,
            )

    fig.update_layout(
        title_text="AI Jobs Agent — 30-Day Statistics",
        height=900,
        showlegend=True,
        template="plotly_white",
    )
    fig.update_xaxes(tickangle=45)

    fig.write_html("stats_report.html")
    print("  Dashboard exported to stats_report.html")
    print("=" * 60)


if __name__ == "__main__":
    generate_dashboard()
