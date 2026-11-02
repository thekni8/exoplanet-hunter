import streamlit as st
import pandas as pd
import lightkurve as lk
import numpy as np
import matplotlib.pyplot as plt
import os

st.set_page_config(page_title="Exoplanet Hunter Pipeline", layout="wide")
st.title("🔭 Autonomous Exoplanet Dashboard")
st.markdown("This dashboard reads live discoveries from the headless GitHub Actions engine.")

if not os.path.exists("hits.csv"):
    st.info("The automated engine is scanning in the background. No signals found yet! Check back after the next Cron run.")
else:
    df = pd.read_csv("hits.csv")
    
    st.success(f"🎯 The autonomous engine has found {len(df)} candidate signals!")
    st.dataframe(df, use_container_width=True)
    
    st.divider()
    st.markdown("### 🔍 Run QA Validation")
    
    selected_tic = st.selectbox("Select a flagged target to verify:", df["TIC_ID"].unique())
    target_data = df[df["TIC_ID"] == selected_tic].iloc[0]
    
    if st.button("Generate Transit Graph", type="primary"):
        with st.spinner(f"Pulling light curves for TIC {selected_tic}..."):
            try:
                search = lk.search_lightcurve(f"TIC {selected_tic}")
                lc_collection = search.download_all()
                lc = lc_collection.stitch().remove_nans().remove_outliers(sigma=5.0)
                lc_flat = lc.flatten(window_length=71)

                t = lc_flat.time.value
                f = lc_flat.flux.value
                P = target_data["Period"]
                
                phase_hr = (((t - np.min(t) + 0.5 * P) % P) - 0.5 * P) * 24.0
                
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.scatter(phase_hr, f * 100, s=2, alpha=0.5, color="gray", label="Raw Snapshots")
                ax.set_title(f"TIC {selected_tic} (Period: {P:.4f} days)")
                ax.set_xlabel("Hours From Transit Center")
                ax.set_ylabel("Brightness (%)")
                ax.grid(alpha=0.2)
                st.pyplot(fig)
                
            except Exception as e:
                st.error(f"Error generating graph: {e}")
