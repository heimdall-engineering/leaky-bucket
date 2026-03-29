"""Live KPI Dashboard for LeakyBucket simulation.

Three-panel layout:
  1. Rider Experience (Pain Metrics)
  2. System Efficiency (Throughput Metrics)
  3. Supply & Quality (Sustainability Metrics)

Usage:
    streamlit run dashboard.py
    ./run.sh --compare  # launches sim + dashboard together
"""

from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="LeakyBucket Dashboard",
    page_icon="🚗",
    layout="wide",
)

# ── Helpers ──────────────────────────────────────────────────────────────


def find_csv_files(output_dir: str) -> dict[str, Path]:
    files = {}
    for path in sorted(Path(output_dir).rglob("kpi_*.csv")):
        name = path.stem.replace("kpi_", "").replace("_", " ")
        files[name] = path
    return files


def load_csv(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
        return df if not df.empty else pd.DataFrame()
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def safe_col(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns


# ── Panel 1: Rider Experience ────────────────────────────────────────────


def render_rider_experience(df: pd.DataFrame) -> None:
    st.markdown("### 1. Rider Experience")
    st.caption("The friction felt by people trying to leave the event")

    latest = df.iloc[-1]

    # Top metrics
    cols = st.columns(4)
    cols[0].metric("Avg Wait Time", f"{latest['avg_wait_time']:.0f}s")
    cols[1].metric("P95 Wait Time", f"{latest['p95_wait_time']:.0f}s")
    if safe_col(df, "avg_etr"):
        cols[2].metric("Avg ETR", f"{latest['avg_etr']:.0f}s")
    if safe_col(df, "match_failure_rate"):
        cols[3].metric("Match Failure", f"{latest['match_failure_rate']:.1f}%")

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Wait Times (AWT & P95)**")
        chart_cols = ["avg_wait_time", "p95_wait_time"]
        st.line_chart(
            df.set_index("step")[chart_cols],
            color=["#4CAF50", "#FF5722"],
        )

    with col_r:
        if safe_col(df, "match_failure_rate"):
            st.markdown("**Match Failure Rate (%)**")
            st.area_chart(
                df.set_index("step")[["match_failure_rate"]],
                color=["#E91E63"],
            )
        elif safe_col(df, "avg_etr"):
            st.markdown("**Estimated Time to Request (ETR)**")
            st.line_chart(
                df.set_index("step")[["avg_etr"]],
                color=["#FF9800"],
            )

    # Rider status breakdown
    status_cols = [c for c in ["riders_waiting", "riders_matched", "riders_in_vehicle", "riders_delivered"] if safe_col(df, c)]
    if status_cols:
        st.markdown("**Rider Status Over Time**")
        st.area_chart(
            df.set_index("step")[status_cols],
            color=["#FF9800", "#2196F3", "#9C27B0", "#4CAF50"][:len(status_cols)],
        )


# ── Panel 2: System Efficiency ───────────────────────────────────────────


def render_system_efficiency(df: pd.DataFrame) -> None:
    st.markdown("### 2. System Efficiency")
    st.caption("How well the crowd is being cleared")

    latest = df.iloc[-1]

    cols = st.columns(4)
    cols[0].metric("Clearance Rate", f"{latest['clearance_rate']:.1f}/min")
    if safe_col(df, "total_evacuation_pct"):
        cols[1].metric("Evacuated", f"{latest['total_evacuation_pct']:.1f}%")
    if safe_col(df, "riders_delivered") and safe_col(df, "riders_total"):
        cols[2].metric("Delivered", f"{int(latest['riders_delivered'])} / {int(latest['riders_total'])}")
    if safe_col(df, "dead_mileage_ratio"):
        cols[3].metric("Dead Mileage", f"{latest['dead_mileage_ratio'] * 100:.1f}%")

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Clearance Rate (passengers/min)**")
        st.area_chart(
            df.set_index("step")[["clearance_rate"]],
            color=["#2196F3"],
        )

    with col_r:
        if safe_col(df, "total_evacuation_pct"):
            st.markdown("**Total Evacuation Progress (%)**")
            st.line_chart(
                df.set_index("step")[["total_evacuation_pct"]],
                color=["#4CAF50"],
            )

    if safe_col(df, "dead_mileage_ratio"):
        st.markdown("**Dead Mileage Ratio (cruising without passenger)**")
        st.area_chart(
            df.set_index("step")[["dead_mileage_ratio"]],
            color=["#FF5722"],
        )


# ── Panel 3: Supply & Quality ────────────────────────────────────────────


def render_supply_quality(df: pd.DataFrame) -> None:
    st.markdown("### 3. Supply & Quality")
    st.caption("Driver sustainability and ride quality")

    latest = df.iloc[-1]

    cols = st.columns(4)
    cols[0].metric("Driver Utilization", f"{latest['driver_utilization'] * 100:.1f}%")
    cols[1].metric("Braking Events", f"{int(latest['braking_intensity'])}")
    if safe_col(df, "effective_eph"):
        cols[2].metric("Earnings/Hour", f"${latest['effective_eph']:.0f}")
    drivers_total = 0
    for c in ["drivers_idle", "drivers_en_route", "drivers_occupied", "drivers_returning"]:
        if safe_col(df, c):
            drivers_total += int(latest[c])
    if drivers_total:
        cols[3].metric("Fleet Size", f"{drivers_total}")

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Driver Utilization Over Time**")
        # Convert to percentage for display
        util_df = df.set_index("step")[["driver_utilization"]].copy()
        util_df["driver_utilization"] = util_df["driver_utilization"] * 100
        st.line_chart(util_df, color=["#4CAF50"])

        # Utilization health indicator
        util_pct = latest["driver_utilization"] * 100
        if util_pct > 95:
            st.error(f"Utilization at {util_pct:.0f}% — system is brittle, zero buffer")
        elif util_pct > 80:
            st.warning(f"Utilization at {util_pct:.0f}% — approaching saturation")
        elif util_pct > 50:
            st.success(f"Utilization at {util_pct:.0f}% — healthy range")

    with col_r:
        if safe_col(df, "effective_eph"):
            st.markdown("**Effective Earnings Per Hour ($)**")
            st.line_chart(
                df.set_index("step")[["effective_eph"]],
                color=["#8BC34A"],
            )

    st.markdown("**Braking Intensity (harsh events per interval)**")
    st.bar_chart(
        df.set_index("step")[["braking_intensity"]],
        color=["#F44336"],
    )

    # Driver status breakdown
    driver_cols = [c for c in ["drivers_idle", "drivers_en_route", "drivers_occupied", "drivers_returning"] if safe_col(df, c)]
    if driver_cols:
        st.markdown("**Driver Status Over Time**")
        st.area_chart(
            df.set_index("step")[driver_cols],
            color=["#8BC34A", "#FF9800", "#F44336", "#9C27B0"][:len(driver_cols)],
        )


# ── Strategy View (all 3 panels) ─────────────────────────────────────────


def render_strategy(name: str, df: pd.DataFrame) -> None:
    if df.empty:
        st.warning(f"No data yet for {name}")
        return

    render_rider_experience(df)
    st.divider()
    render_system_efficiency(df)
    st.divider()
    render_supply_quality(df)


# ── Comparison View ───────────────────────────────────────────────────────


def render_comparison(all_data: dict[str, pd.DataFrame]) -> None:
    st.header("Strategy Comparison")

    frames = {n: d.set_index("step") for n, d in all_data.items() if not d.empty}

    if len(frames) < 2:
        st.info("Run multiple strategies to see comparisons. Use: `./run.sh --compare`")
        return

    # Comparison charts: 3 panels × 2 columns
    st.markdown("### Rider Experience")
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Avg Wait Time**")
        st.line_chart(pd.DataFrame({n: d["avg_wait_time"] for n, d in frames.items()}))
    with col_r:
        st.markdown("**P95 Wait Time**")
        st.line_chart(pd.DataFrame({n: d["p95_wait_time"] for n, d in frames.items()}))

    if all(safe_col(d, "match_failure_rate") for d in all_data.values() if not d.empty):
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**Match Failure Rate (%)**")
            st.line_chart(pd.DataFrame({n: d["match_failure_rate"] for n, d in frames.items()}))
        with col_r:
            st.markdown("**Avg ETR**")
            st.line_chart(pd.DataFrame({n: d["avg_etr"] for n, d in frames.items()}))

    st.divider()
    st.markdown("### System Efficiency")
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Clearance Rate (passengers/min)**")
        st.line_chart(pd.DataFrame({n: d["clearance_rate"] for n, d in frames.items()}))
    with col_r:
        if all(safe_col(d, "total_evacuation_pct") for d in all_data.values() if not d.empty):
            st.markdown("**Total Evacuation (%)**")
            st.line_chart(pd.DataFrame({n: d["total_evacuation_pct"] for n, d in frames.items()}))

    if all(safe_col(d, "dead_mileage_ratio") for d in all_data.values() if not d.empty):
        st.markdown("**Dead Mileage Ratio**")
        st.line_chart(pd.DataFrame({n: d["dead_mileage_ratio"] for n, d in frames.items()}))

    st.divider()
    st.markdown("### Supply & Quality")
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Driver Utilization**")
        st.line_chart(pd.DataFrame({n: d["driver_utilization"] * 100 for n, d in frames.items()}))
    with col_r:
        if all(safe_col(d, "effective_eph") for d in all_data.values() if not d.empty):
            st.markdown("**Effective Earnings/Hour ($)**")
            st.line_chart(pd.DataFrame({n: d["effective_eph"] for n, d in frames.items()}))

    # Summary table
    st.divider()
    st.markdown("### Final Metrics Summary")
    rows = []
    for name, df in all_data.items():
        if df.empty:
            continue
        last = df.iloc[-1]
        row = {
            "Strategy": name,
            "AWT (s)": f"{last['avg_wait_time']:.0f}",
            "P95 (s)": f"{last['p95_wait_time']:.0f}",
        }
        if safe_col(df, "match_failure_rate"):
            row["Fail %"] = f"{last['match_failure_rate']:.1f}"
        if safe_col(df, "riders_delivered") and safe_col(df, "riders_total"):
            row["Delivered"] = f"{int(last['riders_delivered'])}/{int(last['riders_total'])}"
        if safe_col(df, "total_evacuation_pct"):
            row["Evac %"] = f"{last['total_evacuation_pct']:.1f}"
        if safe_col(df, "dead_mileage_ratio"):
            row["Dead Mi."] = f"{last['dead_mileage_ratio'] * 100:.1f}%"
        row["Util %"] = f"{last['driver_utilization'] * 100:.1f}"
        if safe_col(df, "effective_eph"):
            row["EPH ($)"] = f"{last['effective_eph']:.0f}"
        rows.append(row)
    if rows:
        st.table(pd.DataFrame(rows).set_index("Strategy"))


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    output_dir = st.sidebar.text_input("Output directory", value="output")
    auto_refresh = st.sidebar.checkbox("Auto-refresh (live mode)", value=True)

    if auto_refresh:
        st.sidebar.caption("Refreshing every 5 seconds")

    csv_files = find_csv_files(output_dir)

    if not csv_files:
        st.title("LeakyBucket Dashboard")
        st.warning(
            f"No KPI files found in `{output_dir}/`. "
            "Start a simulation first:\n\n"
            "```bash\n./run.sh --strategy baseline\n```"
        )
        if auto_refresh:
            st.rerun()
        return

    all_data = {name: load_csv(path) for name, path in csv_files.items()}

    st.title("LeakyBucket Dashboard")

    strategy_names = list(csv_files.keys())
    if len(strategy_names) > 1:
        tabs = st.tabs(["Comparison"] + strategy_names)
        with tabs[0]:
            render_comparison(all_data)
        for i, name in enumerate(strategy_names):
            with tabs[i + 1]:
                st.header(name)
                render_strategy(name, all_data[name])
    else:
        name = strategy_names[0]
        st.header(name)
        render_strategy(name, all_data[name])

    if auto_refresh:
        import time
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
