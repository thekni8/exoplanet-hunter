import streamlit as st
import numpy as np
import pandas as pd
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares
import astropy.units as u
import matplotlib.pyplot as plt
import gc
import os
import shutil

st.set_page_config(page_title="Exoplanet Hunter Studio", layout="wide", initial_sidebar_state="expanded")

# --- UI Styling ---
st.markdown("""
<style>
    .metric-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🪐 Autonomous Exoplanet Detection Studio")
st.caption("Direct MAST query • Box Least Squares • Multi-stage stellar diagnostic plots")

# --- Sidebar Controls ---
st.sidebar.header("🎯 Target & Survey Parameters")
target_input = st.sidebar.text_input("Target TIC ID:", value="322307342", help="Enter TIC ID without the 'TIC' prefix")
star_radius = st.sidebar.number_input("Stellar Radius ($R_\\odot$):", min_value=0.1, max_value=10.0, value=1.20, step=0.05)

st.sidebar.subheader("BLS Grid Settings")
min_period = st.sidebar.slider("Min Period (days)", 0.5, 5.0, 1.0)
max_period = st.sidebar.slider("Max Period (days)", 5.0, 30.0, 10.0)
max_sectors = st.sidebar.slider("Max Sectors to Download", 1, 3, 1, help="Keep at 1-2 to prevent memory crashes on Streamlit Cloud")

run_analysis = st.sidebar.button("🚀 Analyze Light Curve", type="primary", use_container_width=True)

# --- Main Pipeline ---
if run_analysis:
    # Clear any corrupt cache from previous downloads
    cache_dir = os.path.expanduser("~/.cache/lightkurve/mastDownload")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)

    progress_bar = st.progress(0, text="Querying NASA MAST catalog...")
    
    try:
        # 1. Search & Filter
        search = lk.search_lightcurve(f"TIC {target_input}", author=["SPOC", "TESS-SPOC", "QLP"])
        if len(search) == 0:
            search = lk.search_lightcurve(f"TIC {target_input}")
            
        if len(search) == 0:
            st.error(f"No light curves found for TIC {target_input}.")
            st.stop()

        progress_bar.progress(25, text=f"Downloading {min(len(search), max_sectors)} observation sector(s)...")
        
        # Download capped sectors to stay safely within RAM limits
        lc_collection = search[:max_sectors].download_all()
        if not lc_collection:
            st.error("Failed to download light curve data products.")
            st.stop()
            
        # 2. Stitch, Clean, & Flatten
        progress_bar.progress(50, text="Stitching and flattening stellar variability...")
        lc_raw = lc_collection.stitch().remove_nans().remove_outliers(sigma=5.0)
        lc_flat, trend = lc_raw.flatten(window_length=71, return_trend=True)

        t = lc_flat.time.value
        f = lc_flat.flux.value

        # 3. Box Least Squares (BLS) Search
        progress_bar.progress(75, text="Running Box Least Squares periodogram...")
        durations = np.linspace(0.04, 0.18, 8) * u.day
        periods = np.linspace(min_period, max_period, 6000) * u.day
        
        bls = BoxLeastSquares(t * u.day, f)
        res = bls.power(periods, durations)

        best_idx = np.argmax(res.power)
        best_period = float(res.period[best_idx].value)
        best_depth = float(res.depth[best_idx])
        best_duration = float(res.duration[best_idx].value)
        sde = (res.power[best_idx] - np.median(res.power)) / (np.std(res.power) + 1e-12)
        
        # Physical estimation
        planet_radius_earth = np.sqrt(max(0.0, best_depth)) * star_radius * 109.1

        progress_bar.progress(100, text="Complete!")
        progress_bar.empty()

        # --- Diagnostics Dashboard ---
        st.subheader("📊 Candidate Telemetry")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Orbital Period", f"{best_period:.4f} d")
        c2.metric("Signal Detection Eff. (SDE)", f"{sde:.1f}", delta="Strong Signal" if sde >= 8.0 else "Weak/Noise")
        c3.metric("Transit Depth", f"{best_depth * 100:.3f}%")
        c4.metric("Est. Planet Size", f"{planet_radius_earth:.2f} R⊕")

        st.divider()

        # --- Plot 1: Raw vs Trend Light Curve ---
        st.markdown("#### 1. Raw Photometry & Detrending Baseline")
        fig1, ax1 = plt.subplots(figsize=(12, 3.5))
        ax1.scatter(lc_raw.time.value, lc_raw.flux.value, s=1, color="#7f8c8d", alpha=0.5, label="Raw Cadence Flux")
        ax1.plot(trend.time.value, trend.flux.value, color="#e74c3c", lw=1.5, label="Savitzky-Golay Stellar Trend")
        ax1.set_xlabel("Time - 2457000 [BTJD Days]")
        ax1.set_ylabel("Normalized Flux")
        ax1.legend(loc="upper right", framealpha=0.8)
        ax1.grid(alpha=0.2)
        st.pyplot(fig1)
        plt.close(fig1)

        # --- Plot 2: Detrended / Flattened Light Curve ---
        st.markdown("#### 2. Flattened Light Curve (Normalized Residuals)")
        fig2, ax2 = plt.subplots(figsize=(12, 3.5))
        ax2.scatter(t, f, s=1, color="#2980b9", alpha=0.6, label="Flattened Flux")
        ax2.axhline(1.0, color="#c0392b", linestyle="--", lw=1)
        ax2.set_xlabel("Time - 2457000 [BTJD Days]")
        ax2.set_ylabel("Relative Flux")
        ax2.grid(alpha=0.2)
        st.pyplot(fig2)
        plt.close(fig2)

        # --- Plot 3: BLS Periodogram ---
        st.markdown("#### 3. Box Least Squares (BLS) Power Spectrum")
        fig3, ax3 = plt.subplots(figsize=(12, 3.5))
        ax3.plot(res.period.value, res.power, color="#2ecc71", lw=1.2)
        ax3.axvline(best_period, color="#e74c3c", linestyle="--", lw=1.5, label=f"Peak Period: {best_period:.4f} d (SDE: {sde:.1f})")
        ax3.set_xlabel("Period [Days]")
        ax3.set_ylabel("Spectral Power")
        ax3.legend(loc="upper right", framealpha=0.8)
        ax3.grid(alpha=0.2)
        st.pyplot(fig3)
        plt.close(fig3)

        # --- Plot 4: Zoomed Phase-Folded Transit Profile ---
        st.markdown("#### 4. Phase-Folded Transit Profile (Zoomed on Ingress/Egress)")
        
        # Calculate Phase centered on 0
        t0 = float(res.transit_time[best_idx].value)
        phase = ((t - t0 + 0.5 * best_period) % best_period) - 0.5 * best_period
        
        # Convert phase window to hours
        phase_hours = phase * 24.0
        
        # Zoom window: 3 times the transit duration (converted to hours)
        zoom_window_hr = max(6.0, (best_duration * 24.0) * 3)

        # Binning for the classic published discovery curve
        df_fold = pd.DataFrame({"phase_hr": phase_hours, "flux": f})
        df_fold = df_fold[(df_fold["phase_hr"] >= -zoom_window_hr) & (df_fold["phase_hr"] <= zoom_window_hr)]
        df_fold["bin"] = pd.cut(df_fold["phase_hr"], bins=60)
        binned = df_fold.groupby("bin", observed=True).agg({"phase_hr": "mean", "flux": ["mean", "sem"]}).dropna()

        fig4, ax4 = plt.subplots(figsize=(12, 4.5))
        # Raw points
        ax4.scatter(df_fold["phase_hr"], df_fold["flux"], s=3, color="#95a5a6", alpha=0.35, label="Individual Observations")
        # Binned points
        ax4.errorbar(
            binned["phase_hr"]["mean"], 
            binned["flux"]["mean"], 
            yerr=binned["flux"]["sem"], 
            fmt="o", 
            color="#e74c3c", 
            markersize=5, 
            capsize=2, 
            label="Phase-Binned Average"
        )
        
        ax4.set_xlim(-zoom_window_hr, zoom_window_hr)
        ax4.set_title(f"TIC {target_input} — Folded at P = {best_period:.4f} days")
        ax4.set_xlabel("Hours from Mid-Transit")
        ax4.set_ylabel("Normalized Flux")
        ax4.legend(loc="lower right", framealpha=0.8)
        ax4.grid(alpha=0.3)
        st.pyplot(fig4)
        plt.close(fig4)

        # Free memory cleanly
        del lc_collection, lc_raw, lc_flat, trend, bls, res, t, f
        gc.collect()

    except Exception as e:
        st.error(f"Analysis Pipeline Error: {e}")
