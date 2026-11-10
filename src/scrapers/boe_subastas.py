# -*- coding: utf-8 -*-
"""
Lector del Portal de Subastas Electrónicas del BOE (https://subastas.boe.es).

Busca subastas de INMUEBLES en la provincia configurada (por defecto Alicante, 03) que estén
celebrándose (EJ) o a punto de abrir (PU): judiciales, Agencia Tributaria, Seguridad Social,
notariales y otras administraciones. Abre la ficha de cada una (y de cada lote), se queda solo
con los bienes situados en las zonas del radar y calcula:

- valor de subasta, tasación, puja mínima, depósito (5%) y fecha de cierre;
- superficie (convierte las cifras escritas en letra: "CIENTO VEINTE METROS CUADRADOS");
- descuento estimado frente al €/m² de referencia de la zona;
- banderas de riesgo: solo se subasta una parte (50%, nuda propiedad...), ocupada,
  cargas previas, vivienda habitual del deudor, no visitable, ya tiene pujas.

No inventa nada: si un dato no aparece en la ficha, se deja vacío.
"""

import datetime
import html as html_lib
import re
import time
import unicodedata
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from src.scrapers.portals_scraper import http_get

BASE_URL = "https://subastas.boe.es"

# ------------------------------------------------------------------ utilidades


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.lower()).strip()


def parse_eur(text: str) -> Optional[float]:
    """'118.002,50 €' -> 118002.5 ; 'Sin puja mínima' / 'No consta' -> None"""
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*€", text)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def parse_iso_date(text: str) -> Optional[str]:
    m = re.search(r"ISO:\s*([0-9T:\-+]+)", text or "")
    if m:
        return m.group(1)
    m = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})(?:\s+a las)?\s*(\d{2}:\d{2}(?::\d{2})?)?", text or "")
    if m:
        hh = m.group(4) or "00:00:00"
        if len(hh) == 5:
            hh += ":00"
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}T{hh}"
    return None


# ------------------------------------------- números escritos en letra (español)
_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600,
    "seiscientas": 600, "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}
_NUM_WORD_RE = "|".join(sorted(list(_UNITS.keys()) + ["mil"], key=len, reverse=True))
_NUM_SEQ = re.compile(r"\b(?:(?:" + _NUM_WORD_RE + r")\b(?:\s+y\s+|\s+)?)+", re.IGNORECASE)


def words_to_int(seq: str) -> Optional[int]:
    tokens = [t for t in re.split(r"\s+", _norm(seq)) if t and t != "y"]
    if not tokens:
        return None
    total, current = 0, 0
    for t in tokens:
        if t == "mil":
            current = max(current, 1) * 1000
            total += current
            current = 0
        elif t in _UNITS:
            current += _UNITS[t]
        else:
            return None
    return total + current


def spelled_numbers_to_digits(text: str) -> str:
    """Convierte 'CIENTO ONCE METROS Y SESENTA Y TRES DECÍMETROS CUADRADOS' en '111,63 m2'."""
    t = _norm(text)

    def repl(m: "re.Match[str]") -> str:
        raw = m.group(0)
        val = words_to_int(raw)
        if val is None:
            return raw
        trailing = " " if raw.endswith(" ") else ""
        return f"{val}{trailing}"

    t = _NUM_SEQ.sub(repl, t)
    # "55 metros y 90 decimetros cuadrados" -> "55,90 m2"
    t = re.sub(
        r"(\d+)\s*metros?\s*(?:y\s*)?(\d{1,2})\s*decimetros?\s*cuadrados?",
        lambda m: f"{m.group(1)},{int(m.group(2)):02d} m2",
        t,
    )
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*metros?\s*cuadrados?", r"\1 m2", t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)\b", r"\1 m2", t)
    return t


# --------------------------------------------------------------- parsing HTML


def table_to_dict(table) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for tr in table.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            out[th.get_text(" ", strip=True)] = td.get_text(" ", strip=True)
    return out


def parse_search_results(page_html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(page_html, "html.parser")
    results = []
    for li in soup.select("li.resultado-busqueda"):
        h3 = li.find("h3")
        title = h3.get_text(" ", strip=True) if h3 else ""
        m = re.search(r"(SUB-[A-Z]{2}-\d{4}-[A-Z0-9]+)", title)
        if not m:
            continue
        lots_m = re.search(r"\((\d+)\s+lotes?\)", title)
        h4 = li.find("h4")
        ps = [p.get_text(" ", strip=True) for p in li.find_all("p")]
        estado = next((p for p in ps if p.lower().startswith("estado")), "")
        results.append(
            {
                "id_subasta": m.group(1),
                "num_lotes": int(lots_m.group(1)) if lots_m else 1,
                "autoridad": h4.get_text(" ", strip=True) if h4 else "",
                "estado_texto": estado.replace("Estado:", "").strip(),
                "resumen": max(ps, key=len) if ps else "",
            }
        )
    return results


def parse_total_results(page_html: str) -> Optional[int]:
    m = re.search(r"Resultados\s+\d+\s+a\s+\d+\s+de\s+(\d+)", page_html)
    return int(m.group(1)) if m else None


def parse_general(page_html: str) -> Dict[str, Any]:
    """Datos generales (ver=1) + documentos públicos (edicto, certificación de cargas...)."""
    soup = BeautifulSoup(page_html, "html.parser")
    block = soup.find(id="idBloqueDatos1") or soup
    table = block.find("table")
    data: Dict[str, Any] = table_to_dict(table) if table else {}
    docs = []
    for a in block.select("ul.enlaces a[href]"):
        href = a.get("href", "")
        if "verDocumento" in href:
            docs.append({"titulo": a.get_text(" ", strip=True), "url": urllib.parse.urljoin(BASE_URL + "/", href)})
    data["_documentos"] = docs
    return data


def parse_lot_page(page_html: str) -> Dict[str, Any]:
    """Página ver=3 (con o sin idLote). Devuelve datos del lote, bienes y pestañas de lotes."""
    soup = BeautifulSoup(page_html, "html.parser")
    tabs = []
    for a in soup.select("a[id^=idTabLote]"):
        num_m = re.search(r"idTabLote(\d+)", a.get("id", ""))
        if num_m:
            tabs.append({"lote": int(num_m.group(1)), "titulo": html_lib.unescape(a.get("title", ""))})

    lot_data: Dict[str, str] = {}
    bienes: List[Dict[str, str]] = []
    nota_lote = ""
    container = soup.find(id=re.compile(r"^idBloqueLote\d+")) or soup.find(id="idBloqueDatos3") or soup
    for h3 in container.find_all("h3"):
        if "Datos relacionados con la subasta" in h3.get_text():
            tb = h3.find_next("table")
            if tb:
                lot_data = table_to_dict(tb)
    for h4 in container.find_all("h4"):
        txt = h4.get_text(" ", strip=True)
        if not txt.lower().startswith("bien"):
            continue
        tb = h4.find_next("table")
        data = table_to_dict(tb) if tb else {}
        sub_m = re.search(r"\(([^)]+)\)", txt)
        data["_titulo_bien"] = txt
        data["_subtipo"] = sub_m.group(1).strip() if sub_m else ""
        bienes.append(data)
    caja = container.find("div", class_="caja")
    em = container.find("em")
    nota_lote = " ".join(x.get_text(" ", strip=True) for x in (caja, em) if x)
    return {"tabs": tabs, "lot_data": lot_data, "bienes": bienes, "nota": nota_lote}


def parse_pujas(page_html: str) -> Dict[str, Any]:
    t = _norm(BeautifulSoup(page_html, "html.parser").get_text(" "))
    if "no ha recibido pujas" in t:
        return {"tiene_pujas": False, "puja_maxima_eur": None, "texto": "Sin pujas"}
    if "ha recibido alguna puja" in t:
        return {"tiene_pujas": True, "puja_maxima_eur": None, "texto": "Ya tiene pujas (importe solo visible con registro)"}
    idx = t.find("puja maxima actual")
    if idx >= 0:
        val = parse_eur(t[idx: idx + 200].replace("eur", "€"))
        return {"tiene_pujas": val is not None, "puja_maxima_eur": val, "texto": "Puja máxima pública"}
    return {"tiene_pujas": None, "puja_maxima_eur": None, "texto": "Sin dato de pujas"}


# ------------------------------------------------------------------ el lector


class BoeSubastasScraper:
    SKIP_LOT_TERMS = ("plaza de garaje", "plaza de aparcamiento", "aparcamiento numero", "trastero", "plaza garaje")

    def __init__(
        self,
        config: Dict[str, Any],
        analyzer: Any,
        getter: Optional[Callable[[str], Optional[str]]] = None,
        delay_s: float = 0.6,
        cache: Optional[Dict[str, Any]] = None,
        cache_days: int = 3,
    ):
        self.config = config
        self.cfg = config.get("boe_subastas", {}) or {}
        self.analyzer = analyzer
        self.getter = getter or (lambda url: http_get(url, timeout=25))
        self.delay_s = float(self.cfg.get("delay_s", delay_s))
        self.cache = cache if cache is not None else {}
        self.cache_days = cache_days
        self.errors: List[str] = []
        self.stats = {"subastas_provincia": 0, "fichas_descargadas": 0, "lotes_revisados": 0, "en_zona": 0}
        self.summary_ids: List[str] = []
        self.listing_ok = False

        kws = []
        for z in (config.get("zones") or {}).values():
            kws.extend(z.get("keywords", []))
        kws.extend(self.cfg.get("extra_localidades", []))
        self.zone_keywords = sorted({_norm(k) for k in kws if k}, key=len, reverse=True)
        self.excluded = [_norm(k) for k in config.get("excluded_costa_keywords", []) if k]
        self.excluded_cp = set(self.cfg.get("excluir_codigos_postales", ["03189"]))

    # ---------------------------------------------------------- HTTP
    def _get(self, url: str) -> Optional[str]:
        time.sleep(self.delay_s)
        try:
            return self.getter(url)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{url}: {exc}")
            return None

    def search_url(self, estado: str, provincia: str) -> str:
        params = [
            ("campo[0]", "SUBASTA.ORIGEN"), ("dato[0]", ""),
            ("campo[1]", "SUBASTA.AUTORIDAD"), ("dato[1]", ""),
            ("campo[2]", "SUBASTA.ESTADO.CODIGO"), ("dato[2]", estado),
            ("campo[3]", "BIEN.TIPO"), ("dato[3]", "I"),
            ("dato[4]", ""),
            ("campo[5]", "BIEN.DIRECCION"), ("dato[5]", ""),
            ("campo[6]", "BIEN.CODPOSTAL"), ("dato[6]", ""),
            ("campo[7]", "BIEN.LOCALIDAD"), ("dato[7]", ""),
            ("campo[8]", "BIEN.COD_PROVINCIA"), ("dato[8]", provincia),
            ("page_hits", "500"),
            ("sort_field[0]", "SUBASTA.FECHA_FIN"), ("sort_order[0]", "asc"),
            ("accion", "Buscar"),
        ]
        return f"{BASE_URL}/subastas_ava.php?" + urllib.parse.urlencode(params)

    @staticmethod
    def detail_url(id_sub: str, ver: int, lote: Optional[int] = None) -> str:
        u = f"{BASE_URL}/detalleSubasta.php?idSub={urllib.parse.quote(id_sub)}&ver={ver}"
        if lote:
            u += f"&idLote={lote}"
        return u

    # ---------------------------------------------------------- filtros de zona
    def match_zone_text(self, localidad: str, direccion: str, cp: str) -> Tuple[bool, str]:
        if cp and cp.strip() in self.excluded_cp:
            return False, f"Código postal excluido ({cp})"
        loc = _norm(f"{localidad} {direccion}")
        for ex in self.excluded:
            if ex and re.search(r"\b" + re.escape(ex) + r"\b", loc):
                return False, f"Zona excluida ({ex})"
        for kw in self.zone_keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", loc):
                return True, kw
        return False, "Fuera de las zonas del radar"

    def _lot_title_skippable(self, titulo: str) -> bool:
        t = _norm(titulo)
        if any(term in t for term in self.SKIP_LOT_TERMS):
            return True
        return any(re.search(r"\b" + re.escape(ex) + r"\b", t) for ex in self.excluded if ex)

    # ---------------------------------------------------------- recogida
    def fetch_auction(self, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        id_sub = summary["id_subasta"]
        cached = self.cache.get(id_sub)
        if cached:
            try:
                age = datetime.datetime.utcnow() - datetime.datetime.fromisoformat(cached["fetched_at"])
                if age.days < self.cache_days:
                    return cached
            except Exception:  # noqa: BLE001
                pass

        gen_html = self._get(self.detail_url(id_sub, 1))
        lot1_html = self._get(self.detail_url(id_sub, 3))
        if not gen_html or not lot1_html:
            return None
        self.stats["fichas_descargadas"] += 1
        general = parse_general(gen_html)
        first = parse_lot_page(lot1_html)
        lots = []
        if first["tabs"]:
            for tab in first["tabs"]:
                if tab["lote"] == 1:
                    page = first
                else:
                    if self._lot_title_skippable(tab["titulo"]):
                        continue
                    h = self._get(self.detail_url(id_sub, 3, tab["lote"]))
                    if not h:
                        continue
                    page = parse_lot_page(h)
                self.stats["lotes_revisados"] += 1
                lots.append({"lote": tab["lote"], **{k: page[k] for k in ("lot_data", "bienes", "nota")}})
        else:
            self.stats["lotes_revisados"] += 1
            lots.append({"lote": None, "lot_data": {}, "bienes": first["bienes"], "nota": first["nota"]})

        record = {
            "fetched_at": datetime.datetime.utcnow().isoformat(),
            "id_subasta": id_sub,
            "general": general,
            "lots": lots,
        }
        self.cache[id_sub] = record
        return record

    def run(self) -> List[Dict[str, Any]]:
        if not self.cfg.get("enabled", True):
            return []
        provincias = self.cfg.get("provincias", ["03"])
        estados = self.cfg.get("estados", ["EJ", "PU"])
        summaries: Dict[str, Dict[str, Any]] = {}
        for prov in provincias:
            for est in estados:
                page = self._get(self.search_url(est, prov))
                if page is None:
                    self.errors.append(f"No se pudo leer el listado (provincia {prov}, estado {est})")
                    continue
                for s in parse_search_results(page):
                    s["estado_codigo"] = est
                    summaries[s["id_subasta"]] = s
        self.stats["subastas_provincia"] = len(summaries)
        self.summary_ids = list(summaries.keys())
        self.listing_ok = not any("No se pudo leer el listado" in e for e in self.errors)

        items: List[Dict[str, Any]] = []
        for id_sub, summary in summaries.items():
            rec = self.fetch_auction(summary)
            if not rec:
                continue
            for lot in rec["lots"]:
                for idx, bien in enumerate(lot["bienes"], 1):
                    ok, why = self.match_zone_text(
                        bien.get("Localidad", ""), bien.get("Dirección", ""), bien.get("Código Postal", "")
                    )
                    if not ok:
                        continue
                    item = self.build_item(summary, rec["general"], lot, bien, idx, why)
                    if item:
                        items.append(item)

        # Pujas solo de lo que nos interesa (pocas peticiones)
        for it in items:
            h = self._get(self.detail_url(it["id_subasta"], 5, it.get("lote")))
            if h:
                it.update({"pujas": parse_pujas(h)})
            it["riesgos"], it["score"], it["score_reasons"] = self.score_item(it)

        self.stats["en_zona"] = len(items)
        return items

    # ---------------------------------------------------------- análisis
    def _surfaces(self, description: str, subtipo: str) -> Tuple[Optional[float], Optional[float], float]:
        digits = spelled_numbers_to_digits(description)
        hint_type = "solar_urbano" if "solar" in _norm(subtipo) or "rustica" in _norm(subtipo) else "casa_planta_baja"
        return self.analyzer.extract_surfaces("", digits, asset_type=hint_type)

    def classify(self, subtipo: str, description: str) -> Tuple[str, str, bool]:
        st = _norm(subtipo)
        d = _norm(description)
        if "garaje" in st or "trastero" in st:
            return "descartado_piso", "Garaje / trastero", False
        if "solar" in st:
            urbanizable = any(w in d for w in ("urbanizable", "unidad de ejecucion", "plan parcial", "sector"))
            return ("solar_urbanizable", "Solar urbanizable", True) if urbanizable else ("solar_urbano", "Solar", True)
        if "rustica" in st:
            return "rustico_dudoso", "Finca rústica", False
        if "local" in st or "nave" in st:
            return "descartado_piso", subtipo or "Local / nave", False
        if "vivienda" in st or not st or "otros" in st:
            piso = re.search(
                r"\b(piso|apartamento|atico|duplex|bloque|escalera|portal)\b|planta (primera|segunda|tercera|cuarta|quinta|sexta|septima|octava|alta|[1-9])",
                d,
            )
            casa = re.search(r"\b(casa|unifamiliar|chalet|adosad[oa]|planta baja y|compuesta de planta baja|vivienda de planta baja|patio|corral)\b", d)
            if casa and not piso:
                return "casa_planta_baja", "Casa / vivienda unifamiliar", True
            if "solar" in d and not piso:
                return "solar_urbano", "Solar (según descripción)", True
            return "descartado_piso", "Piso / vivienda en bloque", False
        return "descartado_piso", subtipo or "Otro inmueble", False

    def build_item(self, summary, general, lot, bien, idx, zona_kw) -> Optional[Dict[str, Any]]:
        desc = bien.get("Descripción", "") or lot.get("nota", "")
        subtipo = bien.get("_subtipo", "")
        asset_type, asset_label, is_target = self.classify(subtipo, desc)
        plot_m2, built_m2, eff_m2 = self._surfaces(desc, subtipo)

        ld = lot.get("lot_data") or {}
        def pick(*keys):
            for k in keys:
                for src in (ld, general):
                    if src.get(k):
                        return src[k]
            return ""
        valor = parse_eur(pick("Valor Subasta", "Valor subasta"))
        tasacion = parse_eur(pick("Valor de tasación", "Tasación"))
        if tasacion == 0:
            tasacion = None
        puja_min_txt = pick("Puja mínima")
        puja_min = parse_eur(puja_min_txt)
        deposito = parse_eur(pick("Importe del depósito"))
        fin = parse_iso_date(general.get("Fecha de conclusión", "")) or parse_iso_date(summary.get("estado_texto", ""))
        inicio = parse_iso_date(general.get("Fecha de inicio", ""))

        zone_id, zone_name, _, lat, lon = self.analyzer.detect_zone("", "", f"{bien.get('Localidad','')} {bien.get('Dirección','')}")
        zdata = (self.config.get("zones") or {}).get(zone_id, {})
        ref = zdata.get("ref_eur_m2_casa_reforma" if asset_type == "casa_planta_baja" else "ref_eur_m2_solar")
        base_m2 = (built_m2 or eff_m2) if asset_type == "casa_planta_baja" else (plot_m2 or eff_m2)
        # Solo se estima el valor de mercado de solares y casas (las referencias €/m² de la zona son de esos tipos)
        mercado = round(base_m2 * ref) if (ref and base_m2 and is_target) else None
        ref_price = valor or tasacion
        descuento = round((1 - ref_price / mercado) * 100, 1) if (mercado and ref_price) else None

        lote = lot.get("lote")
        uid = f"{summary['id_subasta']}" + (f"-L{lote}" if lote else "") + (f"-B{idx}" if idx > 1 else "")
        return {
            "id": uid,
            "id_subasta": summary["id_subasta"],
            "lote": lote,
            "url": self.detail_url(summary["id_subasta"], 3, lote) if lote else self.detail_url(summary["id_subasta"], 1),
            "estado_codigo": summary.get("estado_codigo"),
            "estado": "Celebrándose" if summary.get("estado_codigo") == "EJ" else "Próxima apertura",
            "autoridad": summary.get("autoridad", ""),
            "tipo_subasta": general.get("Tipo de subasta", ""),
            "fecha_inicio": inicio,
            "fecha_fin": fin,
            "subtipo": subtipo,
            "asset_type": asset_type,
            "asset_label": asset_label,
            "is_target_type": is_target,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "zona_detectada_por": zona_kw,
            "lat": lat,
            "lon": lon,
            "localidad": bien.get("Localidad", ""),
            "direccion": bien.get("Dirección", ""),
            "codigo_postal": bien.get("Código Postal", ""),
            "referencia_catastral": bien.get("Referencia catastral", ""),
            "descripcion": desc[:1200],
            "superficie_parcela_m2": plot_m2,
            "superficie_construida_m2": built_m2,
            "superficie_efectiva_m2": eff_m2 or None,
            "valor_subasta_eur": valor,
            "tasacion_eur": tasacion,
            "puja_minima_eur": puja_min,
            "puja_minima_texto": puja_min_txt,
            "deposito_eur": deposito,
            "valor_mercado_estimado_eur": mercado,
            "descuento_vs_mercado_pct": descuento,
            "situacion_posesoria": bien.get("Situación posesoria", ""),
            "visitable": bien.get("Visitable", ""),
            "vivienda_habitual": bien.get("Vivienda habitual", ""),
            "cargas_texto": bien.get("Cargas", ""),
            "titulo_juridico": bien.get("Título jurídico", ""),
            "info_adicional": (bien.get("Información adicional", "") + " " + (lot.get("nota") or "")).strip()[:900],
            "documentos": general.get("_documentos", []),
            "pujas": {"tiene_pujas": None, "puja_maxima_eur": None, "texto": "Sin dato de pujas"},
        }

    def score_item(self, it: Dict[str, Any]) -> Tuple[List[str], int, List[str]]:
        riesgos: List[str] = []
        reasons: List[str] = []
        score = 50.0
        texto = _norm(" ".join([it.get("descripcion", ""), it.get("info_adicional", ""), it.get("titulo_juridico", "")]))

        parte = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:del|de la|de)?\s*(pleno dominio|nuda propiedad|usufructo|propiedad)", texto)
        if parte and float(parte.group(1).replace(",", ".")) < 100:
            riesgos.append(f"Solo se subasta el {parte.group(1)}% ({parte.group(2)}): comprarías una parte, no la finca entera")
            score -= 30
        elif re.search(r"mitad indivisa|una (tercera|cuarta|sexta) parte|nuda propiedad|usufructo", texto):
            riesgos.append("Solo se subasta una parte o un derecho (mitad indivisa, nuda propiedad o usufructo)")
            score -= 30

        pos = _norm(it.get("situacion_posesoria", ""))
        if "ocupad" in pos or "con ocupantes" in pos or re.search(r"\b(inmueble|vivienda|finca) ocupad", texto):
            riesgos.append("Ocupada: habría que tramitar el lanzamiento")
            score -= 15
        elif "sin ocupantes" in pos:
            reasons.append("Consta sin ocupantes")
            score += 4
        else:
            riesgos.append("Situación posesoria no consta")

        cargas = parse_eur(it.get("cargas_texto", ""))
        if cargas:
            riesgos.append(f"Cargas previas declaradas: {int(cargas):,} €".replace(",", "."))
            score -= 10
        if it.get("tipo_subasta", "").upper().startswith("JUDICIAL"):
            riesgos.append("Judicial: las cargas anteriores suelen subsistir; pide la certificación de cargas del Registro")
        if _norm(it.get("vivienda_habitual", "")) == "si":
            riesgos.append("Es la vivienda habitual del deudor (reglas de adjudicación más estrictas)")
            score -= 5
        if _norm(it.get("visitable", "")) == "no":
            riesgos.append("No visitable")

        d = it.get("descuento_vs_mercado_pct")
        if d is not None:
            score += max(-20.0, min(30.0, d * 0.5))
            if d >= 25:
                reasons.append(f"Valor de subasta un {d:.0f}% por debajo del €/m² de referencia de la zona")
        if not it.get("puja_minima_eur") and "sin puja" in _norm(it.get("puja_minima_texto", "")):
            reasons.append("Sin puja mínima")
            score += 4
        pj = it.get("pujas") or {}
        if pj.get("tiene_pujas") is False:
            reasons.append("Todavía sin pujas")
            score += 3
        elif pj.get("tiene_pujas"):
            reasons.append("Ya tiene pujas")
        if not it.get("is_target_type"):
            score -= 20
        return riesgos, int(max(5, min(99, round(score)))), reasons
