# app.py
import streamlit as st
import pandas as pd
import glob, os
from datetime import datetime
import altair as alt

# Cache loading of all TB files
@st.cache_data
def load_all_data():
    """Load and sort all TB CSV files by date from the data folder."""
    files = glob.glob(os.path.join('data', 'tb_data_*.csv'))
    def extract_date(fp):
        name = os.path.basename(fp)
        date_str = name.replace('tb_data_', '').replace('.csv', '')
        return datetime.strptime(date_str, '%d%m%y')
    sorted_files = sorted(files, key=extract_date)
    dfs = [pd.read_csv(fp) for fp in sorted_files]
    dates = [extract_date(fp) for fp in sorted_files]
    return dates, dfs

@st.cache_data
def load_latest_data(dates, dfs):
    """Return the latest TB DataFrame."""
    return dfs[-1]

# Main function
def main():
    # Page config
    st.set_page_config(page_title="SWGOH", page_icon="🔥", layout="wide")
    st.title("TB Data Dashboard")

    # Load all run data
    dates, dfs = load_all_data()
    num_runs = st.sidebar.number_input(
        "Number of TB runs to include", min_value=1,
        max_value=len(dfs), value=5, step=1
    )

    # Sidebar: select phases for sums
    st.sidebar.header("Phase Selection for Sums")
    phase_options = list(range(1, 7))  # Phases 1 through 6
    selected_phases = st.sidebar.multiselect(
        "Phases to include in Waves and Attempts sums",
        phase_options, default=phase_options
    )

    # Determine last runs
    last_dates = dates[-num_runs:]
    last_dfs = dfs[-num_runs:]

    # Latest run for summary
    df_latest = load_latest_data(dates, dfs)

    # Compute dynamic Waves and Attempts sums based on selected phases
    wave_cols = [f'P{p} Waves' for p in selected_phases if f'P{p} Waves' in df_latest.columns]
    attempt_cols = [f'P{p} Combat Attempts' for p in selected_phases if f'P{p} Combat Attempts' in df_latest.columns]
    df_latest['Combat Waves Sum'] = df_latest[wave_cols].sum(axis=1)
    df_latest['Combat Attempts Sum'] = df_latest[attempt_cols].sum(axis=1)

    # Compute sum of special attempts
    special_cols = [c for c in df_latest.columns if 'Special Attempts' in c]
    df_latest['Special Attempts Sum'] = df_latest[special_cols].sum(axis=1)

    # Summary table uses dynamic sums
    summary_table = df_latest[[
        'Name', 'Total Territory Points', 'Platoon Units',
        'Combat Waves Sum', 'Combat Attempts Sum',
        'Rogue Actions', 'Special Attempts Sum'
    ]]

    # Sort summary by Total Territory Points descending
    summary_table = summary_table.sort_values('Total Territory Points', ascending=False)

    # Apply default formatting for numeric fields
    fmt = {
        'Total Territory Points': '{:,.0f}',
        'Platoon Units': '{:,.0f}',
        'Combat Waves Sum': '{:,.0f}',
        'Combat Attempts Sum': '{:,.0f}',
        'Rogue Actions': '{:,.0f}',
        'Special Attempts Sum': '{:,.0f}'
    }
    styled_summary = summary_table.style.format(fmt)

    # Tabs
    tab_overall, tab_history = st.tabs(["Overall", "Player History"])

    with tab_overall:
        st.header("Player Summary Table (Latest TB)")
        st.dataframe(styled_summary,hide_index=True)

        # Detailed view
        selected_player = st.selectbox(
            "Select a player for detailed stats",
            sorted(summary_table['Name'].tolist())
        )
        if selected_player:
            player_row = df_latest[df_latest['Name'] == selected_player]
            st.subheader("Select fields to display")
            available = player_row.columns.tolist()
            defaults = [
                'Name', 'Total Territory Points', 'Platoon Units',
                'Combat Waves Sum', 'Combat Attempts Sum',
                'Rogue Actions', 'Special Attempts Sum'
            ]
            fields = st.multiselect(
                "Fields", options=available,
                default=[f for f in defaults if f in available]
            )
            st.subheader(f"Detailed Stats: {selected_player}")
            if fields:
                detail_df = player_row[fields]
                # Apply formatting to numeric columns
                detail_fmt = {col: fmt[col] for col in fields if col in fmt}
                st.dataframe(detail_df.style.format(detail_fmt),hide_index=True)
            else:
                st.warning("Select at least one field.")

    with tab_history:
        st.header(f"Player History over last {num_runs} TBs")
        # Multi-select players
        players_sorted = sorted(df_latest['Name'].tolist())
        selected_players = st.multiselect(
            "Select players for history", players_sorted
        )
        st.subheader("Select metric(s) to chart")
        metrics = st.multiselect(
            "Metrics", options=summary_table.columns.tolist(),
            default=['Combat Waves Sum', 'Combat Attempts Sum']
        )
        if selected_players and metrics:
            history_records = []
            for date, hist_df in zip(last_dates, last_dfs):
                # Dynamic sums per historical run
                wc = [f'P{p} Waves' for p in selected_phases if f'P{p} Waves' in hist_df.columns]
                ac = [f'P{p} Combat Attempts' for p in selected_phases if f'P{p} Combat Attempts' in hist_df.columns]
                hist_df['Combat Waves Sum'] = hist_df[wc].sum(axis=1)
                hist_df['Combat Attempts Sum'] = hist_df[ac].sum(axis=1)
                hist_df['Special Attempts Sum'] = hist_df[
                    [c for c in hist_df.columns if 'Special Attempts' in c]
                ].sum(axis=1)
                for player in selected_players:
                    row = hist_df[hist_df['Name'] == player]
                    if not row.empty:
                        for metric in metrics:
                            history_records.append({
                                'Date': date,
                                'Player': player,
                                'Metric': metric,
                                'Value': row.iloc[0][metric]
                            })
            history_df = pd.DataFrame(history_records)
            history_df = history_df.sort_values('Date')

            # Chart with Altair
            chart = alt.Chart(history_df).mark_line(point=True).encode(
                x=alt.X('Date:T', title='Start Date', axis=alt.Axis(format='%d-%m-%y')),
                y=alt.Y('Value:Q', title='Metric Value'),
                color=alt.Color('Player:N', title='Player'),
                strokeDash=alt.StrokeDash('Metric:N', title='Metric')
            ).properties(width=700, height=400)
            st.altair_chart(chart)

            # Display table
            display_df = history_df.copy()
            display_df['Date'] = display_df['Date'].dt.strftime('%d-%m-%y')
            # Format numeric columns for display table
            disp_fmt = {'Value': '{:,.0f}'}
            st.dataframe(display_df.style.format({**{'Date': '{}'}, **disp_fmt}),hide_index=True)
        else:
            st.info("Select at least one player and one metric.")

# Legacy single-file loader (unused)

def load_data():
    return pd.read_csv('data/tb_data_070725.csv')

if __name__ == "__main__":
    main()
