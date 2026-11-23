# -*- coding: utf-8 -*-
"""
Scraper ligero de Subastas Procuradores (Consejo General de Procuradores de España,
subastasprocuradores.com) para detectar subastas concursales y extrajudiciales
de solares y viviendas en Orihuela, Montepinar, Raiguero, Benferri y Granja de Rocamora.
Se integra en la misma tabla `auctions` que las subastas del BOE (sin mezclar con anuncios de venta).
"""

import hashlib
import html
import re
import time
import urllib.parse
from typing import Any, Dict, List

from src.analyzer import PropertyAnalyzer, normalize_text
from src.scrapers.portals_scraper import http_get


class ProcuradoresSubastasScraper:
    MAX_PAGES = 4

    def __init__(self, config: Dict[str, Any], analyzer: PropertyAnalyzer):
        self.config = config
        self.analyzer = analyzer
        self.fetch_ok = False
        self.stats = {"consultas_ok": 0, "subastas_revisadas": 0, "en_zona": 0}

    def run(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_ids = set()

        # Filtrar directamente por provincia de Alicante (States=ES-A) y paginar si hay > 10 resultados
        for page in range(1, self.MAX_PAGES + 1):
            url = f"https://www.subastasprocuradores.com/subastas?States=ES-A&OrderBy=PublishDateDesc&Page={page}"
            raw = http_get(url, timeout=14, retries=2)
            if not raw:
                break
            self.fetch_ok = True
            self.stats["consultas_ok"] += 1

            cards = re.split(r'(?=<div[^>]+class=["\'][^"\']*\bsp_sales__body\b)', raw, flags=re.IGNORECASE)
            if len(cards) <= 1:
                break
            for card in cards[1:]:
                chunk = card[:4500]
                self.stats["subastas_revisadas"] += 1

                a_m = re.search(
                    r'<a[^>]+href=["\'](/subastas/[a-z0-9]{8,}[^"\']*)["\'][^>]*title=["\']([^"\']+)["\']',
                    chunk,
                    re.IGNORECASE,
                )
                if not a_m:
                    a_m = re.search(
                        r'<a[^>]+title=["\']([^"\']+)["\'][^>]+href=["\'](/subastas/[a-z0-9]{8,}[^"\']*)["\']',
                        chunk,
                        re.IGNORECASE,
                    )
                    if not a_m:
                        continue
                    title, rel_href = html.unescape(a_m.group(1)).strip(), a_m.group(2).strip()
                else:
                    rel_href, title = a_m.group(1).strip(), html.unescape(a_m.group(2)).strip()

                full_url = urllib.parse.urljoin("https://www.subastasprocuradores.com", rel_href)
                slug_id = rel_href.split("?")[0].rstrip("/").split("/")[-1]
                aid = f"PROC-{slug_id}"
                if aid in seen_ids:
                    continue

                text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
                text_clean = re.sub(r"\s+", " ", text_clean).strip()
                norm = normalize_text(f"{title} {text_clean}")

                # Filtrar estrictamente por nuestras zonas y descartar costa / no inmuebles
                if self.analyzer.is_orihuela_costa(norm):
                    continue
                if not any(k in norm for k in ("orihuela", "montepinar", "raiguero", "benferri", "rocamora", "aparecida", "desamparados", "hurchillo", "arneva")):
                    continue
                if any(w in norm for w in ("vehiculo", "furgoneta", "camion", "maquinaria", "lote de mobiliario", "plaza de garaje")):
                    continue

                zone_id, zone_name, _, lat, lon = self.analyzer.detect_zone(title, text_clean, "Alicante", full_url)
                asset_type, asset_label, is_target = self.analyzer.classify_asset_type(title, text_clean)

                val_m = re.search(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?)\s*€", text_clean)
                valor = float(val_m.group(1).replace(".", "").replace(",", ".")) if val_m else None

                m2_m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m\s*[²2]", text_clean, re.IGNORECASE)
                m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

                seen_ids.add(aid)
                self.stats["en_zona"] += 1
                results.append(
                    {
                        "id": aid,
                        "id_subasta": aid,
                        "fuente": "Subastas Procuradores",
                        "tipo_subasta": "Concursal / Procuradores",
                        "estado": "Activa",
                        "titulo": title[:180],
                        "descripcion": text_clean[:500],
                        "url": full_url,
                        "zone_id": zone_id,
                        "zone_name": zone_name,
                        "localidad": zone_name,
                        "lat": lat,
                        "lon": lon,
                        "asset_type": asset_type,
                        "asset_label": asset_label,
                        "is_target_type": bool(is_target or zone_id == "montepinar"),
                        "valor_subasta": valor,
                        "tasacion": valor,
                        "puja_minima": None,
                        "deposito": None,
                        "superficie_m2": m2,
                        "eur_m2": round(valor / m2, 1) if (valor and m2 and m2 > 0) else None,
                        "fecha_fin": "",
                        "riesgos": ["Subasta concursal/extrajudicial — revisar pliego de condiciones"],
                        "documentos": [],
                        "score": 75 if (is_target or zone_id == "montepinar") else 55,
                    }
                )
            if len(cards) - 1 < 10:
                break
            time.sleep(0.3)

        return results
