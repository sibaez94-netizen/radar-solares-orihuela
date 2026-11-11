# -*- coding: utf-8 -*-
"""
Identidad de inmuebles, episodios de publicación y reglas de alerta.

El problema que resuelve: un mismo inmueble puede salir varias veces. En dos
portales a la vez, o en el mismo portal con otra referencia porque el vendedor
lo retiró y lo volvió a publicar para que parezca recién salido. Si solo
guardamos el anuncio, perdemos la cuenta de cuánto lleva en venta de verdad.

Aquí se decide cuándo dos anuncios son el mismo inmueble (un "inmueble" tiene
su propio identificador, independiente del anuncio), y se traducen los
movimientos de precio y de publicación a alertas en castellano.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

ISO = "%Y-%m-%dT%H:%M:%SZ"

# Palabras que aparecen en casi todos los anuncios y no distinguen nada
VACIAS = {
    "venta", "vende", "vendo", "casa", "chalet", "solar", "terreno", "parcela",
    "suelo", "urbano", "urbanizable", "piso", "vivienda", "inmueble", "finca",
    "para", "con", "sin", "por", "del", "las", "los", "una", "uno", "mas",
    "muy", "zona", "calle", "avenida", "euros", "precio", "oportunidad",
    "reformar", "reforma", "obra", "nueva", "gran", "buena", "ideal",
    "orihuela", "alicante", "vega", "baja", "centro", "pueblo",
}


def ahora_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(ISO)


def a_fecha(iso: Optional[str]) -> Optional[datetime.datetime]:
    if not iso:
        return None
    txt = str(iso).strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(txt[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    return None


def dias_entre(desde: Optional[str], hasta: Optional[str] = None) -> Optional[int]:
    d1 = a_fecha(desde)
    if not d1:
        return None
    d2 = a_fecha(hasta) or datetime.datetime.utcnow()
    return max(0, (d2 - d1).days)


def normaliza(texto: Any) -> str:
    s = str(texto or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def palabras_clave(*textos: Any) -> set:
    """Palabras de 4 letras o más que no estén en la lista de vacías."""
    out = set()
    for t in textos:
        for w in normaliza(t).split():
            if len(w) >= 4 and w not in VACIAS and not w.isdigit():
                out.add(w)
    return out


def normaliza_telefono(tel: Any) -> str:
    d = re.sub(r"\D", "", str(tel or ""))
    return d[-9:] if len(d) >= 9 else ""


def _cerca(a: Optional[float], b: Optional[float], tolerancia: float) -> Optional[bool]:
    """True si se parecen, False si no, None si falta algún dato."""
    if not a or not b or a <= 0 or b <= 0:
        return None
    return abs(a - b) / max(a, b) <= tolerancia


def huella(item: Dict[str, Any]) -> str:
    """Identificador estable de un inmueble, a partir de lo que no cambia al republicarlo."""
    partes = [
        str(item.get("zone_id") or ""),
        str(item.get("asset_type") or ""),
        str(int(round((item.get("effective_plot_m2") or 0) / 5.0) * 5)),
        normaliza_telefono(item.get("phone")),
    ]
    return "P" + hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:14]


def parecido(nuevo: Dict[str, Any], conocido: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Puntúa de 0 a 100 si dos anuncios son el mismo inmueble.
    Devuelve la puntuación y los motivos, para poder explicarlo en el panel.
    """
    if (nuevo.get("zone_id") or "") != (conocido.get("zone_id") or ""):
        return 0, []
    if (nuevo.get("asset_type") or "") != (conocido.get("asset_type") or ""):
        return 0, []

    puntos = 0
    motivos: List[str] = []
    señal_fuerte = False

    tel_a, tel_b = normaliza_telefono(nuevo.get("phone")), normaliza_telefono(conocido.get("phone"))
    mismo_telefono = bool(tel_a and tel_b and tel_a == tel_b)
    if tel_a and tel_b:
        if mismo_telefono:
            puntos += 35
            señal_fuerte = True
            motivos.append("mismo teléfono de contacto")
        else:
            puntos -= 25

    # Dos anuncios del mismo inmueble no suelen separarse tanto de precio. Sin un
    # teléfono que lo confirme, una diferencia enorme significa que son fincas
    # distintas que casualmente miden lo mismo y están en la misma pedanía.
    # Se aprieta más cuando el otro anuncio sigue vivo: nadie publica hoy la misma
    # casa a dos precios muy distintos. Si ya estaba retirado, en cambio, un salto
    # grande de precio es justo lo que se espera de quien republica más barato.
    tolerancia = 0.25 if conocido.get("_sigue_publicado") else 0.40
    if not mismo_telefono and _cerca(nuevo.get("price_eur"), conocido.get("price_eur"), tolerancia) is False:
        return 0, []

    sup = _cerca(nuevo.get("effective_plot_m2"), conocido.get("effective_plot_m2"), 0.02)
    if sup is True:
        puntos += 35
        señal_fuerte = True
        motivos.append("misma superficie de parcela")
    elif sup is False:
        if _cerca(nuevo.get("effective_plot_m2"), conocido.get("effective_plot_m2"), 0.05):
            puntos += 18
            motivos.append("superficie de parcela casi igual")
        else:
            return 0, []  # superficies distintas: no es el mismo inmueble

    con = _cerca(nuevo.get("surface_built_m2"), conocido.get("surface_built_m2"), 0.03)
    if con is True:
        puntos += 15
        motivos.append("misma superficie construida")
    elif con is False:
        puntos -= 15

    ra, rb = nuevo.get("rooms"), conocido.get("rooms")
    if ra and rb:
        if ra == rb:
            puntos += 8
        else:
            puntos -= 12

    ta = palabras_clave(nuevo.get("title"), nuevo.get("location_raw"))
    tb = palabras_clave(conocido.get("title"), conocido.get("location_raw"))
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        if jac >= 0.7:
            puntos += 25
            señal_fuerte = True
            motivos.append("anuncio prácticamente idéntico")
        elif jac >= 0.45:
            puntos += 12
            motivos.append("descripción muy parecida")

    mismo_precio = _cerca(nuevo.get("price_eur"), conocido.get("price_eur"), 0.02) is True
    if mismo_precio:
        puntos += 8
        # Clavar superficie y precio a la vez, viniendo de portales distintos, no es
        # casualidad: es el mismo anuncio replicado por la agencia y el portal.
        if sup is True:
            puntos += 20
            motivos.append("misma superficie y el mismo precio exacto")
    elif _cerca(nuevo.get("price_eur"), conocido.get("price_eur"), 0.10) is True:
        puntos += 8
    elif _cerca(nuevo.get("price_eur"), conocido.get("price_eur"), 0.30):
        puntos += 3

    if not señal_fuerte:
        return 0, motivos
    return max(0, min(100, puntos)), motivos


UMBRAL_MISMO_INMUEBLE = 60


# --------------------------------------------------------------------- Alertas

TIPOS_ALERTA: Dict[str, Tuple[str, str, str]] = {
    "bajada_fuerte": ("🔻", "alta", "Bajada fuerte de precio"),
    "bajada_acumulada": ("📉", "alta", "Bajada acumulada importante"),
    "vuelve_mas_barato": ("♻️", "alta", "Vuelve a publicarse más barato"),
    "vuelve_a_cero": ("♻️", "media", "Republicado para borrar el tiempo en venta"),
    "reaparece": ("↩️", "media", "Vuelve a estar publicado"),
    "desaparece": ("👻", "media", "Ha desaparecido del portal"),
    "duplicado_mas_barato": ("👯", "alta", "El mismo inmueble, más barato en otro anuncio"),
    "yoyo": ("🎢", "media", "El precio sube y baja"),
    "estancado": ("🕰️", "media", "Mucho tiempo en venta y sin bajar"),
    "primera_bajada": ("🪧", "media", "Primera bajada después de mucho tiempo"),
    "bajo_mercado": ("💎", "alta", "Muy por debajo del €/m² de su zona"),
    "subida": ("🔺", "info", "Ha subido de precio"),
}

ORDEN_GRAVEDAD = {"alta": 0, "media": 1, "info": 2}

REGLAS_POR_DEFECTO: Dict[str, Any] = {
    "bajada_fuerte_pct": 5.0,
    "bajada_fuerte_eur": 10000,
    "bajada_acumulada_pct": 15.0,
    "republicacion_dias": 7,
    "republicacion_mas_barato_pct": 3.0,
    "duplicado_dif_pct": 3.0,
    "estancado_dias": 180,
    "primera_bajada_dias": 90,
    "bajo_mercado_factor": 0.70,
    "bajo_mercado_min_comparables": 5,
    "bajo_mercado_minimo_creible": 0.20,
    "yoyo_min_cambios": 3,
    "conservar_alertas_dias": 180,
    "runs_sin_ver_para_retirar": 2,
}


def eur(v: Any) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", ".") + " €"
    except (TypeError, ValueError):
        return "sin precio"


def _alerta(kind: str, prop_id: str, listing: Dict[str, Any], detalle: str, clave: str,
            datos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    icono, gravedad, titulo = TIPOS_ALERTA[kind]
    return {
        "kind": kind,
        "icono": icono,
        "gravedad": gravedad,
        "titulo": titulo,
        "detalle": detalle,
        "prop_id": prop_id,
        "listing_id": listing.get("id"),
        "listing_title": listing.get("title"),
        "url": listing.get("url"),
        "zone_name": listing.get("zone_name"),
        "price_eur": listing.get("price_eur"),
        "clave": f"{kind}|{prop_id}|{clave}",
        "datos": datos or {},
    }


def alertas_de_cambio_de_precio(prop_id: str, listing: Dict[str, Any], precio_anterior: float,
                                precio_nuevo: float, reglas: Dict[str, Any],
                                dias_en_venta: Optional[int], era_la_primera_bajada: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    dif = precio_nuevo - precio_anterior
    pct = abs(dif) / precio_anterior * 100.0 if precio_anterior else 0.0
    clave = str(int(precio_nuevo))

    if dif < 0:
        if pct >= reglas["bajada_fuerte_pct"] or abs(dif) >= reglas["bajada_fuerte_eur"]:
            out.append(_alerta(
                "bajada_fuerte", prop_id, listing,
                f"De {eur(precio_anterior)} a {eur(precio_nuevo)}: {eur(abs(dif))} menos ({pct:.1f} %).",
                clave, {"pct": round(pct, 1), "dif_eur": dif},
            ))
        if era_la_primera_bajada and (dias_en_venta or 0) >= reglas["primera_bajada_dias"]:
            out.append(_alerta(
                "primera_bajada", prop_id, listing,
                f"Primera bajada tras {dias_en_venta} días en venta. El vendedor ha empezado a moverse.",
                clave, {"dias": dias_en_venta},
            ))
    elif dif > 0:
        out.append(_alerta(
            "subida", prop_id, listing,
            f"De {eur(precio_anterior)} a {eur(precio_nuevo)}: {eur(dif)} más ({pct:.1f} %).",
            clave, {"pct": round(pct, 1), "dif_eur": dif},
        ))
    return out


def alertas_de_republicacion(prop_id: str, listing: Dict[str, Any], tramo_anterior: Dict[str, Any],
                             precio_nuevo: Optional[float], reglas: Dict[str, Any],
                             primera_vez: Optional[str], ahora: Optional[str] = None) -> List[Dict[str, Any]]:
    """Cuando un inmueble que había desaparecido vuelve a salir publicado."""
    dias_fuera = dias_entre(tramo_anterior.get("ended_at"), ahora) or 0
    if dias_fuera < reglas["republicacion_dias"]:
        return []

    precio_viejo = tramo_anterior.get("end_price_eur")
    desde = dias_entre(primera_vez, ahora)
    coletilla = f" Lleva en venta desde hace {desde} días, aunque el anuncio parezca nuevo." if desde else ""
    clave = f"{int(precio_nuevo or 0)}|{dias_fuera}"

    if precio_viejo and precio_nuevo:
        dif_pct = (precio_viejo - precio_nuevo) / precio_viejo * 100.0
        if dif_pct >= reglas["republicacion_mas_barato_pct"]:
            return [_alerta(
                "vuelve_mas_barato", prop_id, listing,
                f"Estuvo {dias_fuera} días retirado y vuelve a {eur(precio_nuevo)}, "
                f"{dif_pct:.1f} % por debajo de los {eur(precio_viejo)} a los que estaba.{coletilla}",
                clave, {"dias_fuera": dias_fuera, "pct": round(dif_pct, 1)},
            )]
        if abs(dif_pct) <= reglas["republicacion_mas_barato_pct"]:
            return [_alerta(
                "vuelve_a_cero", prop_id, listing,
                f"Retirado {dias_fuera} días y republicado al mismo precio. "
                f"Suele hacerse para que el anuncio figure como recién puesto.{coletilla}",
                clave, {"dias_fuera": dias_fuera},
            )]

    return [_alerta(
        "reaparece", prop_id, listing,
        f"Vuelve a estar publicado tras {dias_fuera} días retirado.{coletilla}",
        clave, {"dias_fuera": dias_fuera},
    )]


def alerta_desaparicion(prop_id: str, listing: Dict[str, Any], dias_publicado: Optional[int],
                        bajada_pct: Optional[float]) -> Dict[str, Any]:
    extra = f" Había bajado un {bajada_pct:.1f} % desde su precio más alto." if bajada_pct and bajada_pct >= 5 else ""
    txt = f"Ya no aparece en el portal tras {dias_publicado} días publicado." if dias_publicado is not None \
        else "Ya no aparece en el portal."
    return _alerta("desaparece", prop_id, listing, txt + extra,
                   str(int(listing.get("price_eur") or 0)), {"dias": dias_publicado})


def alertas_de_estado(propiedades: List[Dict[str, Any]], medianas_zona: Dict[str, Any],
                      reglas: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Alertas que no nacen de un cambio puntual, sino de mirar la foto completa:
    duplicados más baratos, precios que suben y bajan, anuncios estancados y
    gangas respecto a la mediana de su zona.
    """
    out: List[Dict[str, Any]] = []
    for p in propiedades:
        anuncios = [a for a in p.get("listings", []) if a.get("status") != "retirado"]
        if not anuncios:
            continue
        ref = anuncios[0]
        prop_id = p["prop_id"]
        dias_desde = p.get("dias_desde_primera_vez")

        # El mismo inmueble publicado en dos sitios a precios distintos
        con_precio = [a for a in anuncios if a.get("price_eur")]
        if len(con_precio) >= 2:
            barato = min(con_precio, key=lambda a: a["price_eur"])
            caro = max(con_precio, key=lambda a: a["price_eur"])
            dif_pct = (caro["price_eur"] - barato["price_eur"]) / caro["price_eur"] * 100.0
            if dif_pct >= reglas["duplicado_dif_pct"]:
                out.append(_alerta(
                    "duplicado_mas_barato", prop_id, barato,
                    f"El mismo inmueble está a {eur(barato['price_eur'])} en {barato.get('portal') or 'un portal'} "
                    f"y a {eur(caro['price_eur'])} en {caro.get('portal') or 'otro'}: "
                    f"{dif_pct:.1f} % de diferencia por el mismo sitio.",
                    f"{int(barato['price_eur'])}|{int(caro['price_eur'])}",
                    {"pct": round(dif_pct, 1)},
                ))

        historial = p.get("price_history") or []
        cambios = [h for h in historial if h.get("change_eur")]
        subidas = [h for h in cambios if h["change_eur"] > 0]
        bajadas = [h for h in cambios if h["change_eur"] < 0]

        if len(cambios) >= reglas["yoyo_min_cambios"] and subidas and bajadas:
            out.append(_alerta(
                "yoyo", prop_id, ref,
                f"{len(bajadas)} bajadas y {len(subidas)} subidas de precio. "
                f"O están tanteando el mercado, o el precio no es firme.",
                str(len(cambios)), {"bajadas": len(bajadas), "subidas": len(subidas)},
            ))

        if not cambios and (dias_desde or 0) >= reglas["estancado_dias"]:
            out.append(_alerta(
                "estancado", prop_id, ref,
                f"{dias_desde} días en venta sin tocar el precio ni una vez. "
                f"Es el perfil típico de vendedor al que se le puede negociar.",
                str((dias_desde or 0) // 30), {"dias": dias_desde},
            ))

        bajada_total = p.get("price_drop_pct") or 0
        if bajada_total >= reglas["bajada_acumulada_pct"]:
            out.append(_alerta(
                "bajada_acumulada", prop_id, ref,
                f"Acumula un {bajada_total:.1f} % de bajada desde su precio más alto "
                f"({eur(p.get('max_price_eur'))} → {eur(ref.get('price_eur'))}).",
                str(int(bajada_total // 5 * 5)), {"pct": bajada_total},
            ))

        em2 = ref.get("eur_per_m2")
        z = medianas_zona.get(f"{ref.get('zone_id') or ''}|{ref.get('asset_type') or ''}")
        if em2 and z and z.get("mediana") and z.get("n", 0) >= reglas["bajo_mercado_min_comparables"]:
                # Por debajo del mínimo creíble no es una ganga: es un precio o una
            # superficie mal leídos en el anuncio, y avisar de eso solo da ruido.
            if em2 < z["mediana"] * reglas["bajo_mercado_minimo_creible"]:
                continue
            if em2 <= z["mediana"] * reglas["bajo_mercado_factor"]:
                out.append(_alerta(
                    "bajo_mercado", prop_id, ref,
                    f"{em2:.0f} €/m² frente a los {z['mediana']:.0f} €/m² de mediana en "
                    f"{ref.get('zone_name') or 'su zona'} ({z['n']} comparables).",
                    str(int(em2)), {"eur_m2": em2, "mediana": z["mediana"]},
                ))
    return out


def ordena_alertas(alertas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        alertas,
        key=lambda a: (ORDEN_GRAVEDAD.get(a.get("gravedad"), 9), str(a.get("created_at") or ""), a.get("kind") or ""),
    )
