# -*- coding: utf-8 -*-
"""
Enriquecedor de fichas completas para los anuncios nuevos más prometedores
(Top Chollos con score >= 70, anuncios en Montepinar o anuncios sin superficie clara).

Descarga la ficha individual real del anuncio para extraer:
- Descripción completa (revelando si es particular, herencia, urge, esquina, luz/agua, urbano/rústico).
- Teléfono de contacto (mejora además la detección de duplicados entre portales).
- Imagen principal (`og:image`) si faltaba.
- Coordenadas exactas (`geo` / `data-lat`) si la ficha las publica.
- Referencia catastral + consulta automática a la Sede del Catastro cuando existe.
- Superficie exacta de parcela si la tarjeta solo traía superficie construida.
"""

import html
import json
import re
import time
from typing import Any, Dict, List, Optional, Set

from src.catastro import extract_cadastral_ref, lookup_catastro_by_coords, lookup_catastro_by_rc
from src.scrapers.portals_scraper import http_get

PHONE_RE = re.compile(r"(?:\+34[\s\-]?)?([6789]\d{2}[\s\.\-]?\d{2,3}[\s\.\-]?\d{2,3}[\s\.\-]?\d{0,2})")


def _extract_jsonld_details(raw_html: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw_html, re.IGNORECASE | re.DOTALL):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if obj.get("description") and len(str(obj["description"])) > len(out.get("description", "")):
                out["description"] = html.unescape(str(obj["description"])).strip()
            geo = obj.get("geo")
            if isinstance(geo, dict):
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                try:
                    if lat and lon:
                        out["lat"] = float(str(lat).replace(",", "."))
                        out["lon"] = float(str(lon).replace(",", "."))
                except ValueError:
                    pass
            if obj.get("telephone") and not out.get("phone"):
                out["phone"] = str(obj["telephone"]).strip()
            img = obj.get("image")
            if img and not out.get("image_url"):
                if isinstance(img, list) and img:
                    img = img[0]
                if isinstance(img, dict):
                    img = img.get("url")
                if isinstance(img, str) and img.startswith("http"):
                    out["image_url"] = img
    return out


def enrich_listing_from_url(item: Dict[str, Any], timeout: int = 12) -> Dict[str, Any]:
    """Descarga y enriquece una ficha individual sin perder los campos ya detectados."""
    url = (item.get("url") or "").strip()
    if not url.startswith("http"):
        return item

    raw_html = http_get(url, timeout=timeout, retries=1)
    if not raw_html:
        return item

    enriched = dict(item)
    ld = _extract_jsonld_details(raw_html)

    # Normalizar <sup>2</sup> -> 2 antes de extraer texto
    norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)

    # og:image si falta foto
    if not enriched.get("image_url"):
        if ld.get("image_url"):
            enriched["image_url"] = ld["image_url"]
        else:
            og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']', raw_html, re.IGNORECASE)
            if og_img:
                enriched["image_url"] = html.unescape(og_img.group(1)).strip()

    # Descripción enriquecida (JSON-LD o meta description + cuerpo limpio de la ficha)
    meta_desc_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{30,})["\']', raw_html, re.IGNORECASE)
    meta_desc = html.unescape(meta_desc_m.group(1)).strip() if meta_desc_m else ""

    vis_html = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>|<nav[^>]*>.*?</nav>|<footer[^>]*>.*?</footer>", " ", norm_html, flags=re.IGNORECASE | re.DOTALL)
    vis_txt = html.unescape(re.sub(r"<[^>]+>", " ", vis_html))
    vis_txt = re.sub(r"\s+", " ", vis_txt).strip()

    best_desc = ld.get("description") or meta_desc or enriched.get("description") or ""
    # Si el texto visible tiene bloques largos de descripción de inmueble, añadir los datos clave
    if len(best_desc) < 250 and len(vis_txt) > 300:
        best_desc = f"{best_desc} {vis_txt[:900]}".strip()
    elif enriched.get("description") and enriched["description"] not in best_desc:
        best_desc = f"{best_desc} | {enriched['description']}".strip()
    enriched["description"] = best_desc[:1400]

    # Teléfono
    if not enriched.get("phone"):
        if ld.get("phone"):
            enriched["phone"] = ld["phone"]
        else:
            tel_m = re.search(r'href=["\']tel:([+\d\s\-]{9,18})["\']', raw_html, re.IGNORECASE)
            if tel_m:
                enriched["phone"] = tel_m.group(1).strip()

    # Coordenadas reales si vienen en JSON-LD o atributos data-lat/data-lng
    real_lat = ld.get("lat")
    real_lon = ld.get("lon")
    if not (real_lat and real_lon):
        lat_m = re.search(r'data-lat=["\'](3[78]\.\d+)["\']', raw_html)
        lon_m = re.search(r'data-(?:lng|lon)=["\'](-[01]\.\d+)["\']', raw_html)
        if lat_m and lon_m:
            real_lat, real_lon = float(lat_m.group(1)), float(lon_m.group(1))
    if real_lat and real_lon and 37.5 <= real_lat <= 38.6 and -1.5 <= real_lon <= -0.3:
        enriched["lat"] = round(real_lat, 5)
        enriched["lon"] = round(real_lon, 5)
        enriched["has_exact_coords"] = True

    # Superficie de parcela exacta si no venía o era igual a construida
    plot_m = re.search(
        r"(?:parcela|terreno|solar)[^\d]{0,25}(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m[²2]|"
        r"(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m[²2]\s*(?:de\s*)?(?:parcela|terreno|solar)",
        f"{best_desc} {vis_txt[:2500]}",
        re.IGNORECASE,
    )
    if plot_m:
        raw_p = (plot_m.group(1) or plot_m.group(2)).replace(".", "")
        try:
            pv = float(raw_p)
            if 40 <= pv <= 50000:
                enriched["surface_plot_m2"] = pv
        except ValueError:
            pass

    # Referencia catastral + consulta oficial a Sede del Catastro (si existe RC o coords exactas)
    rc = extract_cadastral_ref(f"{best_desc} {vis_txt[:4000]}")
    catastro_info = None
    if rc:
        enriched["cadastral_ref"] = rc
        catastro_info = lookup_catastro_by_rc(rc)
    elif enriched.get("has_exact_coords"):
        catastro_info = lookup_catastro_by_coords(enriched["lat"], enriched["lon"])
        if catastro_info and catastro_info.get("rc"):
            enriched["cadastral_ref"] = catastro_info["rc"]

    if catastro_info:
        enriched["catastro_info"] = catastro_info

    enriched["detail_enriched"] = True
    return enriched


def enrich_top_candidates(
    analyzed_list: List[Dict[str, Any]],
    analyzer: Any,
    already_known_ids: Optional[Set[str]] = None,
    max_enrich: int = 16,
) -> int:
    """
    Enriquece in-place hasta `max_enrich` anuncios prioritarios (nuevos destacados,
    chollos con score >= 70, Montepinar o anuncios a los que les falte parcela/descripción).
    Devuelve el número de fichas enriquecidas.
    """
    known = already_known_ids or set()
    candidates = []
    for idx, it in enumerate(analyzed_list):
        if it.get("is_orihuela_costa"):
            continue
        if not it.get("sin_filtro") and it.get("asset_type") in ("descartado_piso", "rustico_dudoso"):
            continue
        is_new = it.get("id") not in known
        is_montepinar = it.get("zone_id") == "montepinar"
        is_high = (it.get("chollo_score") or 0) >= 70 and bool(it.get("is_highlighted"))
        needs_m2 = not (it.get("effective_plot_m2") or 0)
        if is_new and (is_montepinar or is_high or needs_m2):
            priority = (0 if is_montepinar else 1, -(it.get("chollo_score") or 0))
            candidates.append((priority, idx))

    candidates.sort(key=lambda x: x[0])
    enriched_count = 0

    for _, idx in candidates[:max_enrich]:
        orig = analyzed_list[idx]
        updated_raw = enrich_listing_from_url(orig)
        if updated_raw.get("detail_enriched"):
            re_analyzed = analyzer.analyze_raw_item(updated_raw)
            # Preservar info de Catastro y coordenadas exactas si se obtuvieron
            if updated_raw.get("cadastral_ref"):
                re_analyzed["cadastral_ref"] = updated_raw["cadastral_ref"]
            if updated_raw.get("catastro_info"):
                re_analyzed["catastro_info"] = updated_raw["catastro_info"]
            if updated_raw.get("has_exact_coords"):
                re_analyzed["lat"] = updated_raw["lat"]
                re_analyzed["lon"] = updated_raw["lon"]
                re_analyzed["has_exact_coords"] = True
            analyzed_list[idx] = re_analyzed
            enriched_count += 1
            time.sleep(0.3)

    return enriched_count
