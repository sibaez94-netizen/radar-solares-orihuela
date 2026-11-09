# -*- coding: utf-8 -*-
"""
Scraper multi-portal para portales inmobiliarios nacionales + Descubrimiento indexado
(Idealista, Fotocasa, Milanuncios, Pisos.com, Habitaclia, Yaencontre, Trovimap).
Funciona con librería estándar (urllib) o con requests/curl_cffi si están instalados.
"""

import html
import json
import random
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


def http_get(url: str, timeout: int = 15, extra_headers: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Petición HTTP resiliente usando curl_cffi, requests o urllib.request."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    }
    if extra_headers:
        headers.update(extra_headers)

    # 1. Intentar curl_cffi si está disponible (imita TLS fingerprint de Chrome real en GitHub Actions)
    try:
        from curl_cffi import requests as creq  # type: ignore

        resp = creq.get(url, headers=headers, impersonate="chrome124", timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        pass

    # 2. Intentar requests estándar si está disponible
    try:
        import requests  # type: ignore

        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        pass

    # 3. Fallback a urllib.request de la librería estándar de Python
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(charset, errors="replace")
    except Exception:
        return None


class PortalsScraper:
    """
    Combina scraping directo de portales (Pisos.com, Habitaclia, Yaencontre, Trovimap)
    con búsqueda indexada para Idealista, Fotocasa y Milanuncios.
    """

    PORTAL_URLS = [
        # Pisos.com - Terrenos y Solares (Núcleo Urbano y Pedanías, sin Orihuela Costa)
        ("Pisos.com", "https://www.pisos.com/venta/terrenos-orihuela_nucleo_urbano/", "solar_urbano"),
        ("Pisos.com", "https://www.pisos.com/venta/terrenos-orihuela_pedanias/", "solar_urbano"),
        ("Pisos.com", "https://www.pisos.com/venta/terrenos-benferri/", "solar_urbano"),
        ("Pisos.com", "https://www.pisos.com/venta/terrenos-granja_de_rocamora/", "solar_urbano"),
        # Pisos.com - Casas de pueblo / planta baja / a reformar
        ("Pisos.com", "https://www.pisos.com/venta/casas-orihuela_nucleo_urbano/", "casa_planta_baja"),
        ("Pisos.com", "https://www.pisos.com/venta/casas-orihuela_pedanias/", "casa_planta_baja"),
        ("Pisos.com", "https://www.pisos.com/venta/casas-benferri/", "casa_planta_baja"),
        ("Pisos.com", "https://www.pisos.com/venta/casas-granja_de_rocamora/", "casa_planta_baja"),
        # Habitaclia
        ("Habitaclia", "https://www.habitaclia.com/terrenos-orihuela.htm", "solar_urbano"),
        ("Habitaclia", "https://www.habitaclia.com/terrenos-benferri.htm", "solar_urbano"),
        ("Habitaclia", "https://www.habitaclia.com/casas-orihuela.htm", "casa_planta_baja"),
        # Yaencontre
        ("Yaencontre", "https://www.yaencontre.com/venta/terrenos/orihuela", "solar_urbano"),
        ("Yaencontre", "https://www.yaencontre.com/venta/terrenos/benferri", "solar_urbano"),
        ("Yaencontre", "https://www.yaencontre.com/venta/terrenos/granja-de-rocamora", "solar_urbano"),
        ("Yaencontre", "https://www.yaencontre.com/venta/casas/orihuela/e-reformar", "casa_planta_baja"),
        # Trovimap
        ("Trovimap", "https://www.trovimap.com/venta-solar-orihuela", "solar_urbano"),
        ("Trovimap", "https://www.trovimap.com/venta-terreno-benferri", "solar_urbano"),
    ]

    SEARCH_DORKS = [
        # Idealista
        ("Idealista", 'site:idealista.com/inmueble "solar" "Orihuela"'),
        ("Idealista", 'site:idealista.com/inmueble "Montepinar" "Orihuela"'),
        ("Idealista", 'site:idealista.com/inmueble "Raiguero" "Orihuela"'),
        ("Idealista", 'site:idealista.com/inmueble "Benferri" solar OR terreno OR reformar'),
        ("Idealista", 'site:idealista.com/inmueble "Granja de Rocamora" solar OR terreno OR casa'),
        ("Idealista", 'site:idealista.com/inmueble "planta baja" "reformar" "Orihuela"'),
        # Fotocasa
        ("Fotocasa", 'site:fotocasa.es "terreno" "Orihuela"'),
        ("Fotocasa", 'site:fotocasa.es "Benferri" terreno OR solar OR reformar'),
        ("Fotocasa", 'site:fotocasa.es "Granja de Rocamora" terreno OR solar OR casa'),
        # Milanuncios
        ("Milanuncios", 'site:milanuncios.com "solar" "Orihuela"'),
        ("Milanuncios", 'site:milanuncios.com "Raiguero" OR "Montepinar" OR "Benferri" solar'),
    ]

    def run_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_urls = set()

        for portal_name, url, raw_type in self.PORTAL_URLS:
            page_html = http_get(url)
            if not page_html:
                continue
            parsed = self.parse_portal_html(page_html, portal_name=portal_name, base_url=url, raw_type=raw_type)
            for item in parsed:
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)
            time.sleep(0.4)

        # Ejecutar descubrimiento indexado para Idealista / Fotocasa / Milanuncios
        for portal_name, query in self.SEARCH_DORKS:
            dork_items = self.search_indexed_listings(query, portal_name)
            for item in dork_items:
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)
            time.sleep(0.5)

        return results

    def parse_portal_html(
        self, raw_html: str, portal_name: str, base_url: str, raw_type: str = "solar_urbano"
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        # 1. Dividir por tarjetas completas de anuncio (Pisos.com usa <div ... class="ad-preview" data-lnk-href="...">)
        if "ad-preview" in raw_html:
            parts = re.split(r'(?=<div[^>]+class=["\'][^"\']*\bad-preview\b)', raw_html)
            for part in parts[1:]:
                card = self._parse_card_block(part[:8000], portal_name, base_url, raw_type)
                if card:
                    items.append(card)

        # 2. Habitaclia / Yaencontre / Trovimap (<article ...> o bloques de listado)
        for m in re.finditer(r"<article[^>]*>(.*?)</article>", raw_html, re.IGNORECASE | re.DOTALL):
            card = self._parse_card_block(m.group(1), portal_name, base_url, raw_type)
            if card:
                items.append(card)

        return items

    def _extract_from_jsonld(
        self, data: Any, portal_name: str, base_url: str, raw_type: str
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for el in data:
                out.extend(self._extract_from_jsonld(el, portal_name, base_url, raw_type))
            return out
        if not isinstance(data, dict):
            return out

        if "itemListElement" in data and isinstance(data["itemListElement"], list):
            for el in data["itemListElement"]:
                out.extend(self._extract_from_jsonld(el, portal_name, base_url, raw_type))

        item_obj = data.get("item") if isinstance(data.get("item"), dict) else data
        name = item_obj.get("name") or item_obj.get("headline")
        url = item_obj.get("url") or data.get("url")
        if name and url:
            full_url = urllib.parse.urljoin(base_url, str(url))
            if not self.is_valid_detail_url(full_url):
                return out
            desc = item_obj.get("description") or ""
            offers = item_obj.get("offers") or {}
            if isinstance(offers, list) and offers:
                offers = offers[0]
            price = offers.get("price") if isinstance(offers, dict) else None

            out.append(
                {
                    "portal": portal_name,
                    "title": html.unescape(str(name)),
                    "url": full_url,
                    "price_eur": float(price) if price and str(price).replace(".", "").isdigit() else None,
                    "description": html.unescape(str(desc)),
                    "raw_type": raw_type,
                }
            )
        return out

    @staticmethod
    def is_valid_detail_url(url: str) -> bool:
        """
        Verifica que la URL apunte a una ficha concreta de un anuncio (con ID o slug de inmueble)
        y NO a una página general de búsqueda, listado por municipio o perfil de inmobiliaria.
        """
        u = url.lower().split("?")[0].rstrip("/")
        # Descartar perfiles de agencia, listados generales o páginas de categoría
        bad_fragments = [
            "/inmobiliaria/",
            "/inmobiliarias/",
            "/agencia/",
            "/venta/terrenos-",
            "/venta/casas-",
            "/venta-terrenos/",
            "/venta-viviendas/",
            "/todas-las-zonas/",
            "/alquiler",
            "javascript:",
            "mailto:",
            "tel:",
        ]
        if any(b in u for b in bad_fragments):
            return False
        if re.search(r"habitaclia\.com/(?:terrenos|casas|viviendas)-[a-z0-9_-]+\.htm$", u):
            return False

        # Patrones de ficha individual de anuncio por portal e inmobiliarias locales
        good_patterns = [
            r"pisos\.com/comprar/[^/]+-\d+",
            r"habitaclia\.com/comprar-[^/]+-i\d+\.htm",
            r"yaencontre\.com/venta/[^/]+/[^/]+/inmueble-\d+",
            r"yaencontre\.com/venta/(?:terrenos|casas|chalets)/inmueble-",
            r"idealista\.com/inmueble/\d+",
            r"fotocasa\.es/.*/comprar/(?:terreno|vivienda|casa|edificio)/[^/]+/\d+",
            r"milanuncios\.com/[^/]+-\d+\.htm",
            r"trovimap\.com/inmueble/",
            r"solvia\.es/es/comprar/.*/[a-z0-9-]+-\d+",
            r"alisedainmobiliaria\.com/inmueble/",
            r"haya\.es/.*/\d+",
            r"esphouses\.es/propiedad/",
            r"inmoadapta\.com/propiedad/\d+/",
            r"primergrupovegacasa\.com/ad/\d+",
            r"10soles\.com/[a-z0-9-]+-es\d+\.html",
        ]
        if any(re.search(p, u) for p in good_patterns):
            return True

        # Fallback: si la URL tiene un identificador numérico de al menos 5 dígitos al final o en el slug
        return bool(re.search(r"\d{5,}", u))

    def _parse_card_block(
        self, block: str, portal_name: str, base_url: str, raw_type: str
    ) -> Optional[Dict[str, Any]]:
        chosen_url = None
        chosen_anchor = ""

        # 1. Comprobar atributo data-lnk-href de Pisos.com
        lnk_m = re.search(r'data-lnk-href=["\']([^"\']+)["\']', block, re.IGNORECASE)
        if lnk_m:
            cand = urllib.parse.urljoin(base_url, lnk_m.group(1).strip())
            if self.is_valid_detail_url(cand):
                chosen_url = cand

        # 2. Buscar todos los enlaces dentro de la tarjeta y quedarse con el que apunte a la ficha del anuncio
        all_links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
        for href, anchor_html in all_links:
            href = href.strip()
            if href.startswith("#") or "javascript:" in href:
                continue
            cand_url = urllib.parse.urljoin(base_url, href)
            if self.is_valid_detail_url(cand_url):
                if not chosen_url:
                    chosen_url = cand_url
                anchor_txt = re.sub(r"<[^>]+>", " ", anchor_html).strip()
                if len(anchor_txt) > len(chosen_anchor):
                    chosen_anchor = anchor_txt

        if not chosen_url:
            return None

        full_url = chosen_url
        text_clean = html.unescape(re.sub(r"<[^>]+>", " ", block))
        text_clean = re.sub(r"\s+", " ", text_clean).strip()

        title_m = re.search(
            r'<(?:a|h2|h3|span)[^>]+class=["\'][^"\']*(?:title|heading|ad-preview__title)[^"\']*["\'][^>]*>(.*?)</(?:a|h2|h3|span)>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        raw_title = re.sub(r"<[^>]+>", " ", title_m.group(1) if title_m else chosen_anchor).strip()
        if len(raw_title) < 6:
            raw_title = text_clean[:95]

        price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", text_clean)
        price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

        m2_m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,6})\s*m[²2]", text_clean, re.IGNORECASE)
        surface_m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

        rooms_m = re.search(r"(\d{1,2})\s*(?:habs?\.?|habitaciones|dorms?\.?)", text_clean, re.IGNORECASE)
        rooms = int(rooms_m.group(1)) if rooms_m else None

        if not price_eur or not surface_m2:
            return None

        return {
            "portal": portal_name,
            "title": html.unescape(raw_title)[:150],
            "url": full_url,
            "price_eur": price_eur,
            "surface_plot_m2": surface_m2,
            "rooms": rooms,
            "description": text_clean[:550],
            "raw_type": raw_type,
        }

    def search_indexed_listings(self, query: str, portal_name: str) -> List[Dict[str, Any]]:
        """
        Consulta el índice web (DuckDuckGo HTML) para descubrir anuncios públicos
        de Idealista, Fotocasa y Milanuncios sin chocar con DataDome.
        """
        encoded_q = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        raw = http_get(search_url, timeout=12)
        if not raw:
            return []

        found: List[Dict[str, Any]] = []
        result_blocks = re.findall(
            r'<div[^>]+class=["\'][^"\']*result__body[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        for blk in result_blocks:
            a_m = re.search(
                r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                blk,
                re.IGNORECASE | re.DOTALL,
            )
            if not a_m:
                continue
            raw_href = html.unescape(a_m.group(1))
            if "uddg=" in raw_href:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                real_url = urllib.parse.unquote(qs.get("uddg", [raw_href])[0])
            else:
                real_url = raw_href

            if not self.is_valid_detail_url(real_url):
                continue

            title = html.unescape(re.sub(r"<[^>]+>", " ", a_m.group(2))).strip()
            snippet = html.unescape(re.sub(r"<[^>]+>", " ", blk))
            snippet = re.sub(r"\s+", " ", snippet).strip()

            full_txt = f"{title} {snippet}"
            price_m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*(?:€|eur|euros)", full_txt, re.IGNORECASE)
            price_eur = float(price_m.group(1).replace(".", "")) if price_m else None

            m2_m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,6})\s*m[²2]", full_txt, re.IGNORECASE)
            surface_m2 = float(m2_m.group(1).replace(".", "")) if m2_m else None

            found.append(
                {
                    "portal": portal_name,
                    "title": title[:160],
                    "url": real_url.split("?")[0],
                    "price_eur": price_eur,
                    "surface_plot_m2": surface_m2,
                    "description": snippet[:500],
                }
            )
        return found
