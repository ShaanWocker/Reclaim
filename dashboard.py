"""
Streamlit dashboard for Reclaim: explore and clean up your Gmail and
Drive storage, and see your real Google account quota.

Run: streamlit run dashboard.py
(Run gmail_fetch_data.py and drive_fetch_data.py first to generate data)
"""

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from drive_actions import empty_trash, trash_files
from drive_actions import get_service as get_drive_service
from export import build_powerbi_workbook
from gmail_actions import get_service as get_gmail_service
from gmail_actions import trash_messages
from subscriptions import summarize_senders, unsubscribe_one_click

ACCENT = "#0F6B5C"
ACCENT_SOFT = "#CDE8E2"

st.set_page_config(page_title="Reclaim", page_icon="📦", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
                '&family=Space+Grotesk:wght@600;700&display=swap');

    html, body, .stApp { font-family: 'Inter', sans-serif; }

    /* Breathing room: main content area */
    .block-container {
        padding-top: 2.75rem !important;
        padding-left: 3.5rem !important;
        padding-right: 3.5rem !important;
        padding-bottom: 3rem !important;
    }

    /* Widen the sidebar so the extra padding below doesn't clip widgets */
    [data-testid="stSidebar"] {
        min-width: 340px !important;
        max-width: 340px !important;
    }

    /* Breathing room: sidebar, especially around the filters */
    [data-testid="stSidebarUserContent"] {
        padding: 2.75rem 2.25rem 2rem 2.25rem !important;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"] {
        margin-bottom: 0.5rem;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stWidgetLabel"] {
        font-weight: 500;
        margin-top: 0.4rem;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stHeading"] {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        font-size: 1.3rem;
        margin-bottom: 1.5rem;
    }

    .reclaim-title {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        font-size: 2.5rem;
        letter-spacing: -0.02em;
        margin-bottom: 0.15rem;
    }
    .reclaim-subtitle { color: #667066; font-size: 0.98rem; margin-bottom: 1.25rem; }
    .reclaim-meter-track {
        width: 100%; height: 14px; background: #E3E6E1;
        border-radius: 999px; overflow: hidden; margin-bottom: 0.5rem;
        box-shadow: inset 0 1px 2px rgba(28,32,29,0.08);
    }
    .reclaim-meter-fill {
        height: 100%; background: linear-gradient(90deg, #0F6B5C, #14A085);
        border-radius: 999px;
    }
    .reclaim-meter-caption { color: #667066; font-size: 0.85rem; margin-bottom: 1.75rem; }

    /* Custom KPI cards -- full control over shadow/spacing/accent,
       since Streamlit's native bordered containers can't be reliably
       restyled across versions. */
    .reclaim-kpi-row {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1.1rem;
        margin-bottom: 2rem;
    }
    .reclaim-kpi-card {
        background: #FFFFFF;
        border: 1px solid #E3E6E1;
        border-left: 3px solid #0F6B5C;
        border-radius: 10px;
        padding: 1.35rem 1.5rem;
        box-shadow: 0 1px 2px rgba(28,32,29,0.04), 0 6px 16px rgba(15,107,92,0.07);
    }
    .reclaim-kpi-label {
        font-size: 0.82rem;
        color: #667066;
        margin-bottom: 0.4rem;
    }
    .reclaim-kpi-value {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        font-size: 1.8rem;
        color: #1C201D;
        letter-spacing: -0.01em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    df = pd.read_csv("messages.csv")
except FileNotFoundError:
    st.error("messages.csv not found. Run `python gmail_fetch_data.py` first.")
    st.stop()

df["size_mb"] = df["size_bytes"] / (1024 * 1024)
df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

try:
    with open("quota.json") as f:
        quota = json.load(f)
except FileNotFoundError:
    quota = None

# ---------- Sidebar filters (apply to the Gmail tabs) ----------
st.sidebar.header("🔎 Gmail filters")

valid_dates = df["date_parsed"].dropna()
date_range = None
if not valid_dates.empty:
    min_date, max_date = valid_dates.min().date(), valid_dates.max().date()
    date_range = st.sidebar.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

max_size = float(max(df["size_mb"].max(), 1.0))
min_size_mb = st.sidebar.slider("Minimum email size (MB)", 0.0, max_size, 0.0, step=0.5)

sender_search = st.sidebar.text_input("Sender contains")

filtered = df
if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[filtered["date_parsed"].dt.date.between(start, end)]
if min_size_mb > 0:
    filtered = filtered[filtered["size_mb"] >= min_size_mb]
if sender_search:
    filtered = filtered[filtered["from"].str.contains(sender_search, case=False, na=False)]

st.sidebar.caption(f"{len(filtered):,} of {len(df):,} messages match")
if st.sidebar.button("Reset filters"):
    st.rerun()

# ---------- Signature header: the real account quota if we have it ----------
# (Drive's about.get is the only endpoint that knows this -- until
# drive_fetch_data.py has been run once, fall back to the honestly
# scoped "scanned mail" framing instead of guessing.)
if quota and quota.get("limit"):
    limit_gb = quota["limit"] / (1024**3)
    usage_gb = quota["usage"] / (1024**3)
    drive_gb = quota["usage_in_drive"] / (1024**3)
    other_gb = max(usage_gb - drive_gb, 0)
    pct = quota["usage"] / quota["limit"] * 100

    st.markdown('<div class="reclaim-title">📦 Reclaim</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="reclaim-subtitle">Your real Google account storage '
        f'&middot; {usage_gb:,.1f} GB of {limit_gb:,.1f} GB used</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="reclaim-meter-track"><div class="reclaim-meter-fill" '
        f'style="width:{min(pct, 100):.1f}%"></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="reclaim-meter-caption">{pct:.0f}% used &mdash; '
        f'{drive_gb:,.2f} GB in Drive, {other_gb:,.2f} GB in Gmail + Photos '
        f'combined (no separate breakdown available for those two)</div>',
        unsafe_allow_html=True,
    )
elif quota:
    usage_gb = quota["usage"] / (1024**3)
    st.markdown('<div class="reclaim-title">📦 Reclaim</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="reclaim-subtitle">Your Google account storage &middot; '
        f'{usage_gb:,.1f} GB used on an unlimited plan</div>',
        unsafe_allow_html=True,
    )
else:
    total_mb_all = df["size_mb"].sum()
    total_mb_filtered = filtered["size_mb"].sum()
    pct = (total_mb_filtered / total_mb_all * 100) if total_mb_all else 0

    st.markdown('<div class="reclaim-title">📦 Reclaim</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="reclaim-subtitle">{len(df):,} messages scanned &middot; '
        f'{total_mb_all:,.0f} MB total</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="reclaim-meter-track"><div class="reclaim-meter-fill" '
        f'style="width:{pct:.1f}%"></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="reclaim-meter-caption">{len(filtered):,} messages match '
        f'your filters &mdash; {total_mb_filtered:,.0f} MB ({pct:.0f}% of '
        f'scanned mail). Run <code>drive_fetch_data.py</code> to see your '
        f"real account quota here instead.</div>",
        unsafe_allow_html=True,
    )

total_mb_filtered = filtered["size_mb"].sum()
avg_mb = total_mb_filtered / len(filtered) if len(filtered) else 0

st.markdown(
    f"""
    <div class="reclaim-kpi-row">
        <div class="reclaim-kpi-card">
            <div class="reclaim-kpi-label">Messages shown</div>
            <div class="reclaim-kpi-value">{len(filtered):,}</div>
        </div>
        <div class="reclaim-kpi-card">
            <div class="reclaim-kpi-label">Size shown</div>
            <div class="reclaim-kpi-value">{total_mb_filtered:,.0f} MB</div>
        </div>
        <div class="reclaim-kpi-card">
            <div class="reclaim-kpi-label">Senders shown</div>
            <div class="reclaim-kpi-value">{filtered['from'].nunique():,}</div>
        </div>
        <div class="reclaim-kpi-card">
            <div class="reclaim-kpi-label">Avg. size / email</div>
            <div class="reclaim-kpi-value">{avg_mb:.2f} MB</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_overview, tab_cleanup, tab_subscriptions, tab_drive, tab_export = st.tabs(
    ["📊 Overview", "🧹 Cleanup", "📭 Subscriptions", "💾 Drive", "📤 Export"]
)

with tab_overview:
    st.subheader("Senders by total size")
    st.caption("Scroll inside the chart to see every sender, not just the top few.")

    by_sender = (
        filtered.groupby("from")
        .agg(total_mb=("size_mb", "sum"), count=("id", "count"))
        .sort_values("total_mb", ascending=True)  # ascending: Plotly draws biggest at the top
    )

    if by_sender.empty:
        st.info("No messages match the current filters.")
    else:
        chart_height = max(400, 28 * len(by_sender))
        fig = px.bar(
            by_sender,
            x="total_mb",
            y=by_sender.index,
            orientation="h",
            labels={"total_mb": "Total size (MB)", "y": ""},
            hover_data={"count": True},
            color="total_mb",
            color_continuous_scale=[ACCENT_SOFT, ACCENT],
        )
        fig.update_layout(
            height=chart_height,
            margin=dict(l=10, r=10, t=10, b=10),
            coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif"),
        )
        fig.update_yaxes(title_text="")
        with st.container(height=500, border=True):
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            by_sender.sort_values("total_mb", ascending=False).style.format({"total_mb": "{:.1f}"}),
            use_container_width=True,
            height=300,
        )

    st.subheader("Largest individual emails")
    largest = filtered.sort_values("size_mb", ascending=False)
    st.dataframe(
        largest[["from", "date", "size_mb"]].style.format({"size_mb": "{:.1f}"}),
        use_container_width=True,
        height=400,
    )

with tab_cleanup:
    st.caption(
        "Moves matching messages to Trash -- reversible for 30 days, not a "
        "permanent delete. Both actions below respect the sidebar filters."
    )

    st.subheader("Trash by sender")
    sender_totals = (
        filtered.groupby("from")
        .agg(total_mb=("size_mb", "sum"), count=("id", "count"))
        .sort_values("total_mb", ascending=False)
    )

    if sender_totals.empty:
        st.info("No senders match the current filters.")
    else:
        choice = st.selectbox(
            "Sender",
            options=sender_totals.index,
            format_func=lambda s: (
                f"{s}  ({sender_totals.loc[s, 'count']} emails, "
                f"{sender_totals.loc[s, 'total_mb']:.1f} MB)"
            ),
        )
        matching_ids = filtered.loc[filtered["from"] == choice, "id"].tolist()
        st.write(
            f"{len(matching_ids)} messages from this sender, "
            f"{sender_totals.loc[choice, 'total_mb']:.1f} MB total."
        )
        if st.button(f"🗑️ Trash all {len(matching_ids)} messages from this sender", type="primary"):
            with st.spinner("Trashing messages..."):
                trashed = trash_messages(matching_ids, service=get_gmail_service())
            st.success(f"Moved {trashed} messages to Trash.")
            st.info("Re-run gmail_fetch_data.py to refresh the numbers above.")

    st.divider()
    st.subheader("Trash everything matching the current filters")
    st.write(
        f"This would trash **{len(filtered):,} messages** "
        f"(**{filtered['size_mb'].sum():,.1f} MB**) across "
        f"**{filtered['from'].nunique():,} senders** -- everything shown "
        "above, not just one sender. Use the sidebar to narrow this down first."
    )
    confirm = st.checkbox("I understand this will bulk-trash all filtered messages")
    if st.button("🗑️ Trash all filtered messages", disabled=not confirm or filtered.empty):
        ids_to_trash = filtered["id"].tolist()
        with st.spinner(f"Trashing {len(ids_to_trash)} messages..."):
            trashed = trash_messages(ids_to_trash, service=get_gmail_service())
        st.success(f"Moved {trashed} messages to Trash.")
        st.info("Re-run gmail_fetch_data.py to refresh the numbers above.")

with tab_subscriptions:
    st.caption(
        "Detected from the List-Unsubscribe headers (RFC 2369/8058) already "
        "present in your mail -- nothing here is guessed or scraped. "
        "One-click senders can be unsubscribed directly; others open a link "
        "or show an email address for you to action yourself."
    )

    if "list_unsubscribe" not in filtered.columns:
        st.warning(
            "No unsubscribe data found in messages.csv yet. Run "
            "`python gmail_fetch_data.py` again -- this is a one-time refetch "
            "to pick up the new fields."
        )
    else:
        sub_df = summarize_senders(filtered)
        sub_df = sub_df[sub_df["method"] != "none"].sort_values("count", ascending=False)

        if sub_df.empty:
            st.info("No senders with a detectable unsubscribe method match the current filters.")
        else:
            st.write(f"**{len(sub_df):,} senders** with a detectable unsubscribe option.")
            st.write("")

            method_labels = {
                "one_click": "🟢 One-click",
                "link": "🔵 Manual link",
                "mailto": "✉️ Email required",
            }

            for _, row in sub_df.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{row['from']}**")
                        st.caption(
                            f"{row['count']} emails &middot; {row['total_mb']:.1f} MB "
                            f"&middot; {method_labels[row['method']]}",
                            unsafe_allow_html=True,
                        )
                    with c2:
                        if row["method"] == "one_click":
                            if st.button("Unsubscribe", key=f"unsub_{row['from']}", type="primary"):
                                with st.spinner("Sending unsubscribe request..."):
                                    ok, detail = unsubscribe_one_click(row["https_url"])
                                if ok:
                                    st.success(f"Done ({detail})")
                                else:
                                    st.error(f"Failed ({detail}) -- try the link instead")
                                    st.link_button("Open link instead", row["https_url"])
                        elif row["method"] == "link":
                            st.link_button("Open unsubscribe link", row["https_url"])
                        elif row["method"] == "mailto":
                            st.link_button("Send unsubscribe email", f"mailto:{row['mailto']}")

                        if st.button(
                            f"🗑️ Also trash {row['count']} existing",
                            key=f"trash_{row['from']}",
                        ):
                            ids = filtered.loc[filtered["from"] == row["from"], "id"].tolist()
                            with st.spinner("Trashing..."):
                                trashed = trash_messages(ids, service=get_gmail_service())
                            st.success(f"Moved {trashed} messages to Trash.")

with tab_drive:
    try:
        drive_df = pd.read_csv("drive_files.csv")
    except FileNotFoundError:
        drive_df = None

    if drive_df is None:
        st.info(
            "No Drive data yet. Run `python drive_fetch_data.py` to scan your "
            "Drive -- it also fetches the real account quota bar shown at the "
            "top of this page."
        )
    else:
        drive_df["size_mb"] = drive_df["size_bytes"] / (1024 * 1024)

        def _categorize(mime_type):
            if not isinstance(mime_type, str):
                return "Other"
            if mime_type.startswith("image/"):
                return "Images"
            if mime_type.startswith("video/"):
                return "Videos"
            if mime_type == "application/pdf":
                return "PDFs"
            if mime_type.startswith("audio/"):
                return "Audio"
            if mime_type in (
                "application/zip",
                "application/x-zip-compressed",
                "application/x-rar-compressed",
                "application/x-7z-compressed",
                "application/gzip",
            ):
                return "Archives"
            if "wordprocessingml" in mime_type or mime_type == "application/msword":
                return "Word documents"
            if "spreadsheetml" in mime_type or mime_type == "application/vnd.ms-excel":
                return "Spreadsheets"
            if "presentationml" in mime_type or mime_type == "application/vnd.ms-powerpoint":
                return "Presentations"
            return "Other"

        drive_df["category"] = drive_df["mime_type"].apply(_categorize)

        if quota and quota.get("usage_in_drive_trash", 0) > 0:
            trash_mb = quota["usage_in_drive_trash"] / (1024 * 1024)
            with st.container(border=True):
                st.write(
                    f"🗑️ **{trash_mb:,.0f} MB** is already sitting in Drive's "
                    "Trash -- still counting against your quota until it's "
                    "permanently deleted or ages out after 30 days."
                )
                confirm_empty = st.checkbox(
                    "I understand this permanently deletes everything in Drive Trash"
                )
                if st.button("Empty Drive Trash now", disabled=not confirm_empty):
                    with st.spinner("Emptying trash..."):
                        empty_trash(service=get_drive_service())
                    st.success(
                        "Drive Trash emptied. Re-run drive_fetch_data.py to "
                        "refresh the quota bar above."
                    )

        st.subheader("Filters")
        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            name_search = st.text_input("File name contains", key="drive_name_search")
        with dc2:
            max_drive_size = float(max(drive_df["size_mb"].max(), 1.0))
            min_drive_size = st.slider(
                "Minimum file size (MB)", 0.0, max_drive_size, 0.0, step=1.0, key="drive_min_size"
            )
        with dc3:
            categories = ["All"] + sorted(drive_df["category"].unique().tolist())
            category_choice = st.selectbox("File type", categories, key="drive_category")

        drive_filtered = drive_df
        if name_search:
            drive_filtered = drive_filtered[
                drive_filtered["name"].str.contains(name_search, case=False, na=False)
            ]
        if min_drive_size > 0:
            drive_filtered = drive_filtered[drive_filtered["size_mb"] >= min_drive_size]
        if category_choice != "All":
            drive_filtered = drive_filtered[drive_filtered["category"] == category_choice]

        st.caption(f"{len(drive_filtered):,} of {len(drive_df):,} files match")

        st.subheader("Storage by file type")
        by_category = (
            drive_filtered.groupby("category")
            .agg(total_mb=("size_mb", "sum"), count=("id", "count"))
            .sort_values("total_mb", ascending=True)
        )
        if by_category.empty:
            st.info("No files match the current filters.")
        else:
            fig = px.bar(
                by_category,
                x="total_mb",
                y=by_category.index,
                orientation="h",
                labels={"total_mb": "Total size (MB)", "y": ""},
                hover_data={"count": True},
                color="total_mb",
                color_continuous_scale=[ACCENT_SOFT, ACCENT],
            )
            fig.update_layout(
                height=max(300, 40 * len(by_category)),
                margin=dict(l=10, r=10, t=10, b=10),
                coloraxis_showscale=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif"),
            )
            fig.update_yaxes(title_text="")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Largest files")
        largest_files = drive_filtered.sort_values("size_mb", ascending=False)
        st.dataframe(
            largest_files[["name", "category", "size_mb", "modified_time"]].style.format(
                {"size_mb": "{:.1f}"}
            ),
            use_container_width=True,
            height=350,
        )

        st.subheader("Trash a file")
        if drive_filtered.empty:
            st.info("No files match the current filters.")
        else:
            top_files = drive_filtered.sort_values("size_mb", ascending=False).head(200)
            file_options = top_files.set_index("id")[["name", "size_mb"]].to_dict("index")
            file_choice = st.selectbox(
                "File (largest 200 matching filters)",
                options=list(file_options.keys()),
                format_func=lambda fid: (
                    f"{file_options[fid]['name']} ({file_options[fid]['size_mb']:.1f} MB)"
                ),
                key="drive_file_choice",
            )
            if st.button("🗑️ Trash this file", key="drive_trash_one"):
                with st.spinner("Trashing..."):
                    trash_files([file_choice], service=get_drive_service())
                st.success("Moved to Trash.")
                st.info("Re-run drive_fetch_data.py to refresh the numbers above.")

        st.divider()
        st.subheader("Trash everything matching the current filters")
        st.write(
            f"This would trash **{len(drive_filtered):,} files** "
            f"(**{drive_filtered['size_mb'].sum():,.1f} MB**) -- everything "
            "shown above, not just one file."
        )
        confirm_bulk = st.checkbox(
            "I understand this will bulk-trash all filtered files", key="drive_bulk_confirm"
        )
        if st.button(
            "🗑️ Trash all filtered files",
            disabled=not confirm_bulk or drive_filtered.empty,
            key="drive_bulk_trash",
        ):
            ids_to_trash = drive_filtered["id"].tolist()
            with st.spinner(f"Trashing {len(ids_to_trash)} files..."):
                trashed = trash_files(ids_to_trash, service=get_drive_service())
            st.success(f"Moved {trashed} files to Trash.")
            st.info("Re-run drive_fetch_data.py to refresh the numbers above.")

with tab_export:
    st.subheader("Export to Power BI")
    st.caption(
        "Builds an .xlsx workbook with three named Excel Tables -- Messages, "
        "Senders, and Monthly totals -- so Power BI's Get Data > Excel "
        "Workbook picks up clean, typed columns automatically instead of "
        "guessing at a raw range. Respects the sidebar filters. Gmail data "
        "only for now."
    )
    st.write(f"Will include **{len(filtered):,} messages** matching your current filters.")

    if "xlsx_export" not in st.session_state:
        st.session_state.xlsx_export = None

    if st.button("Prepare workbook", disabled=filtered.empty):
        with st.spinner("Building workbook..."):
            st.session_state.xlsx_export = build_powerbi_workbook(filtered)

    if st.session_state.xlsx_export:
        st.download_button(
            "⬇️ Download reclaim_export.xlsx",
            data=st.session_state.xlsx_export,
            file_name="reclaim_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption(
            "In Power BI Desktop: Get Data > Excel Workbook > select this "
            "file > check MessagesTable, SendersTable, and MonthlyTable > Load."
        )
