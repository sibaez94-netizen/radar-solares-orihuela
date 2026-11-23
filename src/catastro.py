# -*- coding: utf-8 -*-
"""
Integración con la Sede Electrónica del Catastro (API pública gratuita sin clave).
- Extrae referencias catastrales (14 o 20 caracteres) cuando aparecen en la ficha.
- Consulta datos oficiales (clase Urbano/Rústico, uso, superficie, año construcción, dirección)
  en `ovc.catastro.meh.es`.
- Genera enlaces directos al Visor del Catastro y a vista Satélite en Google Maps.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from src.scrapers.portals_scraper import http_get

RC20_RE = re.compile(r"\b(\d{7}[A-Z]{2}\d{4}[A-Z]\d{4}[A-Z]{2})\b")
RC14_RE = re.compile(r"\b(\d{7}[A-Z]{2}\d{4}[A-Z])\b")


def extract_cadastral_ref(text: str) -> Optional[str]:
    """Busca una referencia catastral española válida (20 o 14 caracteres) en el texto."""
    if not text:
        return None
    up = text.upper()
    m20 = RC20_RE.search(up)
    if m20:
        return m20.group(1)
    # Para 14 caracteres exigir contexto de catastro/parcela para evitar falsos positivos
    if any(k in up for k in ("CATASTR", "REF.", "REFERENCIA", "PARCELA", "FINCA")):
        m14 = RC14_RE.search(up)
        if m14:
            return m14.group(1)
    return None


def build_catastro_url(lat: Optional[float], lon: Optional[float], rc: Optional[str] = None) -> str:
    """Devuelve enlace directo a la ficha catastral (si hay RC) o al visor cartográfico del Catastro."""
    if rc and len(rc) >= 14:
        rc1 = rc[:7]
        rc2 = rc[7:14]
        return (
            "https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCListaBienes.aspx"
            f"?RC1={urllib.parse.quote(rc1)}&RC2={urllib.parse.quote(rc2)}"
        )
    if lat and lon:
        return (
            "https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx"
            f"?buscar=S&lat={lat:.5f}&lon={lon:.5f}"
        )
    return "https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx"


def build_satellite_url(lat: Optional[float], lon: Optional[float], query: str = "") -> str:
    """Devuelve enlace directo a Google Maps en vista satélite."""
    if lat and lon:
        return f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},18z/data=!3m1!1e3"
    if query:
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(query)}"
    return "https://www.google.com/maps"


def _xml_text(root: ET.Element, tag_suffix: str) -> str:
    for el in root.iter():
        if el.tag.endswith(tag_suffix) and el.text and el.text.strip():
            return el.text.strip()
    return ""


def lookup_catastro_by_rc(rc: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """Consulta oficial de inmueble por referencia catastral en ovc.catastro.meh.es."""
    rc_clean = (rc or "").strip().upper()
    if len(rc_clean) < 14:
        return None
    url = (
        "https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/"
        f"OVCCallejero.asmx/Consulta_DNPRC?Provincia=&Municipio=&RC={urllib.parse.quote(rc_clean)}"
    )
    xml_body = http_get(url, timeout=timeout, retries=1)
    if not xml_body or "<lerr>" in xml_body.lower():
        return None
    try:
        root = ET.fromstring(xml_body.encode("utf-8", errors="ignore"))
    except Exception:
        return None

    cn = _xml_text(root, "cn")  # UR = Urbano, RU = Rústico
    clase = "Urbano" if cn == "UR" else ("Rústico" if cn == "RU" else cn)
    uso = _xml_text(root, "luso")
    sfc = _xml_text(root, "sfc")
    ant = _xml_text(root, "ant")
    ldt = _xml_text(root, "ldt")
    if not (clase or uso or sfc or ldt):
        return None

    return {
        "rc": rc_clean,
        "clase": clase,
        "uso": uso,
        "superficie_catastro_m2": float(sfc) if sfc.replace(".", "").isdigit() else None,
        "anio_construccion": int(ant) if ant.isdigit() else None,
        "direccion": ldt,
        "url": build_catastro_url(None, None, rc_clean),
    }


def lookup_catastro_by_coords(lat: float, lon: float, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """
    Consulta la referencia catastral a partir de coordenadas REALES (WGS84 / EPSG:4326).
    No usar con coordenadas sintéticas/jittered de centro de zona.
    """
    if not lat or not lon:
        return None
    url = (
        "https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/"
        f"OVCCoordenadas.asmx/Consulta_RCCOOR?SRS=EPSG:4326&Coordenada_X={lon:.6f}&Coordenada_Y={lat:.6f}"
    )
    xml_body = http_get(url, timeout=timeout, retries=1)
    if not xml_body or "<lerr>" in xml_body.lower():
        return None
    try:
        root = ET.fromstring(xml_body.encode("utf-8", errors="ignore"))
    except Exception:
        return None

    pc1 = _xml_text(root, "pc1")
    pc2 = _xml_text(root, "pc2")
    ldt = _xml_text(root, "ldt")
    if not (pc1 and pc2):
        return None
    rc14 = f"{pc1}{pc2}"
    detailed = lookup_catastro_by_rc(rc14, timeout=timeout)
    if detailed:
        return detailed
    return {
        "rc": rc14,
        "clase": "",
        "uso": "",
        "superficie_catastro_m2": None,
        "anio_construccion": None,
        "direccion": ldt,
        "url": build_catastro_url(lat, lon, rc14),
    }
