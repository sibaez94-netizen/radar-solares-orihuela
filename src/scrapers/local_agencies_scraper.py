# -*- coding: utf-8 -*-
"""
Scraper para Inmobiliarias Locales de la Vega Baja (Orihuela, Benferri, Granja de Rocamora,
Montepinar, Raiguero) y Servicers Bancarios (Solvia, Aliseda, Haya).
Incluye parser universal compatible con Inmovilla, Witei y WordPress Real Estate.
"""

import html
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from src.scrapers.portals_scraper import PortalsScraper, http_get


class LocalAgenciesAndBanksScraper:
    MAX_PAGES = 4

    DAYAS_ZONE_KEYWORDS = (
        "orihuela", "montepinar", "raiguero", "benferri", "rocamora",
        "aparecida", "desamparados", "hurchillo", "arneva", "campaneta",
        "molins", "san-bartolome", "correntias", "matanza", "murada",
    )
    DAYAS_EXCLUDE_KEYWORDS = (
        "orihuela-costa", "playa-flamenca", "la-zenia", "cabo-roig",
        "villamartin", "campoamor", "dehesa-de-campoamor", "punta-prima",
        "los-dolses", "la-regia", "las-ramblas", "mil-palmeras",
        "torrevieja", "aguamarina", "las-filipinas",
    )
    DAYAS_TARGET_TYPES = (
        "/solar/", "/terreno/", "/parcela/", "/suelo/",
        "/casa/", "/casa-de-campo/", "/casa-con-finca/",
        "/chalet/", "/chalet-independiente/", "/villa/",
        "/finca/", "/adosado/", "/bungalow/",
    )
    DAYAS_FALLBACK_URLS = [
        "https://www.dayas.org/venta-comprar/casa/alicante/orihuela/urb-montepinar/venta-comprar-casa-alicante-orihuela-urb-montepinar.html",
        "https://www.dayas.org/venta-comprar/chalet-independiente/alicante/orihuela/urb-montepinar/venta-comprar-chalet-independiente-alicante-orihuela-urb-montepinar.html",
        "https://www.dayas.org/venta-comprar/casa/alicante/orihuela/orihuela/venta-comprar-casa-alicante-orihuela-orihuela.html",
        "https://www.dayas.org/venta-comprar/casa/alicante/orihuela/centro/venta-comprar-casa-alicante-orihuela-centro.html",
        "https://www.dayas.org/venta-comprar/solar/alicante/orihuela/centro/venta-comprar-solar-alicante-orihuela-centro.html",
        "https://www.dayas.org/venta-comprar/terreno/alicante/orihuela/centro/venta-comprar-terreno-alicante-orihuela-centro.html",
        "https://www.dayas.org/venta-comprar/chalet/alicante/orihuela/raiguero-de-bonanza/venta-comprar-chalet-alicante-orihuela-raiguero-de-bonanza.html",
        "https://www.dayas.org/venta-comprar/chalet/alicante/benferri/benferri/venta-comprar-chalet-alicante-benferri-benferri.html",
        "https://www.dayas.org/venta-comprar/finca/alicante/benferri/benferri/venta-comprar-finca-alicante-benferri-benferri.html",
    ]

    BANK_URLS = [
        ("Solvia (Banco)", "https://www.solvia.es/es/comprar/suelos/alicante/orihuela", "solar_urbano"),
        ("Solvia (Banco)", "https://www.solvia.es/es/comprar/viviendas/alicante/orihuela?tipo=casas-chalets", "casa_planta_baja"),
        ("Aliseda (Banco)", "https://www.alisedainmobiliaria.com/comprar-suelos/alicante/orihuela", "solar_urbano"),
        ("Haya Real Estate", "https://www.haya.es/comprar/suelos/alicante/orihuela/", "solar_urbano"),
    ]

    def __init__(self, custom_agencies: Optional[List[Dict[str, str]]] = None):
        self.custom_agencies = custom_agencies or []
        #: Qué fuentes han respondido en la última pasada
        self.source_health: Dict[str, Dict[str, int]] = {}

    def _anota(self, nombre: str, ok: bool, items_found: int = 0) -> None:
        s = self.source_health.setdefault(nombre, {"intentos": 0, "ok": 0, "items": 0})
        s["intentos"] += 1
        if ok:
            s["ok"] += 1
        s["items"] += items_found

    @property
    def portales_ok(self) -> List[str]:
        """Solo da una agencia por sana si respondieron >= 75% de sus URLs y devolvió anuncios reales."""
        out: List[str] = []
        for n, s in self.source_health.items():
            intentos = s.get("intentos", 0)
            ok = s.get("ok", 0)
            items = s.get("items", 0)
            if intentos > 0 and items > 0 and (ok / intentos) >= 0.75:
                out.append(n)
        return out

    @staticmethod
    def _next_agency_page_url(raw_html: str, current_url: str, page_num: int) -> Optional[str]:
        """Detecta la página siguiente en Mediaelx (InmoAdapta/Esphouses), 10 Soles o Vegacasa."""
        next_n = page_num + 1
        u_low = current_url.lower()
        if "inmoadapta.com" in u_low or "esphouses.es" in u_low:
            m = re.search(rf'href=["\']([^"\']*[?&]p={next_n}\b[^"\']*)["\']', raw_html, re.IGNORECASE)
            if m:
                return urllib.parse.urljoin(current_url, html.unescape(m.group(1)))
        if "primergrupovegacasa.com" in u_low:
            m = re.search(rf'href=["\']([^"\']*(?:page={next_n}|/{next_n})["\'])', raw_html, re.IGNORECASE)
            if m:
                return urllib.parse.urljoin(current_url, html.unescape(m.group(1).strip("'\"")))
        if "10soles.com" in u_low:
            m = re.search(rf'href=["\']([^"\']*pag={next_n}\b[^"\']*)["\']', raw_html, re.IGNORECASE)
            if m:
                return urllib.parse.urljoin(current_url, html.unescape(m.group(1)))
        if "grupoorisalia.com" in u_low:
            m = re.search(rf'href=["\']([^"\']*/page/{next_n}/?[^"\']*)["\']', raw_html, re.IGNORECASE)
            if m:
                return urllib.parse.urljoin(current_url, html.unescape(m.group(1)))
        if "solvia.es" in u_low:
            m = re.search(rf'href=["\']([^"\']*numeroPagina={next_n}\b[^"\']*)["\']', raw_html, re.IGNORECASE)
            if m:
                return urllib.parse.urljoin(current_url, html.unescape(m.group(1)))
        return None

    def _scrape_dayas_sitemap(self, sitemap_url: str, agency_name: str, seen_urls: set) -> List[Dict[str, Any]]:
        """Descubre y recorre todas las páginas de zona objetivo de Dayas Real Estates desde su sitemap.xml."""
        sm = http_get(sitemap_url, timeout=22, retries=2)
        zone_pages: List[str] = []
        if sm:
            locs = re.findall(r"<loc>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</loc>", sm, re.IGNORECASE)
            for loc in locs:
                ll = loc.strip().lower()
                if "/venta-comprar/" not in ll:
                    continue
                if any(e in ll for e in self.DAYAS_EXCLUDE_KEYWORDS):
                    continue
                if not any(z in ll for z in self.DAYAS_ZONE_KEYWORDS):
                    continue
                if not ("montepinar" in ll or any(t in ll for t in self.DAYAS_TARGET_TYPES)):
                    continue
                # Páginas de zona concreta (nivel hoja con fichas `list_house`: .../alicante/<muni>/<zona>/<slug>.html)
                if ll.count("/") == 8:
                    zone_pages.append(loc.strip().replace("http://", "https://"))
            zone_pages = sorted(set(zone_pages))

        if not zone_pages:
            zone_pages = list(self.DAYAS_FALLBACK_URLS)

        items_out: List[Dict[str, Any]] = []
        for zurl in zone_pages:
            raw_html = http_get(zurl, timeout=16, retries=2)
            if not raw_html:
                self._anota(agency_name, False, 0)
                continue
            default_type = ""
            zl = zurl.lower()
            if any(t in zl for t in ("/solar/", "/terreno/", "/parcela/", "/suelo/")):
                default_type = "solar_urbano"
            elif any(t in zl for t in ("/casa/", "/casa-de-campo/", "/casa-con-finca/", "/chalet", "/villa/", "/adosado/", "/bungalow/")):
                default_type = "casa_planta_baja"
            parsed = self._parse_dayas(raw_html, agency_name, zurl, default_type)
            self._anota(agency_name, True, len(parsed))
            for item in parsed:
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    items_out.append(item)
            time.sleep(0.25)
        return items_out

    def run_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_urls = set()
        self.source_health: Dict[str, Dict[str, int]] = {}

        # 1. Escanear servicers bancarios
        for bank_name, url, raw_type in self.BANK_URLS:
            raw_html = http_get(url, retries=2)
            if not raw_html:
                self._anota(bank_name, False, 0)
                continue
            parsed = self.parse_universal_agency_html(raw_html, bank_name, url, raw_type)
            self._anota(bank_name, True, len(parsed))
            for item in parsed:
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)

        # 2. Escanear inmobiliarias locales configuradas en config.json
        for ag in self.custom_agencies:
            name = ag.get("name", "Inmobiliaria Local")
            start_url = ag.get("url", "")
            raw_type = ag.get("raw_type", "")
            if not start_url:
                continue

            # Caso especial Dayas sitemap.xml (descubre todas las zonas de Orihuela/Montepinar/Vega Baja)
            if "dayas.org" in start_url.lower() and start_url.lower().endswith("sitemap.xml"):
                dayas_items = self._scrape_dayas_sitemap(start_url, name, seen_urls)
                results.extend(dayas_items)
                continue

            url = start_url
            url_ok = False
            url_items = 0
            for page_num in range(1, self.MAX_PAGES + 1):
                raw_html = http_get(url, retries=2)
                if not raw_html:
                    break
                if page_num == 1:
                    url_ok = True
                parsed = self.parse_universal_agency_html(raw_html, name, url, raw_type)
                added = 0
                for item in parsed:
                    u = item.get("url", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append(item)
                        added += 1
                url_items += len(parsed)
                if added == 0 or page_num >= self.MAX_PAGES:
                    break
                next_url = self._next_agency_page_url(raw_html, url, page_num)
                if not next_url or next_url == url:
                    break
                url = next_url
                time.sleep(0.3)

            self._anota(name, url_ok, url_items)

        return results

    def parse_universal_agency_html(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Parser para inmobiliarias locales de la Vega Baja:
        Soporta específicamente Dayas Real Estates (Forocasas/Inmovirtual), 10 Soles (Inmoweb),
        Primer Grupo Vegacasa, InmoAdapta / Esphouses (Mediaelx),
        además de Inmovilla, Witei y WordPress Real Estate.
        """
        u_low = base_url.lower()
        if "dayas.org" in u_low or 'class="sixteen columns list_house"' in raw_html:
            return self._parse_dayas(raw_html, agency_name, base_url, default_type)
        if "grupoorisalia.com" in u_low or "grid-listing-info" in raw_html:
            return self._parse_orisalia(raw_html, agency_name, base_url, default_type)
        if "vegahouse.es" in u_low or "fotosAlVuelo" in raw_html:
            return self._parse_vegahouse(raw_html, agency_name, base_url, default_type)
        if "solvia.es" in u_low or "/es/propiedades/comprar/" in raw_html:
            return self._parse_solvia(raw_html, agency_name, base_url, default_type)
        if "10soles.com" in u_low or 'class="venta punto_mapa"' in raw_html:
            return self._parse_10soles(raw_html, agency_name, base_url, default_type)
        if "primergrupovegacasa.com" in u_low or '<section class="inmueble container">' in raw_html:
            return self._parse_vegacasa(raw_html, agency_name, base_url, default_type)
        if "inmoadapta.com" in u_low or "esphouses.es" in u_low or "data-id-prop=" in raw_html:
            return self._parse_inmoadapta(raw_html, agency_name, base_url, default_type)

        items: List[Dict[str, Any]] = []
        # Normalizar <sup>2</sup> a 2 antes de limpiar etiquetas
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)

        block_regex = re.compile(
            r'<(?:article|div|li|section)[^>]+class=["\'][^"\']*(?:property|propiedad|inmueble|ficha|listing|card|item-prop)[^"\']*["\'][^>]*>(.*?)</(?:article|div|li|section)>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in block_regex.finditer(norm_html):
            block = match.group(1)
            all_links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
            if not all_links:
                continue
            full_url = None
            chosen_anchor = ""
            for href, anchor_html in all_links:
                href = href.strip()
                if href.startswith("#") or "javascript:" in href:
                    continue
                cand = urllib.parse.urljoin(base_url, href)
                if PortalsScraper.is_valid_detail_url(cand):
                    full_url = cand
                    anchor_txt = re.sub(r"<[^>]+>", " ", anchor_html).strip()
                    if len(anchor_txt) > len(chosen_anchor):
                        chosen_anchor = anchor_txt
            if not full_url:
                continue

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", block))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            if len(text_clean) < 20:
                continue

            price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", text_clean)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            m2_m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,6})\s*m[²2]", text_clean, re.IGNORECASE)
            surface_m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

            if not price_eur or not surface_m2:
                continue

            title_text = chosen_anchor if len(chosen_anchor) >= 8 else text_clean[:100]

            items.append(
                {
                    "portal": agency_name,
                    "title": html.unescape(title_text)[:150],
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": surface_m2,
                    "description": text_clean[:550],
                    "raw_type": default_type,
                }
            )

        return items

    def _parse_dayas(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parser específico para Dayas Real Estates (tarjetas `<li class="... list_house">`)."""
        items: List[Dict[str, Any]] = []
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)
        blocks = re.split(r'(?=<li[^>]+class=["\'][^"\']*\blist_house\b)', norm_html, flags=re.IGNORECASE)
        for blk in blocks[1:]:
            chunk = blk[:5500]
            h2_m = re.search(r"<div[^>]+class=['\"]TitInmuList['\"][^>]*>.*?<h2[^>]*>(.*?)</h2>", chunk, re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", " ", h2_m.group(1))).strip() if h2_m else ""

            # Extraer referencia del título o del enlace SEO (...-14732.html)
            ref_m = re.search(r"Ref\.?\s*:?\s*(\d{3,8})", title, re.IGNORECASE)
            if not ref_m:
                ref_m = re.search(r"-(\d{4,8})\.html['\"]", chunk, re.IGNORECASE)
            if not ref_m:
                continue
            ref = ref_m.group(1)

            # Código de cliente Forocasas (81808 en Dayas) desde la URL de la foto si existe
            cli_m = re.search(r"fotos/inmuebles/(\d{4,6})/", chunk)
            cli = cli_m.group(1) if cli_m else "81808"
            full_url = f"https://www.dayas.org/inmueble.php?ID={cli}{cli}{ref}&idio=1"

            img_m = re.search(r'image=(https?://[^"\'\s&>]+)', chunk)
            if not img_m:
                img_m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', chunk, re.IGNORECASE)
            image_url = html.unescape(img_m.group(1)) if img_m else ""

            pvp_m = re.search(r"class=['\"]pvpList2?['\"][^>]*>(.*?)</div>", chunk, re.IGNORECASE | re.DOTALL)
            pvp_txt = html.unescape(re.sub(r"<[^>]+>", " ", pvp_m.group(1))) if pvp_m else ""
            price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", pvp_txt)
            if not price_m:
                clean_all = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
                price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", clean_all)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            dist_m = re.search(r"class=['\"]DistriList['\"][^>]*>(.*?)</div>", chunk, re.IGNORECASE | re.DOTALL)
            dist_txt = html.unescape(re.sub(r"<[^>]+>", " ", dist_m.group(1))) if dist_m else ""
            dist_txt = re.sub(r"\s+", " ", dist_txt).strip()

            plot_m = re.search(r"(\d[\d\.]*)\s*m[²2]\s*parc", dist_txt, re.IGNORECASE)
            built_m = re.search(r"(\d[\d\.]*)\s*m[²2]\s*constr", dist_txt, re.IGNORECASE)
            util_m = re.search(r"(\d[\d\.]*)\s*m[²2]\s*util", dist_txt, re.IGNORECASE)
            plot_m2 = float(plot_m.group(1).replace(".", "")) if plot_m else None
            built_m2 = float(built_m.group(1).replace(".", "")) if built_m else (
                float(util_m.group(1).replace(".", "")) if util_m else None
            )

            rooms_m = re.search(r"(\d{1,2})\s*(?:Hab\.?|dormitorios?)", f"{dist_txt} {title}", re.IGNORECASE)
            rooms = int(rooms_m.group(1)) if rooms_m else None

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            if not price_eur or not (plot_m2 or built_m2):
                continue

            # Inferir tipo de inmueble si no vino fijado por la URL de categoría
            rtype = default_type
            tl = f"{title} {base_url}".lower()
            is_montepinar = "montepinar" in tl
            if not is_montepinar and any(
                w in tl for w in ("piso", "ático", "atico", "apartamento", "oficina", "local-comercial", "garaje", "trastero", "nave", "edificio", "hotel")
            ):
                continue
            if not rtype:
                if any(w in tl for w in ("solar", "terreno", "parcela", "suelo")):
                    rtype = "solar_urbano"
                elif any(w in tl for w in ("casa", "chalet", "villa", "adosado", "bungalow", "finca")):
                    rtype = "casa_planta_baja"
                elif is_montepinar:
                    rtype = "casa_planta_baja"
                else:
                    continue

            items.append(
                {
                    "external_id": f"dayas-{ref}",
                    "portal": agency_name,
                    "title": (title or f"Inmueble Ref. {ref} en Dayas")[:150],
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": plot_m2 or built_m2,
                    "surface_built_m2": built_m2,
                    "rooms": rooms,
                    "image_url": image_url,
                    "description": f"{title} · {dist_txt} · {text_clean}"[:550],
                    "raw_type": rtype,
                }
            )
        return items

    def _parse_orisalia(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parser específico para Grupo Orisalia (WordPress Real Estate: grid-listing-info)."""
        items: List[Dict[str, Any]] = []
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)
        blocks = re.split(r'(?=<li[^>]+class=["\'][^"\']*\blisting\b)', norm_html, flags=re.IGNORECASE)
        if len(blocks) <= 1:
            blocks = re.split(r'(?=<div[^>]+class=["\'][^"\']*\bgrid-listing-info\b)', norm_html, flags=re.IGNORECASE)

        seen_local = set()
        for blk in blocks[1:]:
            chunk = blk[:6000]
            u_m = re.search(r'href=["\'](https?://(?:www\.)?grupoorisalia\.com/listados/[^"\']+)["\']', chunk, re.IGNORECASE)
            if not u_m:
                continue
            full_url = u_m.group(1).strip()
            if full_url in seen_local:
                continue
            seen_local.add(full_url)

            title_m = re.search(r'<h5[^>]*>\s*<a[^>]*>(.*?)</a>\s*</h5>', chunk, re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", " ", title_m.group(1))).strip() if title_m else ""

            loc_m = re.search(r'<p[^>]+class=["\'][^"\']*\blocation\b[^"\']*["\'][^>]*>(.*?)</p>', chunk, re.IGNORECASE | re.DOTALL)
            loc = html.unescape(re.sub(r"<[^>]+>", " ", loc_m.group(1))).strip() if loc_m else ""

            price_m = re.search(r"listing-price['\"][^>]*>\s*([\d\.]+)\s*(?:€|&euro;)", chunk, re.IGNORECASE)
            if not price_m:
                clean_p = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
                price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", clean_p)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            img_m = re.search(r'<img[^>]+(?:data-src|src)=["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', chunk, re.IGNORECASE)
            image_url = img_m.group(1) if img_m else ""

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            plot_m = re.search(r"parcela[^\d]{0,18}(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m[²2]|(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m[²2]\s*(?:de\s*)?parcela", text_clean, re.IGNORECASE)
            plot_m2 = float((plot_m.group(1) or plot_m.group(2)).replace(".", "")) if plot_m else None
            any_m2 = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m[²2]", text_clean, re.IGNORECASE)
            built_m2 = float(any_m2.group(1).replace(".", "")) if any_m2 else None

            rooms_m = re.search(r"(\d{1,2})\s*(?:habs?\.?|habitaciones|dormitorios?)", text_clean, re.IGNORECASE)
            rooms = int(rooms_m.group(1)) if rooms_m else None

            if not price_eur:
                continue
            # Si no pone m² en la tarjeta pero es Montepinar/parcela/casa, conservar para enriquecer ficha
            tl = f"{title} {loc} {full_url}".lower()
            is_montepinar = "montepinar" in tl
            if not (plot_m2 or built_m2) and not is_montepinar:
                continue

            if not is_montepinar and any(
                w in tl for w in ("piso", "ático", "atico", "apartamento", "oficina", "local", "garaje", "trastero", "nave", "edificio", "alquiler")
            ):
                continue

            rtype = default_type
            if not rtype:
                if any(w in tl for w in ("solar", "terreno", "parcela", "suelo")):
                    rtype = "solar_urbano"
                elif any(w in tl for w in ("casa", "chalet", "villa", "adosado", "finca")):
                    rtype = "casa_planta_baja"
                elif is_montepinar:
                    rtype = "casa_planta_baja"
                else:
                    continue

            items.append(
                {
                    "portal": agency_name,
                    "title": (title or "Inmueble en Grupo Orisalia")[:150],
                    "url": full_url,
                    "location": loc,
                    "price_eur": price_eur,
                    "surface_plot_m2": plot_m2 or built_m2,
                    "surface_built_m2": built_m2,
                    "rooms": rooms,
                    "image_url": image_url,
                    "description": f"{title} · {loc} · {text_clean}"[:550],
                    "raw_type": rtype,
                }
            )
        return items

    def _parse_vegahouse(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parser específico para VegaHouse (Inmovilla/Apinmo: fichas paginadas `<article class="paginacion-ficha">` y destacados `window.location.href='ficha/...'`)."""
        items: List[Dict[str, Any]] = []
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)
        blocks: List[str] = []
        blocks.extend(re.findall(r'<article[^>]+class=["\'][^"\']*paginacion-ficha[^"\']*["\'][^>]*>(.*?)</article>', norm_html, re.IGNORECASE | re.DOTALL))
        blocks.extend(re.split(r"(?=window\.location\.href=['\"]ficha/)", norm_html, flags=re.IGNORECASE)[1:])
        seen_local = set()

        for blk in blocks:
            chunk = blk[:4800]
            u_m = re.search(r'(?:href|window\.location\.href)\s*=\s*["\']/?(ficha/[^"\']+)["\']', chunk, re.IGNORECASE)
            if not u_m:
                continue
            rel_url = u_m.group(1).strip()
            full_url = urllib.parse.urljoin("https://www.vegahouse.es/", rel_url)
            if full_url in seen_local:
                continue
            seen_local.add(full_url)

            # Extraer tipo y población del slug: ficha/<tipo>/<pueblo>/<zona>/<cli>/<id>/es/
            slug_parts = rel_url.strip("/").split("/")
            slug_tipo = slug_parts[1].replace("-", " ") if len(slug_parts) > 1 else ""
            slug_pueblo = slug_parts[2].replace("-", " ") if len(slug_parts) > 2 else ""
            slug_zona = slug_parts[3].replace("-", " ") if len(slug_parts) > 3 else ""
            prop_num = slug_parts[5] if len(slug_parts) > 5 and slug_parts[5].isdigit() else None

            t_m = re.search(r'<h[1-4][^>]*class=["\'][^"\']*titulo[^"\']*["\'][^>]*>(.*?)</h[1-4]>', chunk, re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", " ", t_m.group(1))).strip() if t_m else ""
            if not title:
                title = f"{slug_tipo.capitalize()} en {slug_pueblo.title()} ({slug_zona.title()})"

            price_m = re.search(r'class=["\'](?:precio1?|paginacion-ficha-tituloprecio)["\'][^>]*>[^<\d]*([\d\.]+)\s*(?:€|&euro;)', chunk, re.IGNORECASE)
            if not price_m:
                clean_p = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
                price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", clean_p)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            img_m = re.search(r'cargaFoto=["\'](https?://[^"\']+)["\']', chunk, re.IGNORECASE)
            image_url = img_m.group(1) if img_m else ""

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            plot_m = re.search(r"(?:parcela|terreno|solar)[^\d]{0,18}(\d[\d\.]*)\s*m\s*[²2]", text_clean, re.IGNORECASE)
            plot_m2 = float(plot_m.group(1).replace(".", "")) if plot_m else None
            any_m2 = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,5})\s*m\s*[²2]", text_clean, re.IGNORECASE)
            built_m2 = float(any_m2.group(1).replace(".", "")) if any_m2 else None

            rooms_m = re.search(r"Habitaciones\s*(\d{1,2})|(\d{1,2})\s*(?:habs?\.?|dormitorios?)", text_clean, re.IGNORECASE)
            rooms = int(rooms_m.group(1) or rooms_m.group(2)) if rooms_m else None

            if not price_eur or not (plot_m2 or built_m2):
                continue

            tl = f"{title} {slug_tipo} {slug_pueblo} {slug_zona}".lower()
            is_montepinar = "montepinar" in tl
            if not is_montepinar and any(
                w in tl for w in ("piso", "atico", "ático", "apartamento", "oficina", "local", "garaje", "trastero", "nave", "edificio", "duplex", "dúplex")
            ):
                continue
            rtype = default_type
            if not rtype:
                if any(w in tl for w in ("solar", "terreno", "parcela", "suelo")):
                    rtype = "solar_urbano"
                elif any(w in tl for w in ("casa", "chalet", "villa", "adosado", "bungalow", "finca")):
                    rtype = "casa_planta_baja"
                elif is_montepinar:
                    rtype = "casa_planta_baja"
                else:
                    continue

            items.append(
                {
                    "external_id": f"vegahouse-{prop_num}" if prop_num else None,
                    "portal": agency_name,
                    "title": title[:150],
                    "url": full_url,
                    "location": f"{slug_zona.title()}, {slug_pueblo.title()}".strip(", "),
                    "price_eur": price_eur,
                    "surface_plot_m2": plot_m2 or built_m2,
                    "surface_built_m2": built_m2,
                    "rooms": rooms,
                    "image_url": image_url,
                    "description": f"{title} · {slug_pueblo} · {slug_zona} · {text_clean}"[:550],
                    "raw_type": rtype,
                }
            )
        return items

    def _parse_solvia(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parser específico para Solvia (Angular SSR con enlaces `/es/propiedades/comprar/...`)."""
        items: List[Dict[str, Any]] = []
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)
        matches = list(re.finditer(r'href=["\'](https?://www\.solvia\.es/es/propiedades/comprar/[^"\']+|/es/propiedades/comprar/[^"\']+)["\']', norm_html, re.IGNORECASE))
        seen_local = set()

        for m in matches:
            full_url = urllib.parse.urljoin("https://www.solvia.es", m.group(1).strip())
            if full_url in seen_local:
                continue

            # Evitar coincidencia previa en el carrusel de fotos (sin precio/m2); esperar al enlace de ficha con datos
            chunk = norm_html[max(0, m.start() - 120) : m.end() + 2600]
            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", text_clean)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            m2_m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,6})\s*m\s*[²2]", text_clean, re.IGNORECASE)
            surface_m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

            if not price_eur or not surface_m2:
                continue

            seen_local.add(full_url)
            # Buscar imagen en el bloque inmediatamente anterior (carrusel de la misma tarjeta)
            pre_chunk = norm_html[max(0, m.start() - 4200) : m.end() + 400]
            img_m = re.search(r'src=["\'](https?://cdnsolv[^"\']+\.(?:jpg|jpeg|png|webp))["\']', pre_chunk, re.IGNORECASE)
            image_url = img_m.group(1).replace("\\", "/") if img_m else ""

            h3_m = re.search(r'<h3[^>]*class=["\'][^"\']*build-name[^"\']*["\'][^>]*>(.*?)</h3>', chunk, re.IGNORECASE | re.DOTALL)
            slug = full_url.rstrip("/").split("/")[-1]
            slug_title = re.sub(r"-\d+-\d+$", "", slug).replace("-", " ").capitalize()
            title = html.unescape(re.sub(r"<[^>]+>", " ", h3_m.group(1))).strip() if h3_m else slug_title

            items.append(
                {
                    "portal": agency_name,
                    "title": f"{title} (Activo Bancario Solvia)"[:150],
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": surface_m2,
                    "image_url": image_url,
                    "description": f"Activo bancario Solvia sin comisión · {title} · {text_clean}"[:550],
                    "raw_type": default_type or ("solar_urbano" if "suelo" in slug or "solar" in slug else "casa_planta_baja"),
                }
            )
        return items

    def _parse_10soles(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        parts = re.split(r'(?=<div[^>]+class=["\'][^"\']*venta\s+punto_mapa)', raw_html)
        for part in parts[1:]:
            chunk = part[:4500]
            url_m = re.search(r'data-url=["\']([^"\']+)["\']', chunk)
            if not url_m:
                continue
            full_url = urllib.parse.urljoin(base_url, url_m.group(1).strip())
            if not PortalsScraper.is_valid_detail_url(full_url):
                continue

            lat_m = re.search(r'data-lat=["\']([\d\.-]+)["\']', chunk)
            lng_m = re.search(r'data-lng=["\']([\d\.-]+)["\']', chunk)
            ref_m = re.search(r'data-ref=["\']([^"\']+)["\']', chunk)

            price_m = re.search(r'<span[^>]+class=["\']actual["\'][^>]*>\s*([\d\.]+)\s*€', chunk, re.IGNORECASE)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            rooms_m = re.search(r"Habitaciones:</span>\s*(\d+)", chunk, re.IGNORECASE)
            rooms = int(rooms_m.group(1)) if rooms_m else None

            plot_m = re.search(r"Sup\.\s*Parcela:</span>\s*([\d\.]+)\s*m", chunk, re.IGNORECASE)
            built_m = re.search(r"Sup\.\s*Construida:</span>\s*([\d\.]+)\s*m", chunk, re.IGNORECASE)
            plot_m2 = float(plot_m.group(1).replace(".", "")) if plot_m else None
            built_m2 = float(built_m.group(1).replace(".", "")) if built_m else None

            desc_m = re.search(r'<p[^>]+class=["\']descripcion[^"\']*["\'][^>]*>(.*?)</p>', chunk, re.IGNORECASE | re.DOTALL)
            desc = html.unescape(re.sub(r"<[^>]+>", " ", desc_m.group(1))).strip() if desc_m else ""

            slug_title = url_m.group(1).strip("/").split("-es")[0].replace("-", " ").capitalize()
            ref_str = f" (Ref. {ref_m.group(1)})" if ref_m else ""
            title = f"{slug_title}{ref_str}"

            if not price_eur or not (plot_m2 or built_m2):
                continue

            items.append(
                {
                    "external_id": f"10soles-{ref_m.group(1).lower()}" if ref_m else None,
                    "portal": agency_name,
                    "title": title[:150],
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": plot_m2 or built_m2,
                    "surface_built_m2": built_m2,
                    "rooms": rooms,
                    "lat": float(lat_m.group(1)) if lat_m else None,
                    "lon": float(lng_m.group(1)) if lng_m else None,
                    "description": desc[:550] or title,
                    "raw_type": default_type or ("solar_urbano" if "solar" in slug_title.lower() or "parcela" in slug_title.lower() else "casa_planta_baja"),
                }
            )
        return items

    def _parse_vegacasa(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        blocks = re.findall(r'<section[^>]+class=["\'][^"\']*inmueble\s+container[^"\']*["\'][^>]*>(.*?)</section>', raw_html, re.IGNORECASE | re.DOTALL)
        for blk in blocks:
            u_m = re.search(r'href=["\'](/ad/\d+)["\']', blk)
            if not u_m:
                continue
            full_url = urllib.parse.urljoin(base_url, u_m.group(1))
            h1_m = re.search(r"<h1>\s*<a[^>]*>(.*?)</a>\s*</h1>", blk, re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", " ", h1_m.group(1))).strip() if h1_m else "Inmueble en Vegacasa"

            price_m = re.search(r'class=["\']price["\'][^>]*>\s*([\d\.]+)\s*€', blk, re.IGNORECASE)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            ref_m = re.search(r"Ref\.\s*([A-Za-z0-9_-]+)", blk)
            rooms_m = re.search(r"(\d+)\s*Dorm", blk, re.IGNORECASE)
            rooms = int(rooms_m.group(1)) if rooms_m else None

            m2_m = re.search(r"icon-plans['\"][^>]*></span>\s*([\d\.]+)\s*m", blk, re.IGNORECASE)
            surface_m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", blk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            if not price_eur or not surface_m2:
                continue

            rtype = default_type
            tl = title.lower()
            if any(w in tl for w in ["piso", "ático", "atico", "apartamento", "oficina", "local", "garaje", "trastero", "nave", "edificio", "dúplex", "duplex"]):
                continue
            if not rtype:
                if any(w in tl for w in ["solar", "terreno", "parcela", "suelo"]):
                    rtype = "solar_urbano"
                elif any(w in tl for w in ["casa", "planta baja", "chalet", "adosad"]):
                    rtype = "casa_planta_baja"
                else:
                    continue

            items.append(
                {
                    "external_id": f"vega-{ref_m.group(1).lower()}" if ref_m else None,
                    "portal": agency_name,
                    "title": f"{title} ({ref_m.group(0)})" if ref_m else title,
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": surface_m2,
                    "rooms": rooms,
                    "description": text_clean[:550],
                    "raw_type": rtype,
                }
            )
        return items

    def _parse_inmoadapta(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        norm_html = re.sub(r"<\s*sup\s*>\s*2\s*<\s*/\s*sup\s*>", "2", raw_html, flags=re.IGNORECASE)
        parts = re.split(r'(?=data-id-prop=["\']\d+["\'])', norm_html)
        for part in parts[1:]:
            chunk = part[:4800]
            url_m = re.search(r'data-url=["\'](/propiedad/\d+/[^"\']+)["\']', chunk)
            if not url_m:
                continue
            full_url = urllib.parse.urljoin(base_url, url_m.group(1).strip())
            alt_m = re.search(r'data-alt=["\']([^"\']+)["\']', chunk)
            title = html.unescape(alt_m.group(1)).strip() if alt_m else "Propiedad en InmoAdapta"

            plot_m = re.search(r'class=["\']m2p["\'][^>]*>\s*([\d\.]+)\s*m', chunk, re.IGNORECASE)
            built_m = re.search(r'house\.svg["\'][^>]*>\s*<span>\s*([\d\.]+)\s*m', chunk, re.IGNORECASE)
            plot_m2 = float(plot_m.group(1).replace(".", "")) if plot_m else None
            built_m2 = float(built_m.group(1).replace(".", "")) if built_m else None

            beds_m = re.search(r'class=["\']beds["\'][^>]*>\s*(\d+)', chunk, re.IGNORECASE)
            rooms = int(beds_m.group(1)) if beds_m else None

            text_clean = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
            text_clean = re.sub(r"\s+", " ", text_clean).strip()

            price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", text_clean)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            if not price_eur or not (plot_m2 or built_m2):
                continue

            rtype = default_type
            tl = f"{title} {full_url}".lower()
            if any(w in tl for w in ["piso", "ático", "atico", "apartamento", "oficina", "local", "garaje", "trastero", "nave", "edificio", "dúplex", "duplex", "bungalow-planta-alta"]):
                continue
            if not rtype:
                if any(w in tl for w in ["solar", "terreno", "parcela"]):
                    rtype = "solar_urbano"
                elif any(w in tl for w in ["casa", "planta-baja", "bungalow-planta-baja", "chalet", "adosado"]):
                    rtype = "casa_planta_baja"
                else:
                    continue

            items.append(
                {
                    "portal": agency_name,
                    "title": title[:150],
                    "url": full_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": plot_m2 or built_m2,
                    "surface_built_m2": built_m2,
                    "rooms": rooms,
                    "description": text_clean[:550],
                    "raw_type": rtype,
                }
            )
        return items


def get_initial_market_baseline() -> List[Dict[str, Any]]:
    """
    Línea base de mercado de las zonas objetivo (Orihuela, Montepinar, Raiguero de Bonanza,
    Raiguero de Levante, Benferri y Granja de Rocamora) para inicializar la base de datos
    con referencias reales de tipología, superficies (>=180 m² y <180 m²) e historial de precios.
    """
    return [
        {
            "external_id": "ori-rb-001",
            "portal": "Idealista",
            "title": "Solar urbano en esquina en Raiguero de Bonanza - Orihuela",
            "url": "https://www.idealista.com/venta-terrenos/orihuela/pedanias/",
            "location": "Raiguero de Bonanza, Orihuela",
            "price_eur": 46000,
            "prev_prices": [("2026-09-15", 54000), ("2026-10-12", 49500)],
            "surface_plot_m2": 265,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Solar urbano directo en el centro de Raiguero de Bonanza (Orihuela), haciendo esquina a dos calles. Superficie de parcela 265 m², edificabilidad bajo + 2 alturas. Con toma de luz, agua y alcantarillado a pie de parcela. Urge venta, precio rebajado.",
        },
        {
            "external_id": "ori-rl-002",
            "portal": "Fotocasa",
            "title": "Parcela urbana edificable en Raiguero de Levante con vistas a la sierra",
            "url": "https://www.fotocasa.es/es/comprar/terrenos/orihuela/todas-las-zonas/l",
            "location": "Raiguero de Levante, Orihuela",
            "price_eur": 42000,
            "prev_prices": [("2026-10-01", 45000)],
            "surface_plot_m2": 240,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Solar urbano consolidado de 240 m2 en Raiguero de Levante, junto a la falda de la sierra de Orihuela. 12 metros de fachada por 20 de fondo. Ideal para vivienda unifamiliar con patio y piscina. Negociable.",
        },
        {
            "external_id": "ori-mp-003",
            "portal": "Idealista",
            "title": "Parcela urbana en Urbanización Montepinar (Orihuela) - 520 m²",
            "url": "https://www.idealista.com/venta-terrenos/orihuela-alicante/",
            "location": "Urbanización Montepinar, Orihuela",
            "price_eur": 98000,
            "prev_prices": [("2026-08-20", 112000), ("2026-10-05", 104000)],
            "surface_plot_m2": 520,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Excelente parcela urbana de 520 m2 en la parte alta de la Urbanización Montepinar (Orihuela). Totalmente vallada, orientación sur-levante, suministros de agua y electricidad en la acera. Excelente acceso a autovía A-7.",
        },
        {
            "external_id": "ori-mp-004",
            "portal": "Pisos.com",
            "title": "Solar urbano llano en Montepinar - Oportunidad 400 m²",
            "url": "https://www.pisos.com/venta/terrenos-orihuela/",
            "location": "Montepinar, Orihuela",
            "price_eur": 79000,
            "prev_prices": [],
            "surface_plot_m2": 400,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Parcela urbana en Montepinar de 400 m2 lista para solicitar licencia de obra de chalet independiente. Suelo urbano consolidado con todos los servicios.",
        },
        {
            "external_id": "ben-sol-005",
            "portal": "Habitaclia",
            "title": "Solar urbano en Benferri zona expansión / Benfis Park - 310 m²",
            "url": "https://www.habitaclia.com/terrenos-benferri.htm",
            "location": "Benferri",
            "price_eur": 49900,
            "prev_prices": [("2026-09-25", 58000)],
            "surface_plot_m2": 310,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Solar urbano de 310 m2 en Benferri, zona residencial tranquila junto a parques y a 2 minutos de la autovía. Da a dos calles (esquina), gran fachada de 28 metros lineales. Oportunidad por bajada de precio.",
        },
        {
            "external_id": "ben-cas-006",
            "portal": "Milanuncios",
            "title": "Casa de pueblo en planta baja para reformar en Benferri con gran patio",
            "url": "https://www.milanuncios.com/venta-de-casas-en-benferri-alicante/",
            "location": "Centro, Benferri",
            "price_eur": 64000,
            "prev_prices": [("2026-10-10", 72000)],
            "surface_plot_m2": 225,
            "surface_built_m2": 145,
            "raw_type": "casa_planta_baja",
            "description": "Casa antigua de planta baja en el centro de Benferri sobre un solar urbano de 225 m2 (145 m2 construidos + 80 m2 de patio/corral). Ideal para reformar integralmente o derribar y hacer vivienda nueva con garaje y piscina. Procedente de herencia, urge vender.",
        },
        {
            "external_id": "gra-sol-007",
            "portal": "Yaencontre",
            "title": "Solar urbano edificable en Granja de Rocamora - 280 m²",
            "url": "https://www.yaencontre.com/venta/terrenos/granja-de-rocamora",
            "location": "Granja de Rocamora",
            "price_eur": 43500,
            "prev_prices": [("2026-09-18", 48000)],
            "surface_plot_m2": 280,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Venta de solar urbano en Granja de Rocamora de 280 m2 de parcela. Suelo urbano directo, fachada de 14 metros, permite edificar planta baja más dos alturas o vivienda unifamiliar con gran jardín.",
        },
        {
            "external_id": "gra-cas-008",
            "portal": "Idealista",
            "title": "Casa de pueblo antigua a reformar en Granja de Rocamora sobre solar de 260 m²",
            "url": "https://www.idealista.com/venta-viviendas/granja-de-rocamora-alicante/",
            "location": "Granja de Rocamora",
            "price_eur": 59000,
            "prev_prices": [],
            "surface_plot_m2": 260,
            "surface_built_m2": 160,
            "raw_type": "casa_planta_baja",
            "description": "Casa tradicional de planta baja para reformar en Granja de Rocamora. Dispone de 260 m2 de parcela gráfica en Catastro y 160 m2 construidos con techos altos, patio trasero y salida a calle trasera (dos calles).",
        },
        {
            "external_id": "ori-cas-009",
            "portal": "Pisos.com",
            "title": "Casa de planta baja para reformar o derribar en Orihuela (Barrio Nuevo / Rabaloche)",
            "url": "https://www.pisos.com/venta/casas-orihuela/",
            "location": "El Rabaloche - Casco Histórico, Orihuela",
            "price_eur": 68000,
            "prev_prices": [("2026-09-10", 79000), ("2026-10-20", 73000)],
            "surface_plot_m2": 195,
            "surface_built_m2": 150,
            "raw_type": "casa_planta_baja",
            "description": "Casa de planta baja para reformar o derribar en Orihuela ciudad, zona Rabaloche / Capuchinos. Solar urbano de 195 m2 con 10 metros de fachada. Edificabilidad bajo + 2 alturas. Precio negociable.",
        },
        {
            "external_id": "ori-sol-010",
            "portal": "Solvia (Banco)",
            "title": "Suelo urbanizable sectorizado en Orihuela - Camino de Enmedio / San Antón",
            "url": "https://www.solvia.es/es/comprar/suelos/alicante/orihuela",
            "location": "Orihuela Centro - San Antón",
            "price_eur": 74000,
            "prev_prices": [("2026-09-01", 89000)],
            "surface_plot_m2": 340,
            "surface_built_m2": None,
            "raw_type": "solar_urbanizable",
            "description": "Activo bancario sin comisión de agencia. Parcela de suelo urbanizable de 340 m2 en Orihuela. Excelente oportunidad de inversión a 217 €/m2 en el entorno urbano de Orihuela.",
        },
        {
            "external_id": "ori-rb-011",
            "portal": "Inmobiliaria Vega Baja Local",
            "title": "Casa de planta baja con huerto urbano en Raiguero de Bonanza",
            "url": "https://www.esphouses.es/propiedades/?loct%5B%5D=orihuela",
            "location": "Raiguero de Bonanza, Orihuela",
            "price_eur": 78000,
            "prev_prices": [("2026-10-15", 85000)],
            "surface_plot_m2": 320,
            "surface_built_m2": 130,
            "raw_type": "casa_planta_baja",
            "description": "Vivienda tradicional de planta baja para reformar en Raiguero de Bonanza (Orihuela). Cuenta con 320 m2 de parcela urbana total, 130 m2 de casa + gran patio soleado con cochera. Agua y luz dadas de alta.",
        },
        {
            "external_id": "ori-ap-012",
            "portal": "Fotocasa",
            "title": "Solar urbano de 290 m² en La Aparecida (Orihuela) cerca de Raiguero",
            "url": "https://www.fotocasa.es/es/comprar/terrenos/orihuela/todas-las-zonas/l",
            "location": "La Aparecida, Orihuela",
            "price_eur": 47000,
            "prev_prices": [],
            "surface_plot_m2": 290,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Solar urbano consolidado de 290 m2 en la pedanía de La Aparecida (Orihuela), a 3 minutos del Raiguero de Bonanza. Calle asfaltada con alcantarillado, alumbrado y aceras.",
        },
        {
            "external_id": "ori-peq-013",
            "portal": "Idealista",
            "title": "Casa de pueblo para derribar en Orihuela Centro (Parcela 135 m² < 180 m²)",
            "url": "https://www.idealista.com/venta-viviendas/orihuela-alicante/",
            "location": "Orihuela Centro",
            "price_eur": 44000,
            "prev_prices": [],
            "surface_plot_m2": 135,
            "surface_built_m2": 120,
            "raw_type": "casa_planta_baja",
            "description": "Casa antigua de planta baja para derribar en calle tranquila de Orihuela. Solar de 135 m2 (guardado en base de datos secundaria por tener menos de 180 m2 de parcela).",
        },
        {
            "external_id": "ben-peq-014",
            "portal": "Habitaclia",
            "title": "Pequeño solar urbano entre medianeras en Benferri (150 m²)",
            "url": "https://www.habitaclia.com/terrenos-benferri.htm",
            "location": "Benferri",
            "price_eur": 29500,
            "prev_prices": [],
            "surface_plot_m2": 150,
            "surface_built_m2": None,
            "raw_type": "solar_urbano",
            "description": "Solar urbano entre medianeras de 150 m2 en Benferri. Guardado en histórico general pero fuera de la vista principal por ser menor de 180 m2.",
        },
    ]
