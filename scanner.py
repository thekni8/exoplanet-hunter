import numpy as np
import pandas as pd
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares
import astropy.units as u
from astroquery.mast import Catalogs
from astropy.coordinates import SkyCoord
import time
import os
import gc

# Define target area (Defaulting to a sample patch in Orion)
coord = SkyCoord(ra=83.82 * u.deg, dec=-5.39 * u.deg)
tic_table = Catalogs.query_region(coord, radius=0.1 * u.deg, catalog="TIC")

mask = ((tic_table["Tmag"] >= 13.5) & (tic_table["Tmag"] <= 15.4) & 
        (tic_table["rad"] > 0.2) & (tic_table["rad"] < 1.5))
candidates = tic_table[mask][:20]

print(f"Starting headless scan of {len(candidates)} stars...")

for row in candidates:
    tic_id = int(row["ID"])
    star_rad = float(row["rad"])
    
    try:
        print(f"Querying TIC {tic_id}...")
        time.sleep(1) # Respect NASA rate limits
        
        search = lk.search_lightcurve(f"TIC {tic_id}", author=["TESS-SPOC", "QLP", "SPOC"])
        if len(search) < 2:
            continue

        lc_collection = search.download_all()
        if not lc_collection:
            continue
            
        lc = lc_collection.stitch().remove_nans().remove_outliers(sigma=5.0)
        lc_flat = lc.flatten(window_length=71)

        t = lc_flat.time.value
        f = lc_flat.flux.value
        bls = BoxLeastSquares(t * u.day, f)
        res = bls.power(np.linspace(0.5, 15.0, 20000) * u.day, np.linspace(0.03, 0.20, 10) * u.day)

        best = np.argmax(res.power)
        sde = (res.power[best] - np.median(res.power)) / (np.std(res.power) + 1e-12)

        if sde >= 3.0:
            P = float(res.period[best].value)
            planet_re = np.sqrt(max(0.0, float(res.depth[best]))) * star_rad * 109.1
            
            print(f"🎯 SIGNAL FOUND! TIC {tic_id} | Period: {P:.2f} | Size: {planet_re:.1f}")
            
            # Vault the data to CSV
            hit_data = pd.DataFrame([{"TIC_ID": tic_id, "Period": P, "Earth_Radii": planet_re}])
            if not os.path.isfile("hits.csv"):
                hit_data.to_csv("hits.csv", index=False)
            else:
                hit_data.to_csv("hits.csv", mode='a', header=False, index=False)
                
    except Exception as e:
        print(f"Failed TIC {tic_id}: {e}")
    
    finally:
        # Crucial Memory Flush
        try:
            del search, lc_collection, lc, lc_flat, bls, res, t, f
        except NameError:
            pass
        gc.collect() 
        
print("Batch complete.")
