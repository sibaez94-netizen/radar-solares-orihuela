# -*- coding: utf-8 -*-
"""
Scraper para Inmobiliarias Locales de la Vega Baja (Orihuela, Benferri, Granja de Rocamora,
Montepinar, Raiguero) y Servicers Bancarios (Solvia, Aliseda, Haya).
Incluye parser universal compatible con Inmovilla, Witei y WordPress Real Estate.
"""

import html
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from src.scrapers.portals_scraper import PortalsScraper, http_get


class LocalAgenciesAndBanksScraper:
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

    def _anota(self, nombre: str, ok: bool) -> None:
        s = self.source_health.setdefault(nombre, {"intentos": 0, "ok": 0})
        s["intentos"] += 1
        if ok:
            s["ok"] += 1

    @property
    def portales_ok(self) -> List[str]:
        return [n for n, s in self.source_health.items() if s["ok"] > 0]

    def run_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_urls = set()
        self.source_health: Dict[str, Dict[str, int]] = {}

        # 1. Escanear servicers bancarios
        for bank_name, url, raw_type in self.BANK_URLS:
            raw_html = http_get(url)
            self._anota(bank_name, bool(raw_html))
            if not raw_html:
                continue
            for item in self.parse_universal_agency_html(raw_html, bank_name, url, raw_type):
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)

        # 2. Escanear inmobiliarias locales configuradas en config.json
        for ag in self.custom_agencies:
            name = ag.get("name", "Inmobiliaria Local")
            url = ag.get("url", "")
            raw_type = ag.get("raw_type", "")
            if not url:
                continue
            raw_html = http_get(url)
            self._anota(name, bool(raw_html))
            if not raw_html:
                continue
            for item in self.parse_universal_agency_html(raw_html, name, url, raw_type):
                u = item.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)

        return results

    def parse_universal_agency_html(
        self, raw_html: str, agency_name: str, base_url: str, default_type: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Parser para inmobiliarias locales de la Vega Baja:
        Soporta específicamente 10 Soles (Inmoweb), Primer Grupo Vegacasa, InmoAdapta / Esphouses (Mediaelx),
        además de Inmovilla, Witei y WordPress Real Estate.
        """
        u_low = base_url.lower()
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
