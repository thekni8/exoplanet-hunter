import numpy as np
import pandas as pd
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares
import astropy.units as u
import os
import gc

# Targeted quick test: TOI-114 (deep, obvious transit, 1 sector)
candidates = [{"ID": "322307342", "rad": 1.2}]
print("Starting rapid 1-sector QA test on TIC 322307342...")

for row in candidates:
    tic_id = int(row["ID"])
    star_rad = float(row["rad"])
    
    try:
        print(f"Querying TIC {tic_id} (Sector 1 only)...")
        search = lk.search_lightcurve(f"TIC {tic_id}", author="SPOC")
        
        if len(search) == 0:
            print("No SPOC light curves found.")
            continue

        # Slice search[:1] to download only 1 sector and keep .stitch() valid
        lc_collection = search[:1].download_all()
        if not lc_collection:
            continue
            
        lc = lc_collection.stitch().remove_nans().remove_outliers(sigma=5.0)
        lc_flat = lc.flatten(window_length=71)

        t = lc_flat.time.value
        f = lc_flat.flux.value
        
        # 5,000 grid points is more than enough for a quick QA signal
        bls = BoxLeastSquares(t * u.day, f)
        res = bls.power(np.linspace(1.0, 5.0, 5000) * u.day, np.linspace(0.03, 0.15, 5) * u.day)

        best = np.argmax(res.power)
        sde = (res.power[best] - np.median(res.power)) / (np.std(res.power) + 1e-12)
        
        print(f"Calculated SDE: {sde:.2f}")

        if sde >= 5.0:
            P = float(res.period[best].value)
            planet_re = np.sqrt(max(0.0, float(res.depth[best]))) * star_rad * 109.1
            
            print(f"🎯 SIGNAL FOUND! TIC {tic_id} | Period: {P:.2f} d | Size: {planet_re:.1f} Re")
            
            hit_data = pd.DataFrame([{"TIC_ID": tic_id, "Period": P, "Earth_Radii": planet_re}])
            if not os.path.isfile("hits.csv"):
                hit_data.to_csv("hits.csv", index=False)
            else:
                hit_data.to_csv("hits.csv", mode='a', header=False, index=False)
                
    except Exception as e:
        print(f"Failed TIC {tic_id}: {e}")
    
    finally:
        try:
            del search, lc_collection, lc, lc_flat, bls, res, t, f
        except NameError:
            pass
        gc.collect()

print("QA test complete.")
