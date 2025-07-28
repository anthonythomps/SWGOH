
import streamlit as st
import pandas as pd
import glob
import os
import json
import re
from datetime import datetime
import altair as alt

# Load friendly name mapping
MAP_STAT_FILE = 'data/map_stat_names.json'
try:
    with open(MAP_STAT_FILE) as mf:
        MAP_STAT_NAMES = json.load(mf)
except FileNotFoundError:
    MAP_STAT_NAMES = {}

# Helper to extract date from filename
def extract_date(fp):
    name = os.path.basename(fp)
    m = re.search(r'tb_data_(\d{6})', name)
    return datetime.strptime(m.group(1), '%d%m%y') if m else None

# Cache JSON loading
@st.cache_data
def load_all_json():
    """Load all TB JSON files and their dates."""
    files = glob.glob(os.path.join('data', 'tb_data_*.json'))
    files = [f for f in files if extract_date(f)]
    files.sort(key=extract_date)
    jsons = []
    dates = []
    for fp in files:
        dates.append(extract_date(fp))
        with open(fp) as f:
            jsons.append(json.load(f))
    return dates, jsons

# Main function
def main():
    st.set_page_config(page_title="SWGOH", page_icon="🔥", layout="wide")
    st.title("Guild Data")

    # Load JSON data
    json_dates, jsons = load_all_json()
    if not jsons:
        st.warning("No TB JSON files found in data folder.")
        return

    # Use the latest run
    jb = jsons[-1]
    # Map playerId to playerName
    members = jb.get('member', [])
    id_to_name = {m['playerId']: m['playerName'] for m in members}

    # Extract and normalize currentStat
    stat_list = jb.get('currentStat', [])
    stat_df = pd.json_normalize(stat_list, 'playerStat', ['mapStatId']) if stat_list else pd.DataFrame()
    if stat_df.empty:
        st.info("No currentStat data to display.")
        return

    # Process stats
    stat_df['score'] = stat_df['score'].astype(int)
    stat_df['Player'] = stat_df['memberId'].map(id_to_name)
    stat_df['StatName'] = stat_df['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k, k))

    # Pivot to wide format
    pivot_df = stat_df.pivot_table(
        index='Player',
        columns='StatName',
        values='score',
        aggfunc='sum'
    ).fillna(0).astype(int)

        # Define summary metrics and formatting
    summary_metrics = {
        'Total Territory Points': '{:,.0f}',
        'Total Mission Attempts': '{:,.0f}',
        'Total Waves Completed': '{:,.0f}',
        'Total Platoons Donated': '{:,.0f}',
        'Total Special Mission Attempts': '{:,.0f}',
        'Total Special Missions Completed': '{:,.0f}'
    }

    # Calculate additional fields P3-P6
    # Friendly names for attempts and waves from map stat mapping
    attempt_names = [f"Mission Attempt Round {p}" for p in range(3,7)]
    wave_names = [f"Waves Completed Round {p}" for p in range(3,7)]
    # Sum across those columns if present
    pivot_df['Total Attempts P3-P6'] = pivot_df[[c for c in attempt_names if c in pivot_df.columns]].sum(axis=1)
    pivot_df['Total Completed Waves P3-P6'] = pivot_df[[c for c in wave_names if c in pivot_df.columns]].sum(axis=1)

        # Build summary DataFrame
    summary_fields = [f for f in summary_metrics if f in pivot_df.columns] + ['Total Attempts P3-P6', 'Total Completed Waves P3-P6']
    summary_df = pivot_df[summary_fields].copy()
    summary_df.index.name = 'Player'

    # Default sort configuration
    sort_field = 'Total Territory Points'
    ascending = False
    if sort_field in summary_df.columns:
        summary_df = summary_df.sort_values(sort_field, ascending=ascending)

        # Apply formatting
    summary_styled = summary_df.style.format(summary_metrics)

    # Compute completed mission status grid
    # Identify completed and attempted mission mapStatIds
    completed_keys = [k for k in MAP_STAT_NAMES.keys() if k.startswith('covert_complete_mission')]
    attempted_keys = [k for k in MAP_STAT_NAMES.keys() if k.startswith('covert_round_attempted_mission')]
    # Build status DataFrame: 1=complete, -1=attempted but not complete, 0=not attempted
    status_dict = {}
    for player in pivot_df.index:
        row_dict = {}
        for key in completed_keys:
            name = MAP_STAT_NAMES.get(key, key)
            completed_count = pivot_df.at[player, name] if name in pivot_df.columns else 0
            # identify corresponding attempts by base
            base = key.replace('covert_complete_mission_', '')
            attempt_names = [MAP_STAT_NAMES.get(a) for a in attempted_keys if base in a]
            attempted_count = sum(pivot_df.at[player, an] for an in attempt_names if an in pivot_df.columns)
            if completed_count > 0:
                status = 1
            elif attempted_count > 0:
                status = -1
            else:
                status = 0
            row_dict[name] = status
        status_dict[player] = row_dict
    status_df = pd.DataFrame.from_dict(status_dict, orient='index').fillna(0).astype(int)
    status_df.index.name = 'Player'
    # Style grid: hide values, color backgrounds
    def color_map(val):
        if val == 1:
            return 'background-color: #66be25; color: transparent'
        elif val == -1:
            return 'background-color: #be4525; color: transparent'
        else:
            return 'background-color: #f59406; color: transparent'
    styled_status = status_df.style.applymap(color_map)

    # Tabs for Guild Data and Player History
    tab1, tab2 = st.tabs(["Guild Data", "Player History"])

    # Page Setup
    st.markdown(
    """
    <style>
      [class^="stMainBlockContainer"] {
        padding: 2.5rem !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
    with tab1:
        st.subheader("Guild Summary")
        st.dataframe(summary_styled, hide_index=False)

        st.subheader("Special Mission Status")
        st.dataframe(styled_status, hide_index=False)

    with tab2:
        st.header("Player History")
        players = st.multiselect("Select player(s)", list(pivot_df.index))
        metrics = st.multiselect(
            "Select fields to display", summary_fields,
            default=[sort_field] if sort_field in summary_fields else []
        )
        if players and metrics:
            history_records = []
            for date, jb_run in zip(json_dates, jsons):
                df_run = pd.json_normalize(jb_run.get('currentStat', []), 'playerStat', ['mapStatId']) if jb_run.get('currentStat', []) else pd.DataFrame()
                if df_run.empty:
                    continue
                df_run['score'] = df_run['score'].astype(int)
                df_run['Player'] = df_run['memberId'].map(id_to_name)
                df_run['StatName'] = df_run['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k, k))
                pivot_run = df_run.pivot_table(
                    index='Player', columns='StatName', values='score', aggfunc='sum'
                ).fillna(0).astype(int)
                # Calculate P3-P6 totals for this historical run
                attempt_names = [f"Mission Attempt Round {p}" for p in range(3,7)]
                wave_names = [f"Waves Completed Round {p}" for p in range(3,7)]
                if attempt_names:
                    pivot_run['Total Attempts P3-P6'] = pivot_run[[c for c in attempt_names if c in pivot_run.columns]].sum(axis=1)
                if wave_names:
                    pivot_run['Total Completed Waves P3-P6'] = pivot_run[[c for c in wave_names if c in pivot_run.columns]].sum(axis=1)
                pivot_run = pivot_run.fillna(0).astype(int)
                for pl in players:
                    for m in metrics:
                        val = pivot_run.at[pl, m] if pl in pivot_run.index and m in pivot_run.columns else 0
                        history_records.append({'Date': date, 'Player': pl, 'Metric': m, 'Value': val})
            hist_df = pd.DataFrame(history_records).sort_values('Date')
            chart = alt.Chart(hist_df).mark_line(point=True).encode(
                x=alt.X('Date:T', title='Date', axis=alt.Axis(format='%d-%m-%y')),
                y=alt.Y('Value:Q', title='Value'),
                color='Player:N', strokeDash='Metric:N'
            ).properties(width=700, height=400)
            st.altair_chart(chart)
        else:
            st.info("Select at least one player and one field.")

if __name__ == '__main__':
    main()
