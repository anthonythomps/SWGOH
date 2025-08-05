import streamlit as st
import pandas as pd
import glob
import os
import json
import re
from datetime import datetime
import altair as alt

st.markdown(
    """
    <style>
      [class^="stMainBlockContainer"] {
        padding: 1.5rem !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
# Load friendly name mapping for stats and zones → planet names
MAP_STAT_FILE = 'data/map_stat_names.json'
try:
    with open(MAP_STAT_FILE) as mf:
        MAP_STAT_NAMES = json.load(mf)
except FileNotFoundError:
    MAP_STAT_NAMES = {}

# Load zone definitions (thresholds & alignment for each planet)
ZONES_FILE = 'data/zones.json'
try:
    with open(ZONES_FILE) as zf:
        ZONE_DEFS = json.load(zf)
except FileNotFoundError:
    ZONE_DEFS = {}

# Helper to extract date from filename
def extract_date(fp):
    name = os.path.basename(fp)
    m = re.search(r'tb_data_(\d{6})', name)
    return datetime.strptime(m.group(1), '%d%m%y') if m else None

@st.cache_data
def load_all_json():
    files = glob.glob(os.path.join('data', 'tb_data_*.json'))
    files = [f for f in files if extract_date(f)]
    files.sort(key=extract_date)
    dates, jsons = [], []
    for fp in files:
        dates.append(extract_date(fp))
        with open(fp) as f:
            jsons.append(json.load(f))
    return dates, jsons

def main():
    st.set_page_config(page_title="SWGOH", page_icon="🔥", layout="wide")
    st.title("Guild Data")

    # Load JSON snapshots
    json_dates, jsons = load_all_json()
    if not jsons:
        st.warning("No TB JSON files found in data folder.")
        return

    # Use latest snapshot
    jb = jsons[-1]
    members = jb.get('member', [])
    id_to_name = {m['playerId']: m['playerName'] for m in members}

    # ---- Compute and display Current Status ----
    status = []
    for cz in jb.get("conflictZoneStatus", []):
        zs = cz.get("zoneStatus", {})
        zone_id = zs.get("zoneId")
        score = int(zs.get("score", 0))
        if score <= 0 or not zone_id:
            continue
        planet = MAP_STAT_NAMES.get(zone_id, zone_id)
        alignment = ZONE_DEFS.get(planet, {}).get("Alignment", "Unknown")
        thresholds = [
            ZONE_DEFS[planet].get(f"{i}-star")
            for i in [1, 2, 3]
            if ZONE_DEFS.get(planet, {}).get(f"{i}-star") is not None
        ]
        stars = sum(1 for t in thresholds if score >= t)
        star_str = "★" * stars + "☆" * (len(thresholds) - stars)
        status.append((planet, alignment, score, star_str))

    # Create three tabs
    tab1, tab2, tab3 = st.tabs(["Guild Data", "Player History", "Edit Current TB"])

    # ---- Tab 1: Guild Data ----
    with tab1:
        st.subheader("Current Status:")
        # compute total achieved stars across all planets
        total_stars = sum(star_str.count("★") for _, _, _, star_str in status)
        st.markdown(f"**Total Stars:** {total_stars}/56", unsafe_allow_html=True)

        for planet, alignment, score, star_str in status:
            st.markdown(
                f"**{planet}** → {alignment} → {score:,} → "
                f"<span style='color:gold'>{star_str}</span>",
                unsafe_allow_html=True
            )

        st.subheader("Guild Summary")

        # Normalize stats for guild summary
        stat_list = jb.get('currentStat', [])
        stat_df = (
            pd.json_normalize(stat_list, 'playerStat', ['mapStatId'])
            if stat_list else pd.DataFrame()
        )
        if stat_df.empty:
            st.info("No currentStat data to display.")
            return

        stat_df['score'] = stat_df['score'].astype(int)
        stat_df['Player'] = stat_df['memberId'].map(id_to_name)
        stat_df['StatName'] = stat_df['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k, k))

        pivot_df = (
            stat_df
            .pivot_table(index='Player', columns='StatName', values='score', aggfunc='sum')
            .fillna(0)
            .astype(int)
        )

        # Define formats for summary metrics
        summary_metrics = {
            'Total Territory Points': '{:,.0f}',
            'Total Mission Attempts': '{:,.0f}',
            'Total Waves Completed': '{:,.0f}',
            'Total Platoons Donated': '{:,.0f}',
            'Total Special Mission Attempts': '{:,.0f}',
            'Total Special Missions Completed': '{:,.0f}'
        }

        # Compute P3-P6 totals
        attempt_names = [f"Mission Attempt Round {p}" for p in range(3, 7)]
        wave_names    = [f"Waves Completed Round {p}" for p in range(3, 7)]
        pivot_df['Total Attempts P3-P6'] = pivot_df[[c for c in attempt_names if c in pivot_df.columns]].sum(axis=1)
        pivot_df['Total Completed Waves P3-P6'] = pivot_df[[c for c in wave_names if c in pivot_df.columns]].sum(axis=1)

        # Build and sort summary DataFrame
        summary_fields = [f for f in summary_metrics if f in pivot_df.columns] + [
            'Total Attempts P3-P6', 'Total Completed Waves P3-P6'
        ]
        summary_df = pivot_df[summary_fields].copy()
        summary_df.index.name = 'Player'
        sort_field = 'Total Territory Points'
        if sort_field in summary_df.columns:
            summary_df = summary_df.sort_values(sort_field, ascending=False)

        summary_styled = summary_df.style.format(summary_metrics)

        # Guild average row
        avg_df = pd.DataFrame([summary_df.mean()])
        avg_df.index = ["Guild Average"]
        avg_format = summary_metrics.copy()
        avg_format['Total Attempts P3-P6'] = '{:.2f}'
        avg_format['Total Completed Waves P3-P6'] = '{:.2f}'
        avg_styled = avg_df.style.format(avg_format)

        # Special mission status grid
        completed_keys = [k for k in MAP_STAT_NAMES if k.startswith('covert_complete_mission')]
        attempted_keys = [k for k in MAP_STAT_NAMES if k.startswith('covert_round_attempted_mission')]
        status_dict = {}
        for player in pivot_df.index:
            row = {}
            for key in completed_keys:
                name = MAP_STAT_NAMES.get(key, key)
                comp = pivot_df.at[player, name] if name in pivot_df.columns else 0
                base = key.replace('covert_complete_mission_', '')
                atts = [MAP_STAT_NAMES.get(a) for a in attempted_keys if base in a]
                att_count = sum(pivot_df.at[player, a] for a in atts if a in pivot_df.columns)
                row[name] = 1 if comp > 0 else (-1 if att_count > 0 else 0)
            status_dict[player] = row
        status_df = pd.DataFrame.from_dict(status_dict, orient='index').fillna(0).astype(int)
        status_df.index.name = 'Player'
        def color_map(v):
            if v == 1:   return 'background-color: #66be25; color: transparent'
            if v == -1:  return 'background-color: #be4525; color: transparent'
            return 'background-color: #f59406; color: transparent'
        styled_status = status_df.style.applymap(color_map)

        # Player filter multiselect
        selected = st.multiselect(
            "Filter players (or All)",
            options=sorted(summary_df.index.tolist())
        )

        # Display guild average & summary table
        st.dataframe(avg_styled, hide_index=False)
        if not selected:
            df_show = summary_df
            status_show = status_df
            style_show = summary_styled
            status_style_show = styled_status
        else:
            df_show = summary_df.loc[selected]
            status_show = status_df.loc[selected]
            style_show = df_show.style.format(summary_metrics)
            status_style_show = status_show.style.applymap(color_map)

        st.dataframe(style_show, hide_index=False)
        st.download_button(
            label="Download Guild Summary as CSV",
            data=df_show.to_csv(index=True).encode("utf-8"),
            file_name="guild_summary.csv",
            mime="text/csv"
        )

        st.subheader("Special Mission Status")
        st.dataframe(status_style_show, hide_index=False)
        st.download_button(
            label="Download Special Mission Status as CSV",
            data=status_show.to_csv(index=True).encode("utf-8"),
            file_name="special_mission_status.csv",
            mime="text/csv"
        )

    # ---- Tab 2: Player History ----
    with tab2:
        st.header("Player History")
        player_opts = list(pivot_df.index) + ["Guild Average"]
        hist_players = st.multiselect(
            "Select player(s)", player_opts,
            default=["Guild Average"]
        )
        metrics = st.multiselect(
            "Select fields to display", summary_fields,
            default=["Total Waves Completed"] if sort_field in summary_fields else []
        )
        if hist_players and metrics:
            records = []
            for date, run in zip(json_dates, jsons):
                df_run = (
                    pd.json_normalize(run.get('currentStat', []), 'playerStat', ['mapStatId'])
                    if run.get('currentStat') else pd.DataFrame()
                )
                if df_run.empty: continue
                df_run['score'] = df_run['score'].astype(int)
                df_run['Player'] = df_run['memberId'].map(id_to_name)
                df_run['StatName'] = df_run['mapStatId'].map(lambda k: MAP_STAT_NAMES.get(k, k))
                piv = (
                    df_run
                    .pivot_table(index='Player', columns='StatName', values='score', aggfunc='sum')
                    .fillna(0).astype(int)
                )
                piv['Total Attempts P3-P6'] = piv[[c for c in attempt_names if c in piv.columns]].sum(axis=1)
                piv['Total Completed Waves P3-P6'] = piv[[c for c in wave_names if c in piv.columns]].sum(axis=1)
                for pl in hist_players:
                    for m in metrics:
                        if pl == "Guild Average":
                            val = piv[m].mean() if m in piv.columns else 0
                        else:
                            val = piv.at[pl, m] if pl in piv.index and m in piv.columns else 0
                        records.append({'Date': date, 'Player': pl, 'Metric': m, 'Value': val})
            hist_df = pd.DataFrame(records).sort_values('Date')
            chart = (
                alt.Chart(hist_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X('Date:T', title='Date', axis=alt.Axis(format='%d-%m-%y')),
                    y=alt.Y('Value:Q', title='Value'),
                    color='Player:N',
                    strokeDash='Metric:N'
                )
                .properties(width=500, height=500)
            )
            st.altair_chart(chart)
        else:
            st.info("Select at least one player and one field.")

    # ---- Tab 3: Edit Current TB ----
    with tab3:
        st.header("Edit Current TB")
        files = glob.glob(os.path.join('data', 'tb_data_*.json'))
        files = [f for f in files if extract_date(f)]
        files.sort(key=extract_date)
        if not files:
            st.warning("No TB JSON files to edit.")
        else:
            latest_fp = files[-1]
            st.write(f"Editing file: {latest_fp}")
            try:
                with open(latest_fp) as f:
                    raw = f.read()
            except IOError as e:
                st.error(f"Error loading file: {e}")
                raw = ""
            edited = st.text_area("Edit JSON here:", value=raw, height=600)
            if st.button("Save Changes"):
                try:
                    parsed = json.loads(edited)
                    with open(latest_fp, "w") as f:
                        json.dump(parsed, f, indent=2)
                    st.success("File saved successfully!")
                    # Clear cache so load_all_json() will re-read on next run
                    st.cache_data.clear()
                    # Prompt user to manually refresh
                    st.info("Please refresh your browser to see the updated data.")
                except Exception as e:
                    st.error(f"Error saving file: {e}")

if __name__ == '__main__':
    main()
