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
    members = jb.get('member', [])
    id_to_name = {m['playerId']: m['playerName'] for m in members}

    # Normalize currentStat
    stat_list = jb.get('currentStat', [])
    stat_df = pd.json_normalize(stat_list, 'playerStat', ['mapStatId']) if stat_list else pd.DataFrame()
    if stat_df.empty:
        st.info("No currentStat data to display.")
        return

    stat_df['score'] = stat_df['score'].astype(int)
    stat_df['Player'] = stat_df['memberId'].map(id_to_name)
    stat_df['StatName'] = stat_df['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k, k))

    pivot_df = stat_df.pivot_table(
        index='Player',
        columns='StatName',
        values='score',
        aggfunc='sum'
    ).fillna(0).astype(int)

    summary_metrics = {
        'Total Territory Points': '{:,.0f}',
        'Total Mission Attempts': '{:,.0f}',
        'Total Waves Completed': '{:,.0f}',
        'Total Platoons Donated': '{:,.0f}',
        'Total Special Mission Attempts': '{:,.0f}',
        'Total Special Missions Completed': '{:,.0f}'
    }

    # P3-P6 fields
    attempt_names = [f"Mission Attempt Round {p}" for p in range(3,7)]
    wave_names = [f"Waves Completed Round {p}" for p in range(3,7)]
    pivot_df['Total Attempts P3-P6'] = pivot_df[[c for c in attempt_names if c in pivot_df.columns]].sum(axis=1)
    pivot_df['Total Completed Waves P3-P6'] = pivot_df[[c for c in wave_names if c in pivot_df.columns]].sum(axis=1)

    summary_fields = [f for f in summary_metrics if f in pivot_df.columns] + ['Total Attempts P3-P6', 'Total Completed Waves P3-P6']
    summary_df = pivot_df[summary_fields].copy()
    summary_df.index.name = 'Player'

    # Sort
    sort_field = 'Total Territory Points'
    if sort_field in summary_df.columns:
        summary_df = summary_df.sort_values(sort_field, ascending=False)

    # Styled tables
    summary_styled = summary_df.style.format(summary_metrics)
    avg_df = pd.DataFrame([summary_df.mean()])
    avg_df.index = ["Guild Average"]
    avg_styled = (
        avg_df.style
            .format(summary_metrics)
            .set_properties(**{'background-color': '#eeeee4'})
            .set_table_styles([
                {'selector': 'th.row_heading', 'props': [('background-color', '#eeeee4')]},
                {'selector': 'td.row_heading', 'props': [('background-color', '#eeeee4')]}]
            )
    )

    # Status grid
    completed_keys = [k for k in MAP_STAT_NAMES if k.startswith('covert_complete_mission')]
    attempted_keys = [k for k in MAP_STAT_NAMES if k.startswith('covert_round_attempted_mission')]
    status = {}
    for player in pivot_df.index:
        row = {}
        for key in completed_keys:
            name = MAP_STAT_NAMES.get(key, key)
            comp = pivot_df.at[player, name] if name in pivot_df.columns else 0
            base = key.replace('covert_complete_mission_', '')
            atts = [MAP_STAT_NAMES.get(a) for a in attempted_keys if base in a]
            att_count = sum(pivot_df.at[player, a] for a in atts if a in pivot_df.columns)
            row[name] = 1 if comp>0 else (-1 if att_count>0 else 0)
        status[player] = row
    status_df = pd.DataFrame.from_dict(status, orient='index').fillna(0).astype(int)
    status_df.index.name='Player'
    def color_map(v):
        return 'background-color: #66be25; color: transparent' if v==1 else ('background-color: #be4525; color: transparent' if v==-1 else 'background-color: #f59406; color: transparent')
    styled_status = status_df.style.applymap(color_map)

    # Tabs
    tab1, tab2 = st.tabs(["Guild Data", "Player History"])
    st.markdown("""<style>[class^=\"stMainBlockContainer\"] {padding: 2.5rem !important;}</style>""", unsafe_allow_html=True)

    with tab1:
        st.subheader("Guild Summary")
        st.dataframe(avg_styled, hide_index=False)
        st.dataframe(summary_styled, hide_index=False)
        csv_summary = summary_df.to_csv(index=True).encode()
        st.download_button("Download Guild Summary as CSV", csv_summary, "guild_summary.csv", "text/csv")
        st.subheader("Special Mission Status")
        st.dataframe(styled_status, hide_index=False)
        csv_mission = status_df.to_csv(index=True).encode()
        st.download_button("Download Special Mission Status as CSV", csv_mission, "special_mission_status.csv", "text/csv")

    with tab2:
        st.header("Player History")
        # Include Guild Average in options and default select
        player_options = list(pivot_df.index) + ["Guild Average"]
        default_selection = ["Guild Average"]
        players = st.multiselect("Select player(s)", player_options, default=default_selection)
        metrics = st.multiselect("Select fields to display", summary_fields, default=[sort_field] if sort_field in summary_fields else [])
        if players and metrics:
            records=[]
            for date, run in zip(json_dates, jsons):
                df_run = pd.json_normalize(run.get('currentStat', []), 'playerStat', ['mapStatId']) if run.get('currentStat') else pd.DataFrame()
                if df_run.empty: continue
                df_run['score']=df_run['score'].astype(int)
                df_run['Player']=df_run['memberId'].map(id_to_name)
                df_run['StatName']=df_run['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k,k))
                piv = df_run.pivot_table(index='Player', columns='StatName', values='score', aggfunc='sum').fillna(0).astype(int)
                piv['Total Attempts P3-P6']=piv[[c for c in attempt_names if c in piv.columns]].sum(axis=1)
                piv['Total Completed Waves P3-P6']=piv[[c for c in wave_names if c in piv.columns]].sum(axis=1)
                for pl in players:
                    for m in metrics:
                        if pl=="Guild Average":
                            val = piv[m].mean() if m in piv.columns else 0
                        else:
                            val = piv.at[pl,m] if pl in piv.index and m in piv.columns else 0
                        records.append({'Date':date,'Player':pl,'Metric':m,'Value':val})
            hist_df=pd.DataFrame(records).sort_values('Date')
            chart=alt.Chart(hist_df).mark_line(point=True).encode(
                x=alt.X('Date:T',title='Date',axis=alt.Axis(format='%d-%m-%y')),
                y=alt.Y('Value:Q',title='Value'),
                color='Player:N',strokeDash='Metric:N'
            ).properties(width=700,height=400)
            st.altair_chart(chart)
        else:
            st.info("Select at least one player and one field.")

if __name__=='__main__': main()
