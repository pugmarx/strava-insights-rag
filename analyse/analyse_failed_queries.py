#!/usr/bin/env python3
"""
Audit & Assessment tool for failed or unrecognized queries in Strava Insights RAG.
Run this script regularly (e.g. daily/weekly or via cron) to inspect failure patterns,
zero-result queries, and performance bottlenecks.
"""

import sys
import os
import argparse
import json
from datetime import datetime

# Add backend directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from query_logger import fetch_failed_queries, get_query_health_summary


def generate_recommendations(failed_queries):
    """Analyze failed query patterns and provide actionable engineering recommendations."""
    recommendations = []
    
    if not failed_queries:
        return ["System is operating at 100% success rate. No query failures detected!"]

    # Pattern heuristics
    missing_sports = []
    has_relative_time = False
    has_aggregations = False
    has_recency = False

    for item in failed_queries:
        q = (item.get("query_text") or "").lower()
        if any(w in q for w in ["kayak", "rowing", "skate", "yoga", "pilates", "crossfit"]):
            missing_sports.append(q)
        if any(w in q for w in ["last month", "last year", "past 2 weeks", "this week"]):
            has_relative_time = True
        if any(w in q for w in ["average", "avg", "total", "sum", "how much", "how many"]):
            has_aggregations = True
        if any(w in q for w in ["last", "latest", "recent", "past"]):
            has_recency = True

    if missing_sports:
        recommendations.append(
            f"Detected queries for uncommon sport types ({len(missing_sports)} queries). Consider expanding matched_types in sql_rag.py."
        )
    if has_relative_time:
        recommendations.append(
            "Detected unparsed relative time filters. Review extract_time_filters() in sql_rag.py."
        )
    if has_aggregations:
        recommendations.append(
            "Detected aggregation requests that yielded no results. Consider routing these to hybrid_query_handler."
        )
    if has_recency:
        recommendations.append(
            "Detected recency queries. Ensure extract_recency_and_limit() correctly extracts N and orders by timestamp DESC."
        )

    if not recommendations:
        recommendations.append(
            "Review query logs individually to verify if data was genuinely absent from the Strava database."
        )

    return recommendations


def print_audit_report(summary, recent_failures, days):
    """Print clean terminal report."""
    print("=" * 70)
    print(f" STRAVA INSIGHTS RAG - QUERY AUDIT & HEALTH REPORT (Last {days} Days)")
    print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    total = summary.get("total_queries", 0)
    success = summary.get("successful_queries", 0)
    no_results = summary.get("no_results_queries", 0)
    errors = summary.get("error_queries", 0)
    unrecognized = summary.get("unrecognized_queries", 0)
    rate = summary.get("success_rate_percent", 100.0)
    latency = summary.get("avg_latency_ms", 0)

    print("\n[📊 Overview Statistics]")
    print(f"  • Total Queries Logged : {total}")
    print(f"  • Successful Responses : {success} ({rate}%)")
    print(f"  • Zero-Result Queries  : {no_results}")
    print(f"  • Error/Exception Hits : {errors}")
    print(f"  • Unrecognized Patterns: {unrecognized}")
    print(f"  • Average Latency      : {latency} ms")

    top_failed = summary.get("top_failed_queries", [])
    print("\n[🚨 Top Failed / Zero-Result Query Patterns]")
    if top_failed:
        for idx, item in enumerate(top_failed, 1):
            q_text = item.get("query_text", "")
            cnt = item.get("count", 1)
            st = item.get("status", "FAILED")
            err = item.get("error_message") or "No matching activities"
            print(f"  {idx}. [{cnt}x] \"{q_text}\" (Status: {st})")
            if err:
                print(f"     Reason: {err}")
    else:
        print("  None! All queries succeeded in this time window.")

    print("\n[💡 Actionable Improvement Recommendations]")
    recommendations = generate_recommendations(top_failed)
    for idx, rec in enumerate(recommendations, 1):
        print(f"  {idx}. {rec}")

    print("\n[📝 Recent Failed Log Entries]")
    if recent_failures:
        for f in recent_failures[:10]:
            ts = f.get("created_at") or f.get("timestamp") or "Unknown"
            q = f.get("query_text", "")
            st = f.get("status", "")
            err = f.get("error_message") or "N/A"
            print(f"  • [{ts}] ({st}) \"{q}\" -> {err}")
    else:
        print("  No recent failures.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Strava Insights RAG Query Failure Auditor")
    parser.add_argument("--days", type=int, default=7, help="Number of days to inspect (default: 7)")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of failure rows to fetch (default: 20)")
    parser.add_argument("--export", type=str, default=None, help="Optional filepath to export report in JSON or Markdown")
    args = parser.parse_args()

    summary = get_query_health_summary(days=args.days)
    recent_failures = fetch_failed_queries(limit=args.limit, days=args.days)

    print_audit_report(summary, recent_failures, args.days)

    if args.export:
        export_path = args.export
        if export_path.endswith(".json"):
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump({
                    "summary": summary,
                    "recent_failures": recent_failures,
                    "recommendations": generate_recommendations(summary.get("top_failed_queries", []))
                }, f, indent=2, default=str)
            print(f"\n[Export] Saved JSON audit report to: {export_path}")
        elif export_path.endswith(".md"):
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(f"# Query Failure Audit Report ({args.days} Days)\n\n")
                f.write(f"- **Total Queries**: {summary.get('total_queries', 0)}\n")
                f.write(f"- **Success Rate**: {summary.get('success_rate_percent', 100.0)}%\n")
                f.write(f"- **Zero Results**: {summary.get('no_results_queries', 0)}\n")
                f.write(f"- **Errors**: {summary.get('error_queries', 0)}\n\n")
                f.write("## Top Failed Queries\n\n")
                for item in summary.get("top_failed_queries", []):
                    f.write(f"- **{item.get('query_text')}** ({item.get('count')}x) - *{item.get('status')}*\n")
            print(f"\n[Export] Saved Markdown audit report to: {export_path}")


if __name__ == "__main__":
    main()
