"""Stage-0 census (Phase 2, 2A) — vetting-manual §0, in-repo.

Ports the manual census (science-vet/rescore-gauntlet-2026-11-14/
census25.py, 2026-11-14) into the pipeline so the desk driver can
run it on any survivor:

  * TIC row by ID (identity verification) + 180" TIC cone
    (astroquery MAST; the policy radius, gauntlet_v2);
  * Gaia DR3 180" cone (Vizier) — RUWE is advisory, never a kill;
  * VSX 3' cone, parsed as RAW XML TEXT (astropy's votable parser
    crashes/mangles VSX string columns — proven 2026-11-09);
  * TOI check via a targeted TAP query that returns PERIODS
    (hunter.is_known_in_toi only returns a boolean — a TOI at a
    different period must not kill);
  * Planet Hunters Talk (Zooniverse project-5733) search.

Fail-closed, by design: the SWEEP is fail-open (a failed check
must never shrink a sweep silently), but the GAUNTLET is
fail-closed — a census whose TOI, VSX or PHT sub-check errored
produces NO catalogue native, so the stage reads UNMEASURED and
blocks promotion instead of passing on a check that never ran.
The census JSON records exactly which sub-check failed, so the
operator can retry. A Gaia failure is advisory only (Vizier 404s
are a known failure mode — the 2026-11-14 rescore census had
no Gaia data for any of the 25 leads).

Catalogue-kill radii: a VSX variable kills only within 30" of
the target (the hunter.is_known_in_vsx bar) with a period
matching P, 2P or P/2 within 1%. A matching variable 30-180"
out is blend evidence for the blend stage, not a catalogue
kill. A PHT hit has no period attached, so it maps to
INCONCLUSIVE (a human must read the discussion) — see
catalogue_result's PHT branch.
"""
import json
import os
import re

import numpy as np

VSX_MATCH_RADIUS_ARCSEC = 30.0
PERIOD_MATCH_FRAC = 0.01
CENSUS_RADIUS_ARCSEC = 180.0

VSX_QUERY_URL = (
    "https://vsx.aavso.org/index.php?view=query.votable"
    "&coords={ra}+{dec}&size=3.0&unit=2&order=9")
TOI_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
ZOONIVERSE_SEARCH_URL = (
    "https://talk.zooniverse.org/searches"
    "?section=project-5733&query={tic}&types[]=comments&types[]=discussions")

_COORD_RE = re.compile(
    r"(\d{2})[: ](\d{2})[: ](\d{2}(?:\.\d+)?)\s+"
    r"([+-]?\d{2})[: ](\d{2})[: ](\d{2}(?:\.\d+)?)")
_TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def period_matches(vp, period):
    """Does a catalogued period match P, 2P or P/2 within 1%?

    Returns (matched, label) — label is "P", "2P" or "P/2".
    """
    try:
        vp = float(vp)
    except (TypeError, ValueError):
        return False, None
    if not np.isfinite(vp) or vp <= 0:
        return False, None
    for cand, label in ((period, "P"), (2 * period, "2P"),
                        (period / 2, "P/2")):
        if abs(vp - cand) / cand < PERIOD_MATCH_FRAC:
            return True, label
    return False, None


def run_census(tic, period, workdir):
    """Run the stage-0 census for one target. Writes
    stage0_census.json into workdir and returns the census dict.
    Never raises for a sub-check failure — errors are recorded
    in census["errors"] and catalogue_native() decides usability.
    """
    from astroquery.mast import Catalogs
    from astroquery.vizier import Vizier
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    import requests

    tic = str(tic)
    period = float(period)
    census = {"target": None, "tic_cone_180arcsec": [],
              "gaia_dr3_cone": None, "vsx_cone_180arcsec": [],
              "toi": None, "pht": None, "flags": [], "errors": []}
    try:
        tbl = Catalogs.query_criteria(catalog="Tic", ID=int(tic))
        if len(tbl) != 1:
            raise ValueError(f"expected 1 TIC row, got {len(tbl)}")
        row = tbl[0]
        target = {}
        for k in ("ID", "ra", "dec", "Tmag", "rad", "Teff", "mass",
                  "contratio", "GAIA", "dstArcSec"):
            if k not in tbl.colnames:
                continue
            v = row[k]
            target[k] = (None if v is None else
                         (float(v) if k in ("ra", "dec", "Tmag", "rad",
                                            "Teff", "mass", "contratio",
                                            "dstArcSec") else str(v)))
        census["target"] = target
        ra0, dec0 = float(row["ra"]), float(row["dec"])
        centre = SkyCoord(ra=ra0 * u.deg, dec=dec0 * u.deg)
        cone = Catalogs.query_region(centre,
                                     radius=CENSUS_RADIUS_ARCSEC * u.arcsec,
                                     catalog="Tic")
        for r in cone:
            c = SkyCoord(ra=float(r["ra"]) * u.deg,
                         dec=float(r["dec"]) * u.deg)
            census["tic_cone_180arcsec"].append({
                "tic_id": str(r["ID"]), "ra": float(r["ra"]),
                "dec": float(r["dec"]),
                "sep_arcsec": round(float(
                    centre.separation(c).arcsec), 2),
                "Tmag": (None if r["Tmag"] is None
                         else float(r["Tmag"])),
                "rad_rsun": (None if r["rad"] is None
                             else float(r["rad"])),
                "contratio": (None if r["contratio"] is None
                              else float(r["contratio"])),
                "gaia_id": (None if r["GAIA"] is None
                            else str(r["GAIA"])),
                "is_target": str(r["ID"]) == tic})
        census["tic_cone_180arcsec"].sort(key=lambda n: n["sep_arcsec"])
        # diffimg --census-json reads tic_cone_search + radius_arcsec
        # (load_census_json); the stage0 record carries both keys so
        # one census file feeds the catalogue stage and diffimg.
        census["tic_cone_search"] = census["tic_cone_180arcsec"]
        census["radius_arcsec"] = CENSUS_RADIUS_ARCSEC
        tmag0 = target.get("Tmag")
        if tmag0 is not None:
            for n in census["tic_cone_180arcsec"]:
                if (not n["is_target"] and n["Tmag"] is not None
                        and n["Tmag"] < tmag0):
                    census["flags"].append(
                        f"brighter neighbour TIC {n['tic_id']} "
                        f"Tmag {n['Tmag']} at {n['sep_arcsec']}\"")
        try:
            v = Vizier(columns=["Source", "RA_ICRS", "DE_ICRS", "Gmag",
                                "RUWE"], row_limit=100)
            res = v.query_region(centre,
                                 radius=CENSUS_RADIUS_ARCSEC * u.arcsec,
                                 catalog="I/355/gaiadr3")
            if res and len(res[0]):
                rows = []
                for gr in res[0]:
                    gc_ = SkyCoord(ra=float(gr["RA_ICRS"]) * u.deg,
                                   dec=float(gr["DE_ICRS"]) * u.deg)
                    rows.append({"gaia_dr3": str(gr["Source"]),
                                 "sep_arcsec": round(float(
                                     centre.separation(gc_).arcsec), 2),
                                 "Gmag": float(gr["Gmag"]),
                                 "RUWE": (None if gr["RUWE"] is None
                                          else float(gr["RUWE"]))})
                rows.sort(key=lambda x: x["sep_arcsec"])
                census["gaia_dr3_cone"] = rows
                if rows and rows[0]["sep_arcsec"] < 2.0:
                    ruwe = rows[0]["RUWE"]
                    if ruwe is not None and ruwe > 1.4:
                        census["flags"].append(
                            f"Gaia RUWE {ruwe} — unresolved companion "
                            "likely")
        except Exception as e:  # advisory only — never blocks
            census["errors"].append(f"gaia: {type(e).__name__}: {e}")
        try:
            r = requests.get(VSX_QUERY_URL.format(ra=ra0, dec=dec0),
                             timeout=60)
            if r.status_code != 200:
                raise ValueError(f"VSX HTTP {r.status_code}")
            for block in r.text.split("<TR>")[1:]:
                cells = _TD_RE.findall(block)
                cells = [_TAG_RE.sub("", c).strip() for c in cells]
                if len(cells) < 12:
                    continue
                m = _COORD_RE.search(cells[3])
                if not m:
                    continue
                h, mi, s, d, dm, ds = m.groups()
                sgn = -1 if d.startswith("-") else 1
                vra = (float(h) + float(mi) / 60
                       + float(s) / 3600) * 15.0
                vdec = sgn * (abs(float(d)) + float(dm) / 60
                              + float(ds) / 3600)
                vc = SkyCoord(ra=vra * u.deg, dec=vdec * u.deg)
                census["vsx_cone_180arcsec"].append({
                    "name": cells[1], "type": cells[4],
                    "period_d": cells[11],
                    "sep_arcsec": round(float(
                        centre.separation(vc).arcsec), 2)})
            census["vsx_cone_180arcsec"].sort(
                key=lambda x: x["sep_arcsec"])
            for vrow in census["vsx_cone_180arcsec"]:
                matched, label = period_matches(vrow["period_d"], period)
                if matched:
                    census["flags"].append(
                        f"VSX {vrow['name']} ({vrow['type']}) period "
                        f"{vrow['period_d']} d matches {label} at "
                        f"{vrow['sep_arcsec']}\"")
        except Exception as e:
            census["errors"].append(f"vsx: {type(e).__name__}: {e}")
    except Exception as e:
        census["errors"].append(f"census: {type(e).__name__}: {e}")
    try:
        r = requests.get(
            TOI_TAP_URL,
            params={"query": "SELECT toi, pl_orbper, tfopwg_disp "
                             f"FROM toi WHERE tid = {int(tic)}",
                    "format": "csv"},
            timeout=90)
        if r.status_code != 200:
            raise ValueError(f"TOI TAP HTTP {r.status_code}")
        rows = []
        for line in r.text.splitlines()[1:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 3 or not parts[0]:
                continue
            try:
                p_orb = float(parts[1]) if parts[1] else None
            except ValueError:
                p_orb = None
            rows.append({"toi": parts[0], "period_d": p_orb,
                         "disposition": parts[2] or None})
        census["toi"] = {"is_toi": bool(rows), "rows": rows}
        if rows:
            census["flags"].append(
                "IS A TOI: " + ", ".join(r["toi"] for r in rows))
    except Exception as e:
        census["errors"].append(f"toi: {type(e).__name__}: {e}")
    try:
        r = requests.get(ZOONIVERSE_SEARCH_URL.format(tic=tic),
                         headers={"Accept": "application/vnd.api+json; "
                                            "version=1"},
                         timeout=10)
        if r.status_code != 200:
            raise ValueError(f"PHT HTTP {r.status_code}")
        n = len(r.json().get("searches", []))
        census["pht"] = {"is_discussed": n > 0, "n_hits": n}
        if n > 0:
            census["flags"].append(
                f"discussed on Planet Hunters Talk ({n} hits)")
    except Exception as e:
        census["errors"].append(f"pht: {type(e).__name__}: {e}")
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, "stage0_census.json"), "w") as fh:
        json.dump(census, fh, indent=1)
    return census


def census_usable(census):
    """Is the census good enough to build a catalogue native?

    Fail-closed: the TIC row must exist and the TOI, VSX and PHT
    sub-checks must all have run. A Gaia failure does not block
    (advisory only).
    """
    if not census or census.get("target") is None:
        return False
    errs = census.get("errors") or []
    for prefix in ("toi:", "vsx:", "pht:", "census:"):
        if any(e.startswith(prefix) for e in errs):
            return False
    return True


def catalogue_native(census, period):
    """Map a census to the catalogue adapter native.

    {"known", "source", "var_type", "period_match"}. Returns None
    when the census is unusable (fail-closed — the stage then
    reads UNMEASURED). Precedence: TOI > VSX > PHT (a TOI hit
    with a matching period is the strongest catalogue kill).
    """
    if not census_usable(census):
        return None
    period = float(period)
    toi = census.get("toi") or {}
    if toi.get("is_toi"):
        matched = None
        for row in toi.get("rows") or []:
            m, _label = period_matches(row.get("period_d"), period)
            if m:
                matched = row
                break
        if matched is not None:
            return {"known": True, "source": "TOI",
                    "var_type": matched.get("disposition") or "TOI",
                    "period_match": True}
        first = (toi.get("rows") or [{}])[0]
        return {"known": True, "source": "TOI",
                "var_type": first.get("disposition") or "TOI",
                "period_match": False}
    for vrow in census.get("vsx_cone_180arcsec") or []:
        if vrow.get("sep_arcsec", 1e9) > VSX_MATCH_RADIUS_ARCSEC:
            continue
        m, _label = period_matches(vrow.get("period_d"), period)
        if m:
            return {"known": True, "source": "VSX",
                    "var_type": vrow.get("type"),
                    "period_match": True}
    for vrow in census.get("vsx_cone_180arcsec") or []:
        if vrow.get("sep_arcsec", 1e9) <= VSX_MATCH_RADIUS_ARCSEC:
            return {"known": True, "source": "VSX",
                    "var_type": vrow.get("type"),
                    "period_match": False}
    pht = census.get("pht") or {}
    if pht.get("is_discussed"):
        # No period attached to a Talk hit — the adapter reads
        # this as INCONCLUSIVE (a human must read the discussion).
        return {"known": True, "source": "PHT", "var_type": None,
                "period_match": None}
    return {"known": False, "source": None, "var_type": None,
            "period_match": False}


def brightest_neighbour(census):
    """The brightest non-target neighbour in the 180\" cone
    (the blend stage's first suspect), or None if the cone has
    no other star with a Tmag."""
    best = None
    for n in (census or {}).get("tic_cone_180arcsec") or []:
        if n.get("is_target") or n.get("Tmag") is None:
            continue
        if best is None or n["Tmag"] < best["Tmag"]:
            best = n
    return best
