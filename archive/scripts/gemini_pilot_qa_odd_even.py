# Gemini pilot QA — Dynamic Odd/Even Test (Colab cell, as pasted by Dev 2026-11-04).
# Provenance: from the ORIGINAL Gemini-built pilot app/QA codes that Dev runs in
# Colab — the ancestor of this project's QA view. Kept as reference material;
# NOT wired into the app. See the comparison in chat 2026-11-04: the app's
# hunter.odd_even_test measures numeric depths + verdict on flattened flux with
# a BLS-refined epoch; this pilot version plots the RAW unflattened fold at 2P
# (best-author data, sigma-5 clip, no epoch refinement) for the human eye.
# It caught TIC 294665246 by eye ("mayhem") the night the app's numeric
# odd/even passed that star planet-like and only persistence convicted it —
# its one genuine edge over the app version is the raw-data view.

# @title ⚖️ Dynamic Odd/Even QA Test
# @markdown Enter the TIC ID and the discovered Period below to run the False Positive check.

Target_TIC_ID = 294665246 # @param {type:"number"}
Discovered_Period_Days = 13.8906 # @param {type:"number"}

import lightkurve as lk
import matplotlib.pyplot as plt

tic_id = int(Target_TIC_ID)
period = float(Discovered_Period_Days)
double_period = period * 2

print(f"\nPulling fresh data to run QA Odd/Even Test on TIC {tic_id}...")

search = lk.search_lightcurve(f"TIC {tic_id}")
if len(search) == 0:
    print("  -> No light curves found for QA test.")
else:
    # Dynamically find the best pipeline author
    for preferred_author in ["TESS-SPOC", "QLP", "SPOC", "TGLC"]:
        author_search = search[search.author == preferred_author]
        if len(author_search) > 0:
            search = author_search
            print(f"Found data from the {search.author[0]} pipeline!")
            break

    try:
        # Download, stitch, clean, and fold at double the period
        lc = search.download_all().stitch().remove_nans().remove_outliers(sigma=5.0)
        folded_lc = lc.fold(period=double_period)

        # Build the dynamic plot
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.scatter(folded_lc.time.value, folded_lc.flux.value * 100, s=2, color='gray', alpha=0.4)

        ax.axvline(-period/2, color='crimson', linestyle='--', lw=2, label='Odd Transits (Dip 1)')
        ax.axvline(period/2, color='dodgerblue', linestyle='--', lw=2, label='Even Transits (Dip 2)')

        ax.set_title(f"Odd/Even QA Test: TIC {tic_id} (Folded at {double_period:.4f} days)")
        ax.set_xlabel("Days from Center")
        ax.set_ylabel("Brightness (%)")
        ax.legend(loc='lower left')
        ax.grid(alpha=0.2)

        plt.show()

    except Exception as e:
        print(f"  -> QA Test failed to process: {e}")
