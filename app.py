import streamlit as st
import time
import requests
import numpy as np
import matplotlib.pyplot as plt
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.timeseries import BoxLeastSquares
from astroquery.mast import Catalogs
import lightkurve as lk
import warnings

warnings.filterwarnings('ignore')

st.set_page_config(page_title="Exoplanet Hunter", page_icon="🔭", layout="wide")
st.title("🔭 Automated Exoplanet Hunter")

# Create tabs for the workflow
tab1, tab2 = st.tabs(["Deep Space Scanner", "QA Validation Lab"])

def is_already_known_online(tic_id: int) -> bool:
    try:
        zooniverse_url = f"https://talk.zooniverse.org/searches?section=project-5733&query={tic_id}&types[]=comments&types[]=discussions"
        r = requests.get(zooniverse_url, headers={"Accept": "application/vnd.api+json; version=1"}, timeout=5)
        if r.status_code == 200 and len(r.json().get("searches", [])) > 0:
            return True
    except Exception:
        pass
    return False

with tab1:
    st.markdown("Scan raw NASA MAST data for unflagged exoplanetary transit signals.")
    
    # We added a 5th column here for the offset
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        ra_deg = st.number_input("RA (Degrees)", value=124.53, step=0.01)
    with col2:
        dec_deg = st.number_input("Dec (Degrees)", value=-67.57, step=0.01)
    with col3:
        radius_deg = st.slider("Search Radius", 0.01, 1.0, 0.10, step=0.01)
    with col4:
        max_stars = st.slider("Batch Size", 5, 50, 50, step=5)
    with col5:
        start_index = st.number_input("Start at Star #", value=0, step=50)
        
    if st.button("Initialize Scan", type="primary"):
        st.divider()
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
        
        try:
            with st.spinner("Connecting to NASA MAST Catalog..."):
                tic_table = Catalogs.query_region(coord, radius=radius_deg * u.deg, catalog="TIC")
                mask = ((tic_table["Tmag"] >= 13.5) & (tic_table["Tmag"] <= 15.4) & 
                        (tic_table["rad"] > 0.2) & (tic_table["rad"] < 1.5))
                candidates = tic_table[mask]
            
            # Slice the master list based on the user's Start Index
            total_stars = len(candidates)
            batch_candidates = candidates[start_index : start_index + max_stars]
            
            st.success(f"Found {total_stars} total stars in this sector. Processing batch of {len(batch_candidates)} (Stars {start_index} to {start_index + len(batch_candidates)})...")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            st.markdown("### 📡 Live Scan Log")
            log_box = st.container(height=300)
            
            checked_count = 0
            for row in batch_candidates:
                tic_id = int(row["ID"])
                star_rad = float(row["rad"])
                checked_count += 1
                progress_bar.progress(checked_count / len(batch_candidates))
                
                status_text.text(f"[{checked_count}/{len(batch_candidates)}] Actively querying TIC {tic_id}...")
                
                if is_already_known_online(tic_id):
                    log_box.write(f"⚠️ **TIC {tic_id}**: Already known on Zooniverse, skipping.")
                    continue
                
                try:
                    time.sleep(1)
                    search = lk.search_lightcurve(f"TIC {tic_id}")
                    if len(search) == 0:
                        log_box.write(f"⏩ **TIC {tic_id}**: No light curves available. Skipping.")
                        continue
                        
                    for preferred_author in ["TESS-SPOC", "QLP", "SPOC", "TGLC"]:
                        author_search = search[search.author == preferred_author]
                        if len(author_search) >= 2:
                            search = author_search
                            break
                            
                    if len(search) < 2:
                        log_box.write(f"⏩ **TIC {tic_id}**: Not enough data sectors. Skipping.")
                        continue

                    lc_collection = search.download_all()
                    if not lc_collection:
                        log_box.write(f"❌ **TIC {tic_id}**: Download failed. Skipping.")
                        continue
                        
                    lc = lc_collection.stitch().remove_nans().remove_outliers(sigma=5.0)
                    lc_flat = lc.flatten(window_length=71)

                    t = lc_flat.time.value
                    f = lc_flat.flux.value
                    bls = BoxLeastSquares(t * u.day, f)
                    res = bls.power(np.linspace(0.5, 15.0, 20000) * u.day, np.linspace(0.03, 0.20, 10) * u.day)

                    best = np.argmax(res.power)
                    sde = (res.power[best] - np.median(res.power)) / (np.std(res.power) + 1e-12)

                    if sde >= 11.0:
                        P = float(res.period[best].value)
                        T0 = float(res.transit_time[best].value)
                        dur_hr = float(res.duration[best].value) * 24.0
                        planet_re = np.sqrt(max(0.0, float(res.depth[best]))) * star_rad * 109.1

                        log_box.success(f"🎯 **TIC {tic_id}**: SIGNAL FOUND!")
                        st.error(f"🎯 **NEW UNFLAGGED SIGNAL: TIC {tic_id}** | Period: {P:.4f} days | Size: ~{planet_re:.1f} Earth Radii")

                        phase_hr = (((t - T0 + 0.5 * P) % P) - 0.5 * P) * 24.0
                        zoom = np.abs(phase_hr) <= (dur_hr * 3.0)
                        
                        fig, ax = plt.subplots(figsize=(8, 4))
                        ax.scatter(phase_hr[zoom], f[zoom] * 100, s=4, alpha=0.3, color="gray", label="Raw Snapshots")
                        
                        bins = np.linspace(-dur_hr * 2.8, dur_hr * 2.8, 35)
                        centers = 0.5 * (bins[:-1] + bins[1:])
                        binned = [np.median(f[zoom][(phase_hr[zoom] >= b0) & (phase_hr[zoom] < b1)]) * 100 for b0, b1 in zip(bins[:-1], bins[1:])]
                        
                        ax.plot(centers, binned, color="crimson", lw=2.5, label="Averaged Dip")
                        ax.set_title(f"TIC {tic_id} (Period: {P:.4f} days)")
                        ax.set_xlabel("Hours From Transit Center")
                        ax.set_ylabel("Brightness (%)")
                        ax.legend()
                        ax.grid(alpha=0.2)
                        st.pyplot(fig)
                    else:
                        log_box.write(f"✅ **TIC {tic_id}**: Scanned successfully. No signals.")
                        
                except Exception as e:
                    log_box.write(f"⚠️ **TIC {tic_id}**: Failed processing (Timeout/Error).")
                    continue
                    
            status_text.text("Scan complete!")
            st.balloons()
            
        except Exception as e:
            st.error(f"Error reaching MAST catalog: {e}")

with tab2:
    st.markdown("Run the Odd/Even half-period alias test to rule out Eclipsing Binary stars.")
    
    qa_col1, qa_col2 = st.columns(2)
    with qa_col1:
        qa_tic = st.number_input("Target TIC ID", value=307218289)
    with qa_col2:
        qa_period = st.number_input("Discovered Period (Days)", value=0.6392, format="%.4f")
        
    if st.button("Run Odd/Even Test"):
        double_period = qa_period * 2
        with st.spinner(f"Pulling fresh data for TIC {int(qa_tic)}..."):
            search = lk.search_lightcurve(f"TIC {int(qa_tic)}")
            
            if len(search) == 0:
                st.warning("No light curves found for QA test.")
            else:
                for preferred_author in ["TESS-SPOC", "QLP", "SPOC", "TGLC"]:
                    author_search = search[search.author == preferred_author]
                    if len(author_search) > 0:
                        search = author_search
                        st.info(f"Found data from the {search.author[0]} pipeline.")
                        break
                try:
                    lc = search.download_all().stitch().remove_nans().remove_outliers(sigma=5.0)
                    folded_lc = lc.fold(period=double_period)
                    
                    fig, ax = plt.subplots(figsize=(10, 5))
                    ax.scatter(folded_lc.time.value, folded_lc.flux.value * 100, s=2, color='gray', alpha=0.4)
                    
                    ax.axvline(-qa_period/2, color='crimson', linestyle='--', lw=2, label='Odd Transits (Dip 1)')
                    ax.axvline(qa_period/2, color='dodgerblue', linestyle='--', lw=2, label='Even Transits (Dip 2)')
                    
                    ax.set_title(f"Odd/Even QA Test: TIC {int(qa_tic)} (Folded at {double_period:.4f} days)")
                    ax.set_xlabel("Days from Center")
                    ax.set_ylabel("Brightness (%)")
                    ax.legend(loc='lower left')
                    ax.grid(alpha=0.2)
                    
                    st.pyplot(fig)
                except Exception as e:
                    st.error(f"QA Test failed to process: {e}")
