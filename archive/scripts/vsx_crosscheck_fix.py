#!/usr/bin/env python
"""Repair pass for vsx_crosscheck_2026-11-06.json — READ-ONLY.
1) Robust VSX cone re-fetch for every star (requests + ElementTree
TABLEDATA parse; the astroquery/votable parse in pass 1 mangled
non-empty results). 2) Gaia DR3 secondary via the archive TAP sync
endpoint over plain HTTPS (curl-verified reachable; astroquery's
session failed SSL through this VM's proxy) for stars with no
same-star VSX entry. Updates the JSON in place."""
import io
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import requests
from astropy.coordinates import SkyCoord

BASE = Path(__file__).resolve().parent
JSON_PATH = BASE / "vsx_crosscheck_2026-11-06.json"
EB_TOKENS = {"E", "EA", "EB", "EW", "ELL"}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def vsx_cone(ra, dec):
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={ra}+{dec}&size=0.5&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    fields = [f.get("id") for f in root.iter("FIELD")]
    centre = SkyCoord(ra=ra, dec=dec, unit="deg")
    entries = []
    for tr in root.iter("TR"):
        vals = [(td.text or "").strip() for td in tr.findall("TD")]
        row = dict(zip(fields, vals))
        raw = row.get("radec2000", "").replace(" ", ",")
        parts = [p for p in raw.split(",") if p]
        if len(parts) != 2:
            continue
        cra, cdec = float(parts[0]), float(parts[1])
        sep = float(centre.separation(
            SkyCoord(ra=cra, dec=cdec, unit="deg")).arcsec)
        if sep > 30.0:
            continue

        def num(k):
            v = row.get(k, "")
            try:
                return float(v) if v not in ("", None) else None
            except ValueError:
                return None

        maxm, minm = num("maxMag"), num("minMag")
        entries.append({
            "auid": row.get("auid") or None,
            "name": row.get("name"),
            "const": row.get("const"),
            "ra_deg": cra, "dec_deg": cdec,
            "sep_arcsec": round(sep, 2),
            "var_type": row.get("varType"),
            "max_mag": maxm, "max_passband": row.get("maxPass") or None,
            "min_mag": minm, "min_passband": row.get("minPass") or None,
            "mag_range": (f"{maxm}-{minm} {row.get('maxPass') or ''}".strip()
                          if maxm is not None else None),
            "period_d": num("period"),
            "epoch": num("epoch"),
            "spec_type": row.get("specType") or None,
            "discoverer": row.get("disc") or None,
        })
    entries.sort(key=lambda e: e["sep_arcsec"])
    return entries, url


def tap_csv(adql):
    url = ("https://gea.esac.esa.int/tap-server/tap/sync?REQUEST=doQuery"
           f"&LANG=ADQL&FORMAT=csv&QUERY={quote(adql)}")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or text.startswith("<?xml") or "error" in text[:200].lower():
        raise RuntimeError(f"TAP error/empty: {text[:200]}")
    import csv as csvmod
    rows = list(csvmod.DictReader(io.StringIO(text)))
    return rows


def gaia_secondary(ra, dec):
    out = {"catalogue": "Gaia DR3 (archive TAP via HTTPS sync endpoint)"}
    r_deg = 10.0 / 3600.0
    srcs = tap_csv(
        "SELECT source_id, ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {r_deg})) = 1")
    centre = SkyCoord(ra=ra, dec=dec, unit="deg")
    cands = []
    for r in srcs:
        sep = float(centre.separation(SkyCoord(
            ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")).arcsec)
        cands.append({"source_id": int(r["source_id"]),
                      "sep_arcsec": round(sep, 2),
                      "phot_g_mean_mag": float(r["phot_g_mean_mag"])})
    cands.sort(key=lambda c: c["sep_arcsec"])
    out["gaia_source_within_10arcsec"] = cands
    if not cands:
        out["present_as_variable"] = False
        out["note"] = "no Gaia DR3 source within 10 arcsec"
        return out
    sid = cands[0]["source_id"]
    out["dr3_counterpart_source_id"] = sid
    out["dr3_counterpart_sep_arcsec"] = cands[0]["sep_arcsec"]
    cls = tap_csv(
        "SELECT best_class_name, best_class_score "
        f"FROM gaiadr3.vari_classifier_result WHERE source_id = {sid}")
    out["vari_classifier_result"] = (
        {"best_class_name": cls[0]["best_class_name"],
         "best_class_score": float(cls[0]["best_class_score"])} if cls else None)
    try:
        eb = tap_csv(
            f"SELECT * FROM gaiadr3.vari_eclipsing_binary WHERE source_id = {sid}")
        out["vari_eclipsing_binary"] = eb[0] if eb else None
    except Exception as e:
        out["vari_eclipsing_binary"] = f"query failed: {type(e).__name__}"
    out["present_as_variable"] = bool(out.get("vari_classifier_result")) or \
        isinstance(out.get("vari_eclipsing_binary"), dict)
    return out


def type_is_eb_family(vartype):
    if not vartype:
        return False
    toks = [t.strip().upper().rstrip(":").split("/")[0]
            for t in str(vartype).replace("|", "+").split("+")]
    return any(t in EB_TOKENS for t in toks if t)


def period_relation(filed, ours):
    if filed is None or filed == 0:
        return "no period filed"
    rel = abs(filed - ours) / ours
    if rel <= 0.01:
        return "agree (<=1%)"
    if abs(filed - ours / 2) / (ours / 2) <= 0.01:
        return "filed is HALF our period"
    if abs(filed - 2 * ours) / (2 * ours) <= 0.01:
        return "filed is DOUBLE our period"
    return f"differ (rel. diff {rel:.1%})"


def main():
    data = json.loads(JSON_PATH.read_text())
    data["vsx_route_used"] = ("VSX website query.votable cone service "
                              "(vsx.aavso.org), validated on the TIC 308851365 "
                              "control entry (ROT, P 0.75629 recovered exactly)")
    data["secondary_route"] = ("Gaia DR3 archive TAP via plain HTTPS sync "
                               "endpoint (astroquery session failed SSL "
                               "through this VM's proxy on 2026-11-06)")
    for star in data["stars"]:
        tic = star["tic"]
        ra = float(star["tic_row"]["ra"])
        dec = float(star["tic_row"]["dec"])
        log(f"=== TIC {tic} ===")
        entries, url = vsx_cone(ra, dec)
        star["vsx_route"] = "VSX website query.votable (robust re-fetch)"
        star["vsx_query_url"] = url
        star["vsx_entries_within_30arcsec"] = entries
        same = [e for e in entries if e["sep_arcsec"] <= 5.0]
        star["vsx_same_star_entries"] = same
        star.pop("fail_reason", None)
        log(f"  VSX: {len(entries)} within 30 arcsec; {len(same)} same-star")
        for e in entries:
            log(f"    {e['sep_arcsec']:6.2f}\" {e['name']} type={e['var_type']} "
                f"P={e['period_d']}")
        if same:
            e = same[0]
            star["filed_vs_ours"] = {
                "type_eb_family": type_is_eb_family(e["var_type"]),
                "period_relation": period_relation(e["period_d"],
                                                   star["our_period_d"])}
            star["classification"] = (
                "IN VSX, TYPE+PERIOD AGREE"
                if star["filed_vs_ours"]["type_eb_family"] and
                star["filed_vs_ours"]["period_relation"].startswith("agree")
                else "IN VSX, DISAGREES")
            star.pop("secondary", None)
        else:
            try:
                sec = gaia_secondary(ra, dec)
                star["secondary"] = sec
                log(f"  Gaia DR3: counterpart {sec.get('dr3_counterpart_source_id')} "
                    f"@ {sec.get('dr3_counterpart_sep_arcsec')}\"; classifier="
                    f"{(sec.get('vari_classifier_result') or {}).get('best_class_name')}; "
                    f"EB table={'yes' if isinstance(sec.get('vari_eclipsing_binary'), dict) else 'no'}")
            except Exception as ex:
                star["secondary"] = {
                    "catalogue": "Gaia DR3 (archive TAP via HTTPS sync endpoint)",
                    "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
                log(f"  Gaia secondary FAILED: {ex}")
            sec = star["secondary"]
            if sec.get("present_as_variable"):
                star["classification"] = ("ABSENT IN VSX (present in Gaia DR3) "
                                          "— new-filing candidate, known variable elsewhere")
            elif "error" not in sec:
                star["classification"] = "ABSENT EVERYWHERE CHECKED"
            else:
                star["classification"] = ("ABSENT IN VSX (secondary check failed) "
                                          "— new-filing candidate, secondary unresolved")
        log(f"  -> {star['classification']}")
        JSON_PATH.write_text(json.dumps(data, indent=2, default=str))
    log("REPAIR PASS COMPLETE")


if __name__ == "__main__":
    main()
