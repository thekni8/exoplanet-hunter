import streamlit as st
import numpy as np
import pandas as pd
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares
import astropy.units as u
from astroquery.mast import Catalogs
from astropy.coordinates import SkyCoord
import matplotlib.pyplot as plt
import io
import os
import shutil
import gc
import time

st.set_page_config(page_title="Exoplanet Hunter Studio", layout="wide", initial_sidebar_state="expanded")

# --- UI Styling ---
st.markdown("""
<style>
    .metric-card {
        background-color: #0e1117;
        border: 1px solid #262730;
        border-radius: 8px;
        padding: 12px;
    }
    .stButton>button {
        width: 100%;
        border-radius: 6px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Session State for routing between tabs
if "inspect_tic" not in st.session_state:
    st.session_state.inspect_tic = "322307342"
if "inspect_rad" not in st.session_state:
    st.session_state.inspect_rad = 1.20

def purge_cache():
    cache_dir = os.path.expanduser("~/.cache/lightkurve/mastDownload")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)

# --- Sidebar Global Mission Configuration ---
st.sidebar.title("🔭 Mission Control")
app_mode = st.sidebar.radio("Operational Mode", [
    "🔬 Diagnostic Observatory", 
    "🌌 Wide-Field Sky Sweeper", 
    "⚡ QA Benchmark Suite"
])

st.sidebar.divider()
st.sidebar.subheader("Observation Limits")
download_all_sectors = st.sidebar.checkbox("Download ALL Available Sectors", value=True, 
                                           help="Unbounded full-mission baseline. Uncheck if you want to cap sectors for faster iteration.")
sector_cap = 2
if not download_all_sectors:
    sector_cap = st.sidebar.slider("Sector Cap", 1, 10, 2)

catalogs_allowed = st.sidebar.multiselect(
    "Allowed Pipelines", 
    ["SPOC", "TESS-SPOC", "QLP"], 
    default=["SPOC", "TESS-SPOC", "QLP"]
)

st.sidebar.subheader("BLS Computational Grid")
bls_resolution = st.sidebar.select_slider(
    "Grid Frequency Points", 
    options=[5000, 10000, 25000, 50000], 
    value=25000,
    help="Higher resolution identifies narrow transit dips across multi-year baselines."
)
detrend_window = st.sidebar.slider("Detrending Window Length", 31, 201, 101, step=10, 
                                   help="Savitzky-Golay cadence window for filtering out stellar rotation and flares.")


# ==============================================================================
# TAB 1: DIAGNOSTIC OBSERVATORY (Full Multi-Sector 4-Panel Suite)
# ==============================================================================
if app_mode == "🔬 Diagnostic Observatory":
    st.title("🔬 Deep Diagnostic Observatory")
    st.caption("Ingests full multi-year baseline data across observation sectors without truncated grids.")

    t_col1, t_col2 = st.columns([2, 1])
    with t_col1:
        target_tic = st.text_input("Target TIC ID:", value=str(st.session_state.inspect_tic).strip())
    with t_col2:
        host_radius = st.number_input("Host Stellar Radius ($R_\\odot$):", value=float(st.session_state.inspect_rad), step=0.05)

    with st.expander("Orbital Period Exploration Window", expanded=False):
        c_min, c_max = st.columns(2)
        with c_min:
            p_min = st.number_input("Minimum Period (Days)", value=0.5, step=0.1, min_value=0.1)
        with c_max:
            p_max = st.number_input("Maximum Period (Days)", value=25.0, step=0.5, min_value=1.0)

    if st.button("🚀 Run Full-Mission Diagnostic Suite", type="primary"):
        purge_cache()
        status_box = st.empty()
        pbar = st.progress(0)
        
        status_box.info(f"Querying MAST for observation sectors of TIC {target_tic}...")
        pbar.progress(10)
        
        try:
            search = lk.search_lightcurve(f"TIC {target_tic}", author=catalogs_allowed)
            if len(search) == 0:
                search = lk.search_lightcurve(f"TIC {target_tic}")
                
            if len(search) == 0:
                st.error(f"No mission data found for TIC {target_tic}.")
                st.stop()

            sectors_to_fetch = search if download_all_sectors else search[:sector_cap]
            st.write(f"**Ingesting {len(sectors_to_fetch)} observation sector(s)** from NASA MAST...")
            pbar.progress(25)

            lc_collection = sectors_to_fetch.download_all()
            if not lc_collection or len(lc_collection) == 0:
                st.error("Failed to download light curve data products.")
                st.stop()

            pbar.progress(50)
            status_box.info(f"Stitching {len(lc_collection)} sectors into continuous mission baseline...")

            lc_raw = lc_collection.stitch(corrector_func=lambda x: x.normalize()).remove_nans().remove_outliers(sigma=5.0)
            total_points = len(lc_raw)
            
            status_box.info(f"Flattening stellar rotation across {total_points:,} cadence points...")
            pbar.progress(65)

            lc_flat, trend = lc_raw.flatten(window_length=detrend_window, return_trend=True)
            t = lc_flat.time.value
            f = lc_flat.flux.value

            status_box.info(f"Evaluating {bls_resolution:,} trial periods using Box Least Squares...")
            pbar.progress(80)

            periods = np.linspace(p_min, p_max, bls_resolution) * u.day
            durations = np.linspace(0.03, 0.25, 14) * u.day

            bls = BoxLeastSquares(t * u.day, f)
            res = bls.power(periods, durations)

            best_idx = np.argmax(res.power)
            best_period = float(res.period[best_idx].value)
            best_depth = float(res.depth[best_idx])
            best_duration = float(res.duration[best_idx].value)
            t0 = float(res.transit_time[best_idx].value)
            sde = (res.power[best_idx] - np.median(res.power)) / (np.std(res.power) + 1e-12)
            planet_radius_earth = np.sqrt(max(0.0, best_depth)) * host_radius * 109.1

            pbar.progress(100)
            status_box.success("Astrophysical analysis complete.")
            time.sleep(0.4)
            pbar.empty()
            status_box.empty()

            # --- Metrics Summary ---
            st.subheader("📊 Candidate Physical Telemetry")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Orbital Period", f"{best_period:.5f} d")
            m2.metric("Signal SDE", f"{sde:.1f}", delta="Strong Transit" if sde >= 8.5 else "Marginal / Noise")
            m3.metric("Transit Depth", f"{best_depth * 100:.4f}%")
            m4.metric("Est. Planet Size", f"{planet_radius_earth:.2f} R⊕")
            m5.metric("Data Baseline", f"{len(lc_collection)} Sectors")

            st.divider()

            # --- PLOT 1: Full-Mission Raw Photometry + Trend ---
            st.markdown("#### 1. Full Multi-Sector Raw Photometry & Stellar Trend")
            fig1, ax1 = plt.subplots(figsize=(14, 3.4))
            ax1.scatter(lc_raw.time.value, lc_raw.flux.value, s=0.5, color="#6c757d", alpha=0.35, label=f"Raw Flux ({total_points:,} pts)")
            ax1.plot(trend.time.value, trend.flux.value, color="#e63946", lw=1.2, label=f"Stellar Trend (window={detrend_window})")
            ax1.set_xlabel("Time - 2457000 [BTJD Days]")
            ax1.set_ylabel("Normalized Flux")
            ax1.legend(loc="upper right", framealpha=0.85, fontsize=8)
            ax1.grid(alpha=0.25)
            st.pyplot(fig1)

            # --- PLOT 2: Detrended Residuals ---
            st.markdown("#### 2. Flattened Light Curve (Normalized Residuals)")
            fig2, ax2 = plt.subplots(figsize=(14, 3.4))
            ax2.scatter(t, f, s=0.5, color="#1d3557", alpha=0.45, label="Flattened Cadence Residuals")
            ax2.axhline(1.0, color="#e63946", linestyle="--", lw=0.9)
            ax2.set_xlabel("Time - 2457000 [BTJD Days]")
            ax2.set_ylabel("Relative Flux")
            ax2.grid(alpha=0.25)
            st.pyplot(fig2)

            # --- PLOT 3: High-Density BLS Periodogram ---
            st.markdown(f"#### 3. Box Least Squares (BLS) Power Spectrum ({bls_resolution:,} Bins)")
            fig3, ax3 = plt.subplots(figsize=(14, 3.4))
            ax3.plot(res.period.value, res.power, color="#2a9d8f", lw=0.9)
            ax3.axvline(best_period, color="#e63946", linestyle="--", lw=1.2, label=f"Peak: {best_period:.5f} d | SDE: {sde:.1f}")
            ax3.set_xlabel("Trial Period [Days]")
            ax3.set_ylabel("Spectral Power")
            ax3.legend(loc="upper right", framealpha=0.85, fontsize=8)
            ax3.grid(alpha=0.25)
            st.pyplot(fig3)

            # --- PLOT 4: Zoomed Phase-Folded Transit Profile ---
            st.markdown("#### 4. Zoomed Phase-Folded Transit Profile (Ingress / Egress Detail)")
            phase = ((t - t0 + 0.5 * best_period) % best_period) - 0.5 * best_period
            phase_hours = phase * 24.0
            zoom_hr = max(6.0, (best_duration * 24.0) * 3.5)

            df_fold = pd.DataFrame({"phase_hr": phase_hours, "flux": f})
            df_fold = df_fold[(df_fold["phase_hr"] >= -zoom_hr) & (df_fold["phase_hr"] <= zoom_hr)]
            df_fold["bin"] = pd.cut(df_fold["phase_hr"], bins=65)
            binned = df_fold.groupby("bin", observed=True).agg({"phase_hr": "mean", "flux": ["mean", "sem"]}).dropna()

            fig4, ax4 = plt.subplots(figsize=(14, 4.5))
            ax4.scatter(df_fold["phase_hr"], df_fold["flux"], s=2.5, color="#8d99ae", alpha=0.3, label="Cadence Observations")
            ax4.errorbar(
                binned["phase_hr"]["mean"], 
                binned["flux"]["mean"], 
                yerr=binned["flux"]["sem"], 
                fmt="o", 
                color="#e63946", 
                markersize=4.5, 
                capsize=2, 
                label="Phase-Binned Means (±SEM)"
            )
            ax4.set_xlim(-zoom_hr, zoom_hr)
            ax4.set_title(f"TIC {target_tic} — Transit Fold (Period: {best_period:.5f} d | Depth: {best_depth * 100:.3f}%)", fontweight="bold")
            ax4.set_xlabel("Hours from Mid-Transit Center")
            ax4.set_ylabel("Relative Flux")
            ax4.legend(loc="lower right", framealpha=0.85, fontsize=8)
            ax4.grid(alpha=0.3)
            st.pyplot(fig4)

            # --- Composite High-Res Plate Downloader ---
            fig_master, axes = plt.subplots(4, 1, figsize=(14, 15), constrained_layout=True)
            axes[0].scatter(lc_raw.time.value, lc_raw.flux.value, s=0.5, color="#6c757d", alpha=0.3)
            axes[0].plot(trend.time.value, trend.flux.value, color="#e63946", lw=1.2)
            axes[0].set_title(f"TIC {target_tic} — Raw Baseline ({len(lc_collection)} Sectors)", fontweight="bold")
            axes[0].grid(alpha=0.2)

            axes[1].scatter(t, f, s=0.5, color="#1d3557", alpha=0.35)
            axes[1].axhline(1.0, color="#e63946", linestyle="--", lw=0.9)
            axes[1].set_title("Flattened Residuals", fontweight="bold")
            axes[1].grid(alpha=0.2)

            axes[2].plot(res.period.value, res.power, color="#2a9d8f", lw=0.9)
            axes[2].axvline(best_period, color="#e63946", linestyle="--", lw=1.2)
            axes[2].set_title(f"BLS Power Spectrum (P: {best_period:.5f} d | SDE: {sde:.1f})", fontweight="bold")
            axes[2].grid(alpha=0.2)

            axes[3].scatter(df_fold["phase_hr"], df_fold["flux"], s=2.0, color="#8d99ae", alpha=0.3)
            axes[3].errorbar(binned["phase_hr"]["mean"], binned["flux"]["mean"], yerr=binned["flux"]["sem"], fmt="o", color="#e63946", markersize=4, capsize=2)
            axes[3].set_xlim(-zoom_hr, zoom_hr)
            axes[3].set_title(f"Transit Phase Fold (Rp: {planet_radius_earth:.2f} R⊕)", fontweight="bold")
            axes[3].grid(alpha=0.2)

            buf = io.BytesIO()
            fig_master.savefig(buf, format="png", dpi=300)
            buf.seek(0)

            st.download_button(
                label="📥 Download 300 DPI Diagnostic Plate",
                data=buf,
                file_name=f"TIC_{target_tic}_diagnostic.png",
                mime="image/png"
            )

            plt.close(fig_master)
            plt.close(fig1)
            plt.close(fig2)
            plt.close(fig3)
            plt.close(fig4)

            del lc_collection, lc_raw, lc_flat, trend, bls, res, t, f, df_fold, binned
            gc.collect()

        except Exception as e:
            st.error(f"Analysis Pipeline Error: {e}")


# ==============================================================================
# TAB 2: WIDE-FIELD SKY SWEEPER (Cone Search Across Starfields)
# ==============================================================================
elif app_mode == "🌌 Wide-Field Sky Sweeper":
    st.title("🌌 Autonomous Wide-Field Sky Sweeper")
    st.caption("Point the array at deep-space coordinates. Screens stars through the TIC catalog and logs candidate planets.")

    c1, c2, c3 = st.columns(3)
    with c1:
        ra_val = st.number_input("Right Ascension (RA deg)", value=83.82, step=0.01, format="%.4f")
    with c2:
        dec_val = st.number_input("Declination (Dec deg)", value=-5.39, step=0.01, format="%.4f")
    with c3:
        search_rad = st.slider("Cone Radius (deg)", 0.05, 0.50, 0.15)

    st.subheader("Stellar Screening Filters")
    f1, f2, f3 = st.columns(3)
    with f1:
        mag_filter = st.slider("TESS Magnitude (Tmag)", 10.0, 16.0, (11.5, 15.0))
    with f2:
        rad_filter = st.slider("Host Star Radius ($R_\\odot$)", 0.4, 2.5, (0.6, 1.8))
    with f3:
        star_quota = st.slider("Max Stars to Evaluate", 3, 30, 8)

    if st.button("🛰️ Launch Autonomous Sky Sweep", type="primary"):
        purge_cache()
        st.write(f"Querying MAST catalog around RA: {ra_val}°, Dec: {dec_val}°...")
        
        try:
            coord = SkyCoord(ra=ra_val * u.deg, dec=dec_val * u.deg)
            tic_catalog = Catalogs.query_region(coord, radius=search_rad * u.deg, catalog="TIC")
            
            mask = (
                (tic_catalog["Tmag"] >= mag_filter[0]) & (tic_catalog["Tmag"] <= mag_filter[1]) &
                (tic_catalog["rad"] >= rad_filter[0]) & (tic_catalog["rad"] <= rad_filter[1])
            )
            screened_targets = tic_catalog[mask][:star_quota]
            
            if len(screened_targets) == 0:
                st.warning("No stars matched your screening criteria in this cone.")
            else:
                st.success(f"Locked onto {len(screened_targets)} optimal candidate hosts. Starting evaluation...")
                
                survey_log = []
                p_bar = st.progress(0)
                status = st.empty()

                for idx, row in enumerate(screened_targets):
                    tic_id = str(row["ID"])
                    star_r = float(row["rad"])
                    status.text(f"Evaluating target [{idx+1}/{len(screened_targets)}]: TIC {tic_id} (R* = {star_r:.2f} R☉)")

                    try:
                        search = lk.search_lightcurve(f"TIC {tic_id}", author=catalogs_allowed)
                        if len(search) == 0:
                            p_bar.progress((idx + 1) / len(screened_targets))
                            continue

                        sectors_to_pull = search if download_all_sectors else search[:sector_cap]
                        lc_coll = sectors_to_pull.download_all()
                        if not lc_coll:
                            p_bar.progress((idx + 1) / len(screened_targets))
                            continue

                        lc = lc_coll.stitch(corrector_func=lambda x: x.normalize()).remove_nans().remove_outliers(sigma=5.0)
                        lc_flat = lc.flatten(window_length=detrend_window)

                        t_s, f_s = lc_flat.time.value, lc_flat.flux.value
                        bls = BoxLeastSquares(t_s * u.day, f_s)
                        res = bls.power(np.linspace(0.5, 15.0, 8000) * u.day, np.linspace(0.03, 0.20, 8) * u.day)

                        b_idx = np.argmax(res.power)
                        sde = (res.power[b_idx] - np.median(res.power)) / (np.std(res.power) + 1e-12)
                        p_candidate = float(res.period[b_idx].value)
                        d_candidate = float(res.depth[b_idx])
                        r_planet = np.sqrt(max(0.0, d_candidate)) * star_r * 109.1

                        hit_entry = {
                            "TIC_ID": str(tic_id),
                            "Tmag": float(row["Tmag"]),
                            "Sectors_Analyzed": len(lc_coll),
                            "Star_Radius_Rsun": star_r,
                            "Period_Days": round(p_candidate, 4),
                            "SDE": round(sde, 2),
                            "Planet_Radius_Re": round(r_planet, 2),
                            "Classification": "Candidate Planet" if sde >= 8.5 else "Noise Floor"
                        }
                        survey_log.append(hit_entry)

                        del search, lc_coll, lc, lc_flat, bls, res, t_s, f_s
                        gc.collect()

                    except Exception:
                        pass
                    
                    p_bar.progress((idx + 1) / len(screened_targets))

                status.text("Survey finished.")
                df_survey = pd.DataFrame(survey_log)
                
                if not df_survey.empty:
                    st.dataframe(df_survey, use_container_width=True)
                    
                    # Direct route to Diagnostic tab
                    promising = df_survey[df_survey["SDE"] >= 7.5]
                    if not promising.empty:
                        st.subheader("🎯 Discovered Candidate Signals")
                        route_tic = st.selectbox("Select candidate to dispatch to Diagnostic Observatory:", promising["TIC_ID"].tolist())
                        if st.button("🔬 Route Target to Diagnostic Observatory"):
                            st.session_state.inspect_tic = route_tic
                            st.session_state.inspect_rad = float(df_survey[df_survey["TIC_ID"] == route_tic]["Star_Radius_Rsun"].iloc[0])
                            st.info(f"TIC {route_tic} locked into mission state. Switch tabs in sidebar to view full diagnostic suite.")
                else:
                    st.warning("No light curve data products available for targets in this region.")

        except Exception as e:
            st.error(f"Wide-field survey query failed: {e}")


# ==============================================================================
# TAB 3: QA BENCHMARK SUITE (Pre-configured Verified Standards)
# ==============================================================================
elif app_mode == "⚡ QA Benchmark Suite":
    st.title("⚡ Mission QA Benchmark Suite")
    st.caption("One-click pipeline validation against verified exoplanetary standards across their entire multi-year histories.")

    benchmarks = [
        {
            "name": "Pi Mensae c (TIC 261136679)", 
            "class": "Super-Earth", 
            "known_period": "6.27 days", 
            "size": "2.04 R⊕", 
            "star_rad": 1.14, 
            "id": "261136679",
            "desc": "Famous multi-sector target. Stitches dozens of sectors across years of observations."
        },
        {
            "name": "TOI-114 (TIC 322307342)", 
            "class": "Sub-Neptune", 
            "known_period": "3.59 days", 
            "size": "1.77 R⊕", 
            "star_rad": 1.20, 
            "id": "322307342",
            "desc": "Clean hot sub-Neptune transit inside the Fulton radius valley."
        },
        {
            "name": "WASP-126 b (TIC 25155310)", 
            "class": "Inflated Hot Saturn", 
            "known_period": "3.28 days", 
            "size": "10.7 R⊕", 
            "star_rad": 1.30, 
            "id": "25155310",
            "desc": "Deep, high-SNR Jovian transit signature ideal for quick sanity checks."
        }
    ]

    for b in benchmarks:
        with st.container():
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.subheader(b["name"])
                st.write(f"**Classification:** {b['class']} | **Standard Period:** {b['known_period']} | **Planet Radius:** {b['size']}")
                st.caption(b["desc"])
            with col_b:
                if st.button(f"Load TIC {b['id']}", key=b["id"]):
                    st.session_state.inspect_tic = b["id"]
                    st.session_state.inspect_rad = b["star_rad"]
                    st.success(f"TIC {b['id']} loaded. Navigate to Diagnostic Observatory to inspect.")
            st.divider()
