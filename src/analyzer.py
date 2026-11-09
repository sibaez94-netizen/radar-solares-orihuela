# -*- coding: utf-8 -*-
"""
Motor de análisis inmobiliario para Orihuela, Pedanías y Vega Baja.
Clasifica activos (solar urbano, solar urbanizable, casa de planta baja/pueblo a reformar),
detecta pedanías exactas (Montepinar, Raiguero de Bonanza, Raiguero de Levante, Benferri,
Granja de Rocamora, Orihuela Casco...), extrae superficies (incluyendo conversión de tahúllas)
y calcula el Chollo Score (0-100).
"""

import hashlib
import json
import math
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

TAHULLA_M2 = 1118.0  # 1 tahúlla en la Vega Baja / Orihuela equivale aprox. a 1.118 m²


def normalize_text(text: str) -> str:
    """Convierte a minúsculas y elimina tildes/diacríticos para búsqueda robusta."""
    if not text:
        return ""
    text = str(text).lower()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    if not config_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class PropertyAnalyzer:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.zones = self.config.get("zones", {})
        self.filters = self.config.get("filters", {})
        self.excluded_costa = [
            normalize_text(k) for k in self.config.get("excluded_costa_keywords", [])
        ]

    def is_orihuela_costa(self, full_text: str) -> bool:
        norm = normalize_text(full_text)
        for kw in self.excluded_costa:
            if kw and kw in norm:
                return True
        return False

    def detect_zone(self, title: str, description: str, location_raw: str, url: str = "") -> Tuple[str, str, int, float, float]:
        """
        Devuelve (zone_id, zone_name, tier, lat, lon).
        Prioriza coincidencias específicas (Montepinar, Raiguero de Bonanza, Raiguero de Levante,
        Benferri, Granja de Rocamora) antes del cajón general de Orihuela.
        """
        combined = normalize_text(f"{title} {location_raw} {url} {description}")

        # Orden de evaluación: primero pedanías específicas y municipios objetivo, luego Orihuela casco
        eval_order = [
            "montepinar",
            "raiguero_bonanza",
            "raiguero_levante",
            "benferri",
            "granja_rocamora",
            "pedanias_orihuela",
            "orihuela",
        ]

        for zid in eval_order:
            zdata = self.zones.get(zid)
            if not zdata:
                continue
            for kw in zdata.get("keywords", []):
                nkw = normalize_text(kw)
                if nkw and re.search(r"\b" + re.escape(nkw) + r"\b", combined):
                    lat, lon = self._jitter_coords(
                        zdata["lat"], zdata["lon"], f"{title}:{location_raw}:{url}"
                    )
                    return zid, zdata["name"], zdata.get("tier", 1), lat, lon

        # Si menciona "raiguero" o "riguero" a secas sin especificar bonanza/levante
        if "raiguero" in combined or "riguero" in combined:
            zdata = self.zones["raiguero_bonanza"]
            lat, lon = self._jitter_coords(zdata["lat"], zdata["lon"], f"{title}:{url}")
            return "raiguero_bonanza", zdata["name"], 1, lat, lon

        # Fallback a Orihuela (Casco y Centro)
        zdata = self.zones["orihuela"]
        lat, lon = self._jitter_coords(zdata["lat"], zdata["lon"], f"{title}:{url}")
        return "orihuela", zdata["name"], 1, lat, lon

    @staticmethod
    def _jitter_coords(base_lat: float, base_lon: float, seed_str: str) -> Tuple[float, float]:
        """Genera un desplazamiento determinista suave (~300m) para que no se solapen los pines en el mapa."""
        h = int(hashlib.md5(seed_str.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
        angle = (h % 360) * (math.pi / 180.0)
        radius = ((h >> 8) % 100) / 100.0 * 0.0045
        return round(base_lat + math.sin(angle) * radius, 5), round(
            base_lon + math.cos(angle) * radius, 5
        )

    def classify_asset_type(self, title: str, description: str, raw_type: str = "") -> Tuple[str, str, bool]:
        """
        Clasifica el anuncio en:
        - ('solar_urbano', 'Solar Urbano', True)
        - ('solar_urbanizable', 'Solar Urbanizable', True)
        - ('casa_planta_baja', 'Casa Planta Baja / A Reformar', True)
        - ('rustico_dudoso', 'Rústico / Huerta', False)
        - ('descartado_piso', 'Piso en altura / No aplica', False)
        """
        norm_title = normalize_text(f"{title} {raw_type}")
        norm_all = normalize_text(f"{title} {raw_type} {description}")

        # 1. Descartar pisos/apartamentos en altura salvo que sea una casa entera o solar
        high_rise_terms = [
            r"\bpiso en venta\b",
            r"\batico\b",
            r"\bapartamento\b",
            r"\bplanta [1-9]\b",
            r"\b[1-9]a planta\b",
            r"\bduplex\b",
            r"\bestudio en venta\b",
            r"\bplaza de garaje\b",
            r"\btrastero\b",
        ]
        is_house_or_plot = any(
            w in norm_title
            for w in [
                "solar",
                "terreno",
                "parcela",
                "suelo",
                "casa de pueblo",
                "planta baja",
                "casa para reformar",
                "casa para derribar",
                "casa antigua",
                "casa independiente",
                "casa en venta",
                "chalet",
            ]
        )
        if not is_house_or_plot:
            for pat in high_rise_terms:
                if re.search(pat, norm_title):
                    return "descartado_piso", "Piso / No objetivo", False

        # 2. Detectar Casa de Pueblo / Planta Baja / Para reformar o derribar
        house_keywords = [
            "casa de pueblo",
            "planta baja",
            "casa baja",
            "casa antigua",
            "para reformar",
            "a reformar",
            "para derribar",
            "para demoler",
            "casa con solar",
            "casa con patio",
            "casa tradicional",
            "casa independiente",
            "casa en planta baja",
            "vivienda en planta baja",
            "casa de huerta",
            "casa de campo para reformar",
        ]
        is_solar_primary = any(
            w in norm_title for w in ["solar", "terreno", "parcela urbana", "suelo urbano", "suelo urbanizable"]
        )

        if any(hk in norm_all for hk in house_keywords) and not is_solar_primary:
            return "casa_planta_baja", "Casa Planta Baja / A Reformar", True

        # Si el título dice "Casa en venta..." y menciona reformar, solar, patio, planta baja o derribo
        if ("casa" in norm_title or "chalet" in norm_title) and not is_solar_primary:
            if any(
                w in norm_all
                for w in [
                    "reformar",
                    "derribar",
                    "origen",
                    "planta baja",
                    "solar",
                    "patio",
                    "corral",
                    "antigua",
                    "edificar",
                ]
            ):
                return "casa_planta_baja", "Casa Planta Baja / A Reformar", True
            # Si es un chalet de obra nueva o lujo > 300.000€ sin mención de reforma, lo marcamos aparte
            return "casa_planta_baja", "Casa / Vivienda con Parcela", True

        # 3. Distinguir entre Solar Urbano, Solar Urbanizable y Terreno Rústico
        is_urbanizable = any(
            w in norm_all
            for w in [
                "urbanizable",
                "sectorizado",
                "suelo en desarrollo",
                "unidad de ejecucion",
                "plan parcial",
                "reparcelacion",
            ]
        )
        is_urbano = any(
            w in norm_all
            for w in [
                "solar urbano",
                "suelo urbano",
                "terreno urbano",
                "parcela urbana",
                "urbano directo",
                "urbano consolidado",
                "casco urbano",
                "edificable",
                "para edificar",
                "bajo mas",
                "bajo +",
                "fachada",
                "acerado",
                "alcantarillado",
                "solar en",
            ]
        )
        is_rustico = any(
            w in norm_all
            for w in [
                "rustico",
                "finca rustica",
                "terreno rustico",
                "suelo no urbanizable",
                "uso agricola",
                "regadio",
                "limoneros",
                "naranjos",
                "cultivo",
            ]
        )

        if is_rustico and not is_urbano and not is_urbanizable:
            return "rustico_dudoso", "Suelo Rústico / Huerta", False

        if is_urbanizable and not is_urbano:
            return "solar_urbanizable", "Solar Urbanizable", True

        return "solar_urbano", "Solar Urbano", True

    def extract_surfaces(
        self,
        title: str,
        description: str,
        surface_plot_hint: Optional[float] = None,
        surface_built_hint: Optional[float] = None,
        asset_type: str = "solar_urbano",
    ) -> Tuple[Optional[float], Optional[float], float]:
        """
        Extrae (surface_plot_m2, surface_built_m2, effective_plot_m2).
        Soporta conversión automática de tahúllas (1 tahúlla = 1.118 m²).
        """
        norm = normalize_text(f"{title}. {description}")

        plot_m2 = float(surface_plot_hint) if surface_plot_hint and surface_plot_hint > 0 else None
        built_m2 = float(surface_built_hint) if surface_built_hint and surface_built_hint > 0 else None

        # 1. Buscar patrones específicos de parcela / solar en texto
        plot_patterns = [
            r"(\d[\d\.,]*)\s*(?:m2|m²|metros|metros cuadrados)\s*(?:de\s+)?(?:parcela|solar|terreno|suelo|patio)",
            r"(?:parcela|solar|terreno|suelo|superficie grafica)\s*(?:de\s+|con\s+)?(\d[\d\.,]*)\s*(?:m2|m²|metros)",
        ]
        for pat in plot_patterns:
            m = re.search(pat, norm)
            if m:
                val = self._parse_number(m.group(1))
                if val and 25 <= val <= 500000:
                    plot_m2 = val
                    break

        # 2. Buscar patrones de superficie construida
        built_patterns = [
            r"(\d[\d\.,]*)\s*(?:m2|m²|metros)\s*(?:construidos|utiles|de vivienda|de casa)",
            r"(?:construidos|superficie construida|vivienda de)\s*(?:de\s+)?(\d[\d\.,]*)\s*(?:m2|m²|metros)",
        ]
        for pat in built_patterns:
            m = re.search(pat, norm)
            if m:
                val = self._parse_number(m.group(1))
                if val and 20 <= val <= 10000:
                    built_m2 = val
                    break

        # 3. Buscar tahúllas (medida tradicional en Orihuela y Vega Baja)
        if not plot_m2:
            if "media tahulla" in norm:
                plot_m2 = round(TAHULLA_M2 * 0.5)
            else:
                m_tah = re.search(r"(\d+(?:[\.,]\d+)?)\s*tahullas?", norm)
                if m_tah:
                    t_val = float(m_tah.group(1).replace(",", "."))
                    if 0.1 <= t_val <= 200:
                        plot_m2 = round(t_val * TAHULLA_M2)

        # 4. Búsqueda general de m2 si aún no tenemos dato
        if not plot_m2 and not built_m2:
            all_m2 = re.findall(r"(\d[\d\.,]*)\s*(?:m2|m²|metros\s*cuadrados)", norm)
            parsed_vals = [
                self._parse_number(x) for x in all_m2 if self._parse_number(x) and 25 <= self._parse_number(x) <= 200000
            ]
            if parsed_vals:
                if asset_type in ("solar_urbano", "solar_urbanizable", "rustico_dudoso"):
                    plot_m2 = max(parsed_vals)
                else:
                    # En casa de planta baja, si hay dos cifras (ej. 160 m2 construidos y 240 m2 de parcela)
                    if len(parsed_vals) >= 2:
                        plot_m2 = max(parsed_vals)
                        built_m2 = min(parsed_vals)
                    else:
                        plot_m2 = parsed_vals[0]
                        built_m2 = parsed_vals[0]

        # Superficie efectiva de suelo para el filtro de >= 180 m²
        effective_plot = plot_m2 or built_m2 or 0.0
        return plot_m2, built_m2, round(effective_plot, 1)

    @staticmethod
    def _parse_number(raw: str) -> Optional[float]:
        if not raw:
            return None
        s = raw.strip()
        # Si tiene punto de miles (ej. 1.250 o 2.500)
        if re.match(r"^\d{1,3}(\.\d{3})+$", s):
            s = s.replace(".", "")
        else:
            s = s.replace(".", "").replace(",", ".") if "," in s and "." in s else s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    def calculate_chollo_score(
        self,
        price_eur: Optional[float],
        effective_plot_m2: float,
        zone_id: str,
        asset_type: str,
        title: str,
        description: str,
        price_drop_pct: float = 0.0,
        zone_dynamic_median_m2: Optional[float] = None,
    ) -> Tuple[int, List[str], Optional[float], Optional[float]]:
        """
        Calcula (chollo_score 0..100, reasons_list, eur_per_m2, discount_vs_ref_pct).
        """
        reasons: List[str] = []
        norm = normalize_text(f"{title} {description}")

        if not price_eur or price_eur <= 0 or effective_plot_m2 <= 0:
            return 35, ["Falta precio o m² para valorar €/m²"], None, None

        eur_m2 = round(price_eur / effective_plot_m2, 1)
        zdata = self.zones.get(zone_id, self.zones.get("orihuela", {}))

        if asset_type == "casa_planta_baja":
            ref_m2 = zdata.get("ref_eur_m2_casa_reforma", 450.0)
        else:
            ref_m2 = zdata.get("ref_eur_m2_solar", 220.0)

        # Si tenemos mediana dinámica real de la zona, combinamos 60% mediana real + 40% referencia
        if zone_dynamic_median_m2 and zone_dynamic_median_m2 > 30:
            benchmark_m2 = (zone_dynamic_median_m2 * 0.6) + (ref_m2 * 0.4)
        else:
            benchmark_m2 = float(ref_m2)

        discount_pct = round(((benchmark_m2 - eur_m2) / benchmark_m2) * 100.0, 1)

        # Base score (50 = en precio de mercado)
        score = 50.0 + (discount_pct * 0.65)

        if discount_pct >= 25:
            reasons.append(f"Precio/m² muy bajo ({eur_m2:.0f} €/m², un {discount_pct:.0f}% bajo media de zona)")
        elif discount_pct >= 12:
            reasons.append(f"Buen ratio ({eur_m2:.0f} €/m², {discount_pct:.0f}% bajo referencia en {zdata.get('name', zone_id)})")
        elif discount_pct <= -25:
            reasons.append(f"Precio/m² elevado respecto a la zona ({eur_m2:.0f} €/m²)")

        # Bonus por superficie >= 180 m²
        min_hl = self.filters.get("min_highlight_plot_m2", 180)
        if effective_plot_m2 >= min_hl:
            score += 6
            if effective_plot_m2 >= 300:
                score += 4
                reasons.append(f"Gran amplitud de parcela ({effective_plot_m2:.0f} m²)")
        else:
            score -= 10
            reasons.append(f"Parcela inferior al objetivo principal ({effective_plot_m2:.0f} m² < {min_hl} m²)")

        # Bonus por bajada histórica de precio registrada
        if price_drop_pct > 0:
            score += min(18.0, price_drop_pct * 1.3)
            reasons.append(f"Ha bajado un {price_drop_pct:.1f}% desde que se detectó")

        # Bonus por palabras clave de oportunidad / edificabilidad
        opportunity_signals = [
            (["esquina", "chaflan", "dos calles", "2 calles", "tres calles"], 7, "Solar en esquina / da a dos calles"),
            (["urge", "urgente", "oportunidad", "bajada de precio", "rebajado"], 6, "Vendedor indica urgencia / rebaja"),
            (["negociable", "se escuchan ofertas", "haz tu oferta"], 4, "Precio negociable"),
            (["herencia", "procedente de banco", "activo bancario", "sin comision"], 6, "Activo bancario / venta sin comisión"),
            (["bajo + 2", "bajo + 3", "bajo mas dos", "bajo mas tres", "edificabilidad"], 5, "Alta edificabilidad (varias alturas)"),
            (["agua y luz", "luz y agua", "suministros a pie", "vallado", "con escritura"], 4, "Suministros / servicios a pie de parcela"),
        ]
        for kws, pts, label in opportunity_signals:
            if any(k in norm for k in kws):
                score += pts
                reasons.append(label)

        # Penalización si es rústico dudoso
        if asset_type == "rustico_dudoso":
            score -= 25
            reasons.append("Cuidado: parece suelo rústico / no urbanizable")

        final_score = int(max(5, min(99, round(score))))
        return final_score, reasons[:4], eur_m2, discount_pct

    def analyze_raw_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa un diccionario crudo de cualquier scraper/portal y devuelve el registro enriquecido.
        """
        title = (item.get("title") or "").strip()
        description = (item.get("description") or "").strip()
        location_raw = (item.get("location") or "").strip()
        url = (item.get("url") or "").strip()
        price_eur = item.get("price_eur")
        if isinstance(price_eur, str):
            price_eur = self._parse_number(price_eur)

        full_text = f"{title} {location_raw} {description} {url}"
        is_costa = self.is_orihuela_costa(full_text)

        zone_id, zone_name, tier, lat, lon = self.detect_zone(title, description, location_raw, url)
        if item.get("lat") and item.get("lon"):
            lat, lon = float(item["lat"]), float(item["lon"])

        asset_type, asset_label, is_target_type = self.classify_asset_type(
            title, description, item.get("raw_type", "")
        )

        plot_m2, built_m2, effective_plot_m2 = self.extract_surfaces(
            title,
            description,
            item.get("surface_plot_m2"),
            item.get("surface_built_m2"),
            asset_type=asset_type,
        )

        min_hl = self.filters.get("min_highlight_plot_m2", 180)
        is_highlighted = (
            is_target_type
            and not is_costa
            and effective_plot_m2 >= min_hl
        )

        score, reasons, eur_m2, discount_pct = self.calculate_chollo_score(
            price_eur=price_eur,
            effective_plot_m2=effective_plot_m2,
            zone_id=zone_id,
            asset_type=asset_type,
            title=title,
            description=description,
            price_drop_pct=float(item.get("price_drop_pct", 0.0)),
        )

        # Generar ID estable por URL limpia o por hash de título+zona+superficie
        ext_id = item.get("external_id")
        if not ext_id:
            clean_u = url.split("?")[0].rstrip("/")
            ext_id = hashlib.sha1(f"{clean_u or title}:{zone_id}".encode("utf-8")).hexdigest()[:14]

        return {
            "id": ext_id,
            "portal": item.get("portal", "Web"),
            "title": title or f"{asset_label} en {zone_name}",
            "url": url,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "tier": tier,
            "location_raw": location_raw or zone_name,
            "lat": lat,
            "lon": lon,
            "asset_type": asset_type,
            "asset_label": asset_label,
            "is_target_type": is_target_type,
            "is_orihuela_costa": is_costa,
            "price_eur": price_eur,
            "surface_plot_m2": plot_m2,
            "surface_built_m2": built_m2,
            "effective_plot_m2": effective_plot_m2,
            "eur_per_m2": eur_m2,
            "discount_vs_ref_pct": discount_pct,
            "is_highlighted": is_highlighted,
            "chollo_score": score,
            "chollo_reasons": reasons,
            "description": description[:700],
            "image_url": item.get("image_url", ""),
            "phone": item.get("phone", ""),
        }
