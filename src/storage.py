# -*- coding: utf-8 -*-
"""
Persistencia histórica en SQLite + Exportación a JSON/JS para el Panel Web en GitHub Pages.
Registra altas, cambios de precio (bajadas y subidas), histórico completo de observaciones
y estadísticas de €/m² por zona.
"""

import datetime
import json
import os
import sqlite3
import statistics
from typing import Any, Dict, List, Optional, Tuple

from . import tracking as tk


class StorageManager:
    def __init__(self, db_path: Optional[str] = None, docs_data_dir: Optional[str] = None,
                 reglas: Optional[Dict[str, Any]] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(base_dir, "data", "solares.db")
        self.docs_data_dir = docs_data_dir or os.path.join(base_dir, "docs", "data")
        self.reglas = dict(tk.REGLAS_POR_DEFECTO)
        self.reglas.update(reglas or {})
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.docs_data_dir, exist_ok=True)
        self._init_db()
        migrados = self._backfill_inmuebles()
        if migrados:
            print(f"[Seguimiento] {migrados} anuncios que ya estaban guardados se han "
                  f"dado de alta conservando su fecha de primera aparición.")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY,
                    portal TEXT,
                    title TEXT,
                    url TEXT,
                    zone_id TEXT,
                    zone_name TEXT,
                    tier INTEGER,
                    location_raw TEXT,
                    lat REAL,
                    lon REAL,
                    asset_type TEXT,
                    asset_label TEXT,
                    is_target_type INTEGER,
                    is_orihuela_costa INTEGER,
                    initial_price_eur REAL,
                    price_eur REAL,
                    min_price_eur REAL,
                    max_price_eur REAL,
                    price_drop_eur REAL DEFAULT 0,
                    price_drop_pct REAL DEFAULT 0,
                    surface_plot_m2 REAL,
                    surface_built_m2 REAL,
                    effective_plot_m2 REAL,
                    rooms INTEGER,
                    eur_per_m2 REAL,
                    discount_vs_ref_pct REAL,
                    is_highlighted INTEGER,
                    chollo_score INTEGER,
                    chollo_reasons_json TEXT,
                    description TEXT,
                    image_url TEXT,
                    phone TEXT,
                    first_seen_at TEXT,
                    last_seen_at TEXT,
                    last_price_change_at TEXT,
                    status TEXT DEFAULT 'active',
                    times_seen INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id TEXT NOT NULL,
                    price_eur REAL NOT NULL,
                    eur_per_m2 REAL,
                    recorded_at TEXT NOT NULL,
                    change_eur REAL DEFAULT 0,
                    change_pct REAL DEFAULT 0,
                    FOREIGN KEY(listing_id) REFERENCES listings(id)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ran_at TEXT NOT NULL,
                    total_scraped INTEGER,
                    new_count INTEGER,
                    price_drops_count INTEGER,
                    price_increases_count INTEGER,
                    sources_summary_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_listings_zone ON listings(zone_id);
                CREATE INDEX IF NOT EXISTS idx_listings_highlighted ON listings(is_highlighted);
                CREATE INDEX IF NOT EXISTS idx_history_listing ON price_history(listing_id);
                """
            )
            for col, decl in (
                ("rooms", "INTEGER"),
                ("prop_id", "TEXT"),
                ("missing_runs", "INTEGER DEFAULT 0"),
                ("delisted_at", "TEXT"),
                ("sin_filtro", "INTEGER DEFAULT 0"),
            ):
                try:
                    conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {decl}")
                except Exception:
                    pass

            # Seguimiento: el inmueble (properties) vive por encima del anuncio (listings).
            # Un inmueble puede tener varios anuncios, y cada anuncio varios tramos
            # publicados (spells) si lo retiran y lo vuelven a poner.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS properties (
                    prop_id TEXT PRIMARY KEY,
                    zone_id TEXT,
                    zone_name TEXT,
                    asset_type TEXT,
                    effective_plot_m2 REAL,
                    surface_built_m2 REAL,
                    rooms INTEGER,
                    phone TEXT,
                    title TEXT,
                    location_raw TEXT,
                    price_eur REAL,
                    first_listed_at TEXT,
                    last_seen_at TEXT,
                    listings_count INTEGER DEFAULT 1,
                    republicaciones INTEGER DEFAULT 0,
                    match_reasons_json TEXT
                );

                CREATE TABLE IF NOT EXISTS listing_spells (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id TEXT NOT NULL,
                    prop_id TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    start_price_eur REAL,
                    end_price_eur REAL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT,
                    kind TEXT,
                    gravedad TEXT,
                    icono TEXT,
                    titulo TEXT,
                    detalle TEXT,
                    prop_id TEXT,
                    listing_id TEXT,
                    listing_title TEXT,
                    url TEXT,
                    zone_name TEXT,
                    price_eur REAL,
                    clave TEXT,
                    datos_json TEXT,
                    vista INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_listings_prop ON listings(prop_id);
                CREATE INDEX IF NOT EXISTS idx_spells_prop ON listing_spells(prop_id);
                CREATE INDEX IF NOT EXISTS idx_spells_listing ON listing_spells(listing_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_clave ON alerts(clave);
                CREATE INDEX IF NOT EXISTS idx_alerts_prop ON alerts(prop_id);
                """
            )
            # Subastas del BOE: tabla propia (no se mezclan con los anuncios de venta)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS auctions (
                    id TEXT PRIMARY KEY,
                    id_subasta TEXT,
                    data_json TEXT NOT NULL,
                    first_seen_at TEXT,
                    last_seen_at TEXT,
                    status TEXT DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS boe_cache (
                    id_subasta TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    fetched_at TEXT
                );
                """
            )

    def _backfill_inmuebles(self) -> int:
        """
        Primera ejecución con el seguimiento activado: da de alta un inmueble y su
        primer tramo publicado por cada anuncio que ya estaba en la base de datos,
        conservando la fecha en que se vio por primera vez. Sin esto, actualizar el
        agente pondría todos los anuncios "a la venta desde hoy".
        """
        with self._connect() as conn:
            pendientes = conn.execute("SELECT * FROM listings WHERE prop_id IS NULL").fetchall()
            for r in pendientes:
                desde = r["first_seen_at"] or r["last_seen_at"] or tk.ahora_iso()
                prop_id, _, _ = self._resolver_inmueble(
                    conn, dict(r), r["last_seen_at"] or desde, desde=desde
                )
                conn.execute("UPDATE listings SET prop_id = ? WHERE id = ?", (prop_id, r["id"]))
                self._abrir_tramo(conn, r["id"], prop_id, desde, r["initial_price_eur"] or r["price_eur"])
                if r["status"] == "retirado":
                    self._cerrar_tramo(conn, r["id"], r["delisted_at"] or r["last_seen_at"] or desde, r["price_eur"])
        return len(pendientes)

    # ------------------------------------------------- Identidad del inmueble
    def _resolver_inmueble(self, conn, item: Dict[str, Any], now_str: str,
                           desde: Optional[str] = None) -> Tuple[str, bool, List[str]]:
        """
        Decide a qué inmueble pertenece un anuncio. Si encuentra uno ya conocido con
        la misma superficie, teléfono o descripción, lo engancha a él: así el anuncio
        hereda la fecha en la que ese inmueble salió a la venta por primera vez,
        aunque esta sea su tercera republicación.
        """
        candidatas = conn.execute(
            "SELECT * FROM properties WHERE zone_id IS ? AND asset_type IS ?",
            (item.get("zone_id"), item.get("asset_type")),
        ).fetchall()

        abiertos = {
            r["prop_id"]
            for r in conn.execute("SELECT DISTINCT prop_id FROM listing_spells WHERE ended_at IS NULL").fetchall()
        }

        mejor, mejor_puntos, mejor_motivos = None, 0, []
        for c in candidatas:
            conocido = dict(c)
            conocido["_sigue_publicado"] = conocido["prop_id"] in abiertos
            puntos, motivos = tk.parecido(item, conocido)
            if puntos > mejor_puntos:
                mejor, mejor_puntos, mejor_motivos = c, puntos, motivos

        if mejor is not None and mejor_puntos >= tk.UMBRAL_MISMO_INMUEBLE:
            prop_id = mejor["prop_id"]
            conn.execute(
                """
                UPDATE properties SET
                    last_seen_at = ?,
                    price_eur = COALESCE(?, price_eur),
                    phone = COALESCE(NULLIF(?, ''), phone),
                    rooms = COALESCE(?, rooms),
                    surface_built_m2 = COALESCE(?, surface_built_m2)
                WHERE prop_id = ?
                """,
                (now_str, item.get("price_eur"), item.get("phone") or "", item.get("rooms"),
                 item.get("surface_built_m2"), prop_id),
            )
            return prop_id, False, mejor_motivos

        prop_id = tk.huella(item)
        # La huella puede chocar con otro inmueble muy parecido: si ya existe, se desambigua
        if conn.execute("SELECT 1 FROM properties WHERE prop_id = ?", (prop_id,)).fetchone():
            prop_id = f"{prop_id}-{str(item.get('id'))[-6:]}"
        conn.execute(
            """
            INSERT OR IGNORE INTO properties (
                prop_id, zone_id, zone_name, asset_type, effective_plot_m2, surface_built_m2,
                rooms, phone, title, location_raw, price_eur, first_listed_at, last_seen_at,
                listings_count, republicaciones, match_reasons_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, '[]')
            """,
            (prop_id, item.get("zone_id"), item.get("zone_name"), item.get("asset_type"),
             item.get("effective_plot_m2"), item.get("surface_built_m2"), item.get("rooms"),
             item.get("phone") or "", item.get("title"), item.get("location_raw"),
             item.get("price_eur"), desde or now_str, now_str),
        )
        return prop_id, True, []

    def _tramo_abierto(self, conn, listing_id: str):
        return conn.execute(
            "SELECT * FROM listing_spells WHERE listing_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (listing_id,),
        ).fetchone()

    def _ultimo_tramo_cerrado(self, conn, prop_id: str) -> Optional[Dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM listing_spells WHERE prop_id = ? AND ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1",
            (prop_id,),
        ).fetchone()
        return dict(row) if row else None

    def _abrir_tramo(self, conn, listing_id: str, prop_id: str, now_str: str, precio: Optional[float]) -> None:
        if self._tramo_abierto(conn, listing_id):
            return
        conn.execute(
            "INSERT INTO listing_spells (listing_id, prop_id, started_at, start_price_eur) VALUES (?, ?, ?, ?)",
            (listing_id, prop_id, now_str, precio),
        )

    def _cerrar_tramo(self, conn, listing_id: str, now_str: str, precio: Optional[float]) -> None:
        tramo = self._tramo_abierto(conn, listing_id)
        if tramo:
            conn.execute(
                "UPDATE listing_spells SET ended_at = ?, end_price_eur = ? WHERE id = ?",
                (now_str, precio, tramo["id"]),
            )

    def upsert_listings(self, analyzed_items: List[Dict[str, Any]], now_iso: Optional[str] = None) -> Dict[str, Any]:
        """
        Inserta nuevos inmuebles o actualiza existentes, detectando bajadas y subidas de precio.
        Devuelve resumen con (new_items, price_drops, price_increases, updated_items).
        """
        now_str = now_iso or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        today_date = now_str[:10]

        new_items: List[Dict[str, Any]] = []
        price_drops: List[Dict[str, Any]] = []
        price_increases: List[Dict[str, Any]] = []
        alertas: List[Dict[str, Any]] = []
        republicados: List[Dict[str, Any]] = []

        with self._connect() as conn:
            for item in analyzed_items:
                # Ignorar pisos en altura, rústicos, parcelas > 2000 m2 o costa.
                # En las zonas sin filtro (Montepinar) no se descarta nada.
                eff_m2 = item.get("effective_plot_m2") or 0
                sin_filtro = bool(item.get("sin_filtro"))
                if not sin_filtro and (
                    item.get("asset_type") in ("descartado_piso", "rustico_dudoso")
                    or item.get("is_orihuela_costa")
                    or eff_m2 > 2000
                ):
                    continue

                lid = item["id"]
                cur_price = item.get("price_eur")
                row = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()

                # En un anuncio que ya estaba en la base de datos, el inmueble se da de alta
                # con su fecha original: así actualizar el agente no reinicia el tiempo en venta.
                prop_id, prop_nueva, motivos = self._resolver_inmueble(
                    conn, item, now_str, desde=(row["first_seen_at"] if row else None)
                )
                item["prop_id"] = prop_id

                if row is None:
                    # Nuevo anuncio detectado
                    conn.execute(
                        """
                        INSERT INTO listings (
                            id, portal, title, url, zone_id, zone_name, tier, location_raw,
                            lat, lon, asset_type, asset_label, is_target_type, is_orihuela_costa,
                            initial_price_eur, price_eur, min_price_eur, max_price_eur,
                            price_drop_eur, price_drop_pct,
                            surface_plot_m2, surface_built_m2, effective_plot_m2, rooms,
                            eur_per_m2, discount_vs_ref_pct, is_highlighted,
                            chollo_score, chollo_reasons_json, description, image_url, phone,
                            first_seen_at, last_seen_at, last_price_change_at, status, times_seen,
                            prop_id, missing_runs, sin_filtro
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            0, 0,
                            ?, ?, ?, ?,
                            ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, NULL, 'new', 1,
                            ?, 0, ?
                        )
                        """,
                        (
                            lid,
                            item.get("portal"),
                            item.get("title"),
                            item.get("url"),
                            item.get("zone_id"),
                            item.get("zone_name"),
                            item.get("tier", 1),
                            item.get("location_raw"),
                            item.get("lat"),
                            item.get("lon"),
                            item.get("asset_type"),
                            item.get("asset_label"),
                            1 if item.get("is_target_type") else 0,
                            1 if item.get("is_orihuela_costa") else 0,
                            cur_price,
                            cur_price,
                            cur_price,
                            cur_price,
                            item.get("surface_plot_m2"),
                            item.get("surface_built_m2"),
                            item.get("effective_plot_m2"),
                            item.get("rooms"),
                            item.get("eur_per_m2"),
                            item.get("discount_vs_ref_pct"),
                            1 if item.get("is_highlighted") else 0,
                            item.get("chollo_score", 50),
                            json.dumps(item.get("chollo_reasons", []), ensure_ascii=False),
                            item.get("description", ""),
                            item.get("image_url", ""),
                            item.get("phone", ""),
                            now_str,
                            now_str,
                            prop_id,
                            1 if sin_filtro else 0,
                        ),
                    )
                    if cur_price and cur_price > 0:
                        conn.execute(
                            """
                            INSERT INTO price_history (listing_id, price_eur, eur_per_m2, recorded_at, change_eur, change_pct)
                            VALUES (?, ?, ?, ?, 0, 0)
                            """,
                            (lid, cur_price, item.get("eur_per_m2"), today_date),
                        )

                    prop = conn.execute(
                        "SELECT first_listed_at FROM properties WHERE prop_id = ?", (prop_id,)
                    ).fetchone()
                    primera_vez = prop["first_listed_at"] if prop else now_str

                    # Si el inmueble ya tiene otro anuncio vivo, esto es un duplicado
                    # (el mismo sitio en dos portales), no una republicación.
                    es_duplicado = conn.execute(
                        "SELECT 1 FROM listing_spells WHERE prop_id = ? AND ended_at IS NULL LIMIT 1",
                        (prop_id,),
                    ).fetchone() is not None
                    tramo_previo = (
                        None if (prop_nueva or es_duplicado) else self._ultimo_tramo_cerrado(conn, prop_id)
                    )
                    self._abrir_tramo(conn, lid, prop_id, now_str, cur_price)

                    if not prop_nueva:
                        conn.execute(
                            """
                            UPDATE properties SET
                                listings_count = listings_count + 1,
                                republicaciones = republicaciones + ?,
                                match_reasons_json = ?
                            WHERE prop_id = ?
                            """,
                            (0 if es_duplicado else 1, json.dumps(motivos, ensure_ascii=False), prop_id),
                        )
                        item["motivos_match"] = motivos
                        item["primera_vez_en_venta"] = primera_vez
                        if es_duplicado:
                            item["es_duplicado"] = True
                        else:
                            item["es_republicacion"] = True
                            republicados.append(item)
                        if tramo_previo:
                            alertas.extend(
                                tk.alertas_de_republicacion(
                                    prop_id, item, tramo_previo, cur_price, self.reglas, primera_vez, now_str
                                )
                            )

                    new_items.append(item)
                else:
                    # Anuncio ya conocido: comprobar si ha cambiado de precio
                    prev_price = row["price_eur"]
                    init_price = row["initial_price_eur"] or cur_price
                    min_price = row["min_price_eur"] or cur_price
                    max_price = row["max_price_eur"] or cur_price
                    last_change_at = row["last_price_change_at"]
                    status = "active"

                    prop = conn.execute(
                        "SELECT first_listed_at FROM properties WHERE prop_id = ?", (prop_id,)
                    ).fetchone()
                    primera_vez = prop["first_listed_at"] if prop else row["first_seen_at"]
                    conn.execute(
                        "UPDATE properties SET last_seen_at = ? WHERE prop_id = ?", (now_str, prop_id)
                    )

                    # El mismo anuncio había desaparecido y vuelve a estar publicado
                    if row["status"] == "retirado" or self._tramo_abierto(conn, lid) is None:
                        tramo_previo = self._ultimo_tramo_cerrado(conn, prop_id)
                        inicio = now_str if row["status"] == "retirado" else (row["first_seen_at"] or now_str)
                        self._abrir_tramo(conn, lid, prop_id, inicio, cur_price)
                        if row["status"] == "retirado":
                            conn.execute(
                                "UPDATE properties SET republicaciones = republicaciones + 1 WHERE prop_id = ?",
                                (prop_id,),
                            )
                            item["es_republicacion"] = True
                            item["primera_vez_en_venta"] = primera_vez
                            republicados.append(item)
                            if tramo_previo:
                                alertas.extend(
                                    tk.alertas_de_republicacion(
                                        prop_id, item, tramo_previo, cur_price, self.reglas, primera_vez, now_str
                                    )
                                )

                    if cur_price and prev_price and abs(cur_price - prev_price) >= 50:
                        diff_eur = cur_price - prev_price
                        diff_pct = round((diff_eur / prev_price) * 100.0, 2)
                        hubo_bajadas = conn.execute(
                            "SELECT 1 FROM price_history WHERE listing_id = ? AND change_eur < 0 LIMIT 1", (lid,)
                        ).fetchone() is not None
                        alertas.extend(
                            tk.alertas_de_cambio_de_precio(
                                prop_id, item, prev_price, cur_price, self.reglas,
                                tk.dias_entre(primera_vez, now_str), era_la_primera_bajada=not hubo_bajadas,
                            )
                        )
                        min_price = min(min_price, cur_price) if min_price else cur_price
                        max_price = max(max_price, cur_price) if max_price else cur_price
                        last_change_at = now_str

                        conn.execute(
                            """
                            INSERT INTO price_history (listing_id, price_eur, eur_per_m2, recorded_at, change_eur, change_pct)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (lid, cur_price, item.get("eur_per_m2"), today_date, diff_eur, diff_pct),
                        )

                        if diff_eur < 0:
                            status = "price_drop"
                            item["prev_price_eur"] = prev_price
                            item["change_eur"] = diff_eur
                            item["change_pct"] = diff_pct
                            price_drops.append(item)
                        else:
                            status = "price_up"
                            item["prev_price_eur"] = prev_price
                            item["change_eur"] = diff_eur
                            item["change_pct"] = diff_pct
                            price_increases.append(item)
                    else:
                        status = row["status"] if row["status"] == "price_drop" else "active"

                    # Calcular bajada acumulada respecto al precio máximo o inicial
                    ref_high = max(init_price or 0, max_price or 0)
                    if cur_price and ref_high and ref_high > cur_price:
                        drop_eur = round(ref_high - cur_price, 2)
                        drop_pct = round(((ref_high - cur_price) / ref_high) * 100.0, 1)
                    else:
                        drop_eur = 0.0
                        drop_pct = 0.0

                    conn.execute(
                        """
                        UPDATE listings SET
                            price_eur = COALESCE(?, price_eur),
                            min_price_eur = COALESCE(?, min_price_eur),
                            max_price_eur = COALESCE(?, max_price_eur),
                            price_drop_eur = ?,
                            price_drop_pct = ?,
                            rooms = COALESCE(?, rooms),
                            eur_per_m2 = COALESCE(?, eur_per_m2),
                            discount_vs_ref_pct = COALESCE(?, discount_vs_ref_pct),
                            is_highlighted = ?,
                            chollo_score = ?,
                            chollo_reasons_json = ?,
                            last_seen_at = ?,
                            last_price_change_at = ?,
                            status = ?,
                            times_seen = times_seen + 1,
                            prop_id = ?,
                            sin_filtro = ?,
                            missing_runs = 0,
                            delisted_at = NULL
                        WHERE id = ?
                        """,
                        (
                            cur_price,
                            min_price,
                            max_price,
                            drop_eur,
                            drop_pct,
                            item.get("rooms"),
                            item.get("eur_per_m2"),
                            item.get("discount_vs_ref_pct"),
                            1 if item.get("is_highlighted") else 0,
                            item.get("chollo_score", row["chollo_score"]),
                            json.dumps(item.get("chollo_reasons", []), ensure_ascii=False),
                            now_str,
                            last_change_at,
                            status,
                            prop_id,
                            1 if sin_filtro else 0,
                            lid,
                        ),
                    )
                    conn.execute(
                        "UPDATE properties SET price_eur = COALESCE(?, price_eur) WHERE prop_id = ?",
                        (cur_price, prop_id),
                    )

        return {
            "new_items": new_items,
            "price_drops": price_drops,
            "price_increases": price_increases,
            "republicados": republicados,
            "alertas": alertas,
            "ran_at": now_str,
        }

    # --------------------------------------------- Desaparición y reaparición
    @staticmethod
    def _dias_visibles(tramos: List[Dict[str, Any]], ahora: Optional[str] = None) -> int:
        """Días que un inmueble ha estado publicado, uniendo tramos solapados."""
        fin_por_defecto = tk.a_fecha(ahora) or datetime.datetime.utcnow()
        intervalos = []
        for t in tramos:
            ini = tk.a_fecha(t.get("started_at"))
            fin = tk.a_fecha(t.get("ended_at")) or fin_por_defecto
            if ini and fin > ini:
                intervalos.append((ini, fin))
        if not intervalos:
            return 0
        intervalos.sort()
        total = datetime.timedelta()
        ini_act, fin_act = intervalos[0]
        for ini, fin in intervalos[1:]:
            if ini <= fin_act:
                fin_act = max(fin_act, fin)
            else:
                total += fin_act - ini_act
                ini_act, fin_act = ini, fin
        total += fin_act - ini_act
        return total.days

    def _dias_publicado(self, conn, listing_id: str, ahora: Optional[str] = None) -> Optional[int]:
        """Días que un anuncio ha estado realmente visible, sumando todos sus tramos."""
        filas = conn.execute(
            "SELECT started_at, ended_at FROM listing_spells WHERE listing_id = ?", (listing_id,)
        ).fetchall()
        if not filas:
            return None
        total = 0
        for f in filas:
            d = tk.dias_entre(f["started_at"], f["ended_at"] or ahora)
            if d is not None:
                total += d
        return total

    def marcar_desaparecidos(self, portales_ok: List[str], now_iso: Optional[str] = None) -> Dict[str, Any]:
        """
        Marca como retirado lo que ha dejado de aparecer. Solo se fija en anuncios de
        portales que hoy han respondido: si Idealista se cae, sus anuncios no se dan
        por retirados. Y espera a varias ejecuciones seguidas sin verlo, para que un
        fallo puntual de paginación no cuente como retirada.
        """
        now_str = now_iso or tk.ahora_iso()
        dia = now_str[:10]
        umbral = max(1, int(self.reglas["runs_sin_ver_para_retirar"]))
        ok = set(portales_ok or [])
        retirados: List[Dict[str, Any]] = []
        alertas: List[Dict[str, Any]] = []

        if not ok:
            return {"retirados": [], "alertas": [], "en_duda": 0}

        en_duda = 0
        with self._connect() as conn:
            filas = conn.execute("SELECT * FROM listings WHERE status != 'retirado'").fetchall()
            for r in filas:
                if (r["portal"] or "") not in ok:
                    continue
                if (r["last_seen_at"] or "")[:10] >= dia:
                    continue

                faltas = (r["missing_runs"] or 0) + 1
                if faltas < umbral:
                    conn.execute("UPDATE listings SET missing_runs = ? WHERE id = ?", (faltas, r["id"]))
                    en_duda += 1
                    continue

                conn.execute(
                    "UPDATE listings SET status = 'retirado', missing_runs = ?, delisted_at = ? WHERE id = ?",
                    (faltas, now_str, r["id"]),
                )
                self._cerrar_tramo(conn, r["id"], now_str, r["price_eur"])
                item = dict(r)
                alertas.append(
                    tk.alerta_desaparicion(
                        r["prop_id"] or r["id"], item,
                        self._dias_publicado(conn, r["id"], now_str), r["price_drop_pct"],
                    )
                )
                retirados.append(item)

        return {"retirados": retirados, "alertas": alertas, "en_duda": en_duda}

    # ------------------------------------------------------------- Alertas
    def guardar_alertas(self, alertas: List[Dict[str, Any]], now_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        """Guarda las alertas nuevas. La clave evita que la misma alerta salga cada día."""
        now_str = now_iso or tk.ahora_iso()
        nuevas: List[Dict[str, Any]] = []
        with self._connect() as conn:
            for a in alertas:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO alerts (
                        created_at, kind, gravedad, icono, titulo, detalle, prop_id, listing_id,
                        listing_title, url, zone_name, price_eur, clave, datos_json, vista
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (now_str, a.get("kind"), a.get("gravedad"), a.get("icono"), a.get("titulo"),
                     a.get("detalle"), a.get("prop_id"), a.get("listing_id"), a.get("listing_title"),
                     a.get("url"), a.get("zone_name"), a.get("price_eur"), a.get("clave"),
                     json.dumps(a.get("datos") or {}, ensure_ascii=False)),
                )
                if cur.rowcount:
                    a["created_at"] = now_str
                    nuevas.append(a)

            base = tk.a_fecha(now_str) or datetime.datetime.utcnow()
            corte = (
                base - datetime.timedelta(days=int(self.reglas["conservar_alertas_dias"]))
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute("DELETE FROM alerts WHERE created_at < ?", (corte,))
        return nuevas

    def get_alertas(self, limite: int = 250) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            filas = conn.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limite,)
            ).fetchall()
        out = []
        for f in filas:
            d = dict(f)
            try:
                d["datos"] = json.loads(d.pop("datos_json") or "{}")
            except Exception:
                d["datos"] = {}
            d["dias"] = tk.dias_entre(d.get("created_at"))
            out.append(d)
        return out

    def get_propiedades(self, listings: Optional[List[Dict[str, Any]]] = None,
                        ahora: Optional[str] = None) -> List[Dict[str, Any]]:
        """Agrupa los anuncios por inmueble, juntando su historial de precios completo."""
        items = listings if listings is not None else self.get_all_listings()
        with self._connect() as conn:
            props = {r["prop_id"]: dict(r) for r in conn.execute("SELECT * FROM properties").fetchall()}

        por_prop: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            pid = it.get("prop_id")
            if pid:
                por_prop.setdefault(pid, []).append(it)

        out: List[Dict[str, Any]] = []
        for pid, anuncios in por_prop.items():
            p = props.get(pid, {"prop_id": pid})
            anuncios = sorted(anuncios, key=lambda a: (a.get("status") == "retirado", a.get("price_eur") or 9e9))
            historial: List[Dict[str, Any]] = []
            for a in anuncios:
                historial.extend(a.get("price_history") or [])
            historial.sort(key=lambda h: str(h.get("date") or ""))
            precios = [h["price"] for h in historial if h.get("price")]
            vivos = [a for a in anuncios if a.get("status") != "retirado"]
            actual = (vivos or anuncios)[0].get("price_eur")
            maximo = max(precios) if precios else actual
            bajada = round((maximo - actual) / maximo * 100.0, 1) if maximo and actual and maximo > actual else 0.0

            out.append({
                "prop_id": pid,
                "listings": anuncios,
                "price_history": historial,
                "max_price_eur": maximo,
                "price_drop_pct": bajada,
                "first_listed_at": p.get("first_listed_at"),
                "dias_desde_primera_vez": tk.dias_entre(p.get("first_listed_at"), ahora),
                "republicaciones": p.get("republicaciones") or 0,
                "listings_count": len(anuncios),
            })
        return out

    def medianas_por_zona(self, listings: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Mediana de €/m² por zona y tipo de inmueble, para detectar lo que está muy por debajo."""
        grupos: Dict[str, List[float]] = {}
        for x in listings:
            if x.get("status") == "retirado":
                continue
            em2 = x.get("eur_per_m2")
            if em2 and 20 <= em2 <= 2500:
                grupos.setdefault(f"{x.get('zone_id') or ''}|{x.get('asset_type') or ''}", []).append(em2)
        return {
            k: {"mediana": round(statistics.median(v), 1), "n": len(v)}
            for k, v in grupos.items()
        }

    def generar_alertas_de_estado(self, listings: Optional[List[Dict[str, Any]]] = None,
                                  ahora: Optional[str] = None) -> List[Dict[str, Any]]:
        """Alertas que salen de mirar la foto completa, no de un cambio de hoy."""
        items = listings if listings is not None else self.get_all_listings()
        return tk.alertas_de_estado(
            self.get_propiedades(items, ahora), self.medianas_por_zona(items), self.reglas
        )

    # ------------------------------------------------------------ Subastas BOE
    def load_boe_cache(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id_subasta, data_json FROM boe_cache").fetchall()
        out: Dict[str, Any] = {}
        for r in rows:
            try:
                out[r["id_subasta"]] = json.loads(r["data_json"])
            except Exception:
                pass
        return out

    def save_boe_cache(self, cache: Dict[str, Any], keep_ids: Optional[List[str]] = None) -> None:
        with self._connect() as conn:
            for k, v in cache.items():
                conn.execute(
                    "INSERT OR REPLACE INTO boe_cache (id_subasta, data_json, fetched_at) VALUES (?, ?, ?)",
                    (k, json.dumps(v, ensure_ascii=False), v.get("fetched_at")),
                )
            if keep_ids is not None:
                # Borra de la caché las subastas que ya no salen en el portal (cerradas, suspendidas...)
                keep = set(keep_ids)
                for (k,) in conn.execute("SELECT id_subasta FROM boe_cache").fetchall():
                    if k not in keep:
                        conn.execute("DELETE FROM boe_cache WHERE id_subasta = ?", (k,))

    def upsert_auctions(self, items: List[Dict[str, Any]], fetch_ok: bool = True) -> Dict[str, Any]:
        """Guarda las subastas en zona. Si la lectura del portal fue completa, marca como cerradas las que ya no aparecen."""
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_items: List[Dict[str, Any]] = []
        seen = set()
        with self._connect() as conn:
            for it in items:
                seen.add(it["id"])
                row = conn.execute("SELECT first_seen_at FROM auctions WHERE id = ?", (it["id"],)).fetchone()
                first_seen = row["first_seen_at"] if row else now_str
                it["first_seen_at"] = first_seen
                it["is_new"] = row is None
                if row is None:
                    new_items.append(it)
                conn.execute(
                    """
                    INSERT INTO auctions (id, id_subasta, data_json, first_seen_at, last_seen_at, status)
                    VALUES (?, ?, ?, ?, ?, 'active')
                    ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json, last_seen_at=excluded.last_seen_at, status='active'
                    """,
                    (it["id"], it.get("id_subasta"), json.dumps(it, ensure_ascii=False), first_seen, now_str),
                )
            if fetch_ok:
                for r in conn.execute("SELECT id FROM auctions WHERE status = 'active'").fetchall():
                    if r["id"] not in seen:
                        conn.execute("UPDATE auctions SET status = 'closed' WHERE id = ?", (r["id"],))
        return {"new_auctions": new_items}

    def get_active_auctions(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT data_json, first_seen_at FROM auctions WHERE status = 'active'").fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["data_json"])
                d["first_seen_at"] = r["first_seen_at"]
                out.append(d)
            except Exception:
                pass
        out.sort(key=lambda x: (not x.get("is_target_type"), -(x.get("score") or 0), x.get("fecha_fin") or ""))
        return out

    def log_run(self, total_scraped: int, new_count: int, drops_count: int, inc_count: int, sources: Dict[str, int]) -> None:
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (ran_at, total_scraped, new_count, price_drops_count, price_increases_count, sources_summary_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_str, total_scraped, new_count, drops_count, inc_count, json.dumps(sources, ensure_ascii=False)),
            )

    def get_all_listings(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM listings ORDER BY is_highlighted DESC, chollo_score DESC, eur_per_m2 ASC"
            ).fetchall()
            history_rows = conn.execute(
                "SELECT listing_id, price_eur, eur_per_m2, recorded_at, change_eur, change_pct FROM price_history ORDER BY recorded_at ASC, id ASC"
            ).fetchall()
            props = {r["prop_id"]: dict(r) for r in conn.execute("SELECT * FROM properties").fetchall()}
            spells: Dict[str, List[Dict[str, Any]]] = {}
            por_prop: Dict[str, List[Dict[str, Any]]] = {}
            for s in conn.execute(
                "SELECT listing_id, prop_id, started_at, ended_at, start_price_eur, end_price_eur "
                "FROM listing_spells ORDER BY started_at ASC, id ASC"
            ).fetchall():
                spells.setdefault(s["listing_id"], []).append(dict(s))
                if s["prop_id"]:
                    por_prop.setdefault(s["prop_id"], []).append(dict(s))

        # Días que el inmueble ha estado visible: se unen los tramos de todos sus
        # anuncios, para no contar dos veces los días en que estaba en dos portales.
        visibles = {pid: self._dias_visibles(tramos) for pid, tramos in por_prop.items()}

        hist_map: Dict[str, List[Dict[str, Any]]] = {}
        for h in history_rows:
            hist_map.setdefault(h["listing_id"], []).append(
                {
                    "date": h["recorded_at"],
                    "price": h["price_eur"],
                    "eur_m2": h["eur_per_m2"],
                    "change_eur": h["change_eur"],
                    "change_pct": h["change_pct"],
                }
            )

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["is_highlighted"] = bool(d["is_highlighted"])
            d["is_target_type"] = bool(d["is_target_type"])
            d["is_orihuela_costa"] = bool(d["is_orihuela_costa"])
            try:
                d["chollo_reasons"] = json.loads(d.pop("chollo_reasons_json") or "[]")
            except Exception:
                d["chollo_reasons"] = []
            d["price_history"] = hist_map.get(d["id"], [])

            tramos = spells.get(d["id"], [])
            d["tramos"] = tramos
            p = props.get(d.get("prop_id") or "")
            primera = (p or {}).get("first_listed_at") or d.get("first_seen_at")
            d["primera_vez_en_venta"] = primera
            d["dias_en_venta"] = tk.dias_entre(primera)
            d["dias_publicado"] = visibles.get(
                d.get("prop_id") or "",
                tk.dias_entre(d.get("first_seen_at"), d.get("delisted_at")),
            )
            d["republicaciones"] = (p or {}).get("republicaciones") or 0
            d["anuncios_del_inmueble"] = (p or {}).get("listings_count") or 1
            d["retirado"] = d.get("status") == "retirado"
            d["sin_filtro"] = bool(d.get("sin_filtro"))
            out.append(d)
        return out

    def compute_stats(self, listings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        todos = listings if listings is not None else self.get_all_listings()
        items = [x for x in todos if not x.get("retirado")]
        retirados = [x for x in todos if x.get("retirado")]
        highlighted = [x for x in items if x.get("is_highlighted")]
        drops = [x for x in items if (x.get("price_drop_pct") or 0) > 0]
        chollos = [x for x in highlighted if (x.get("chollo_score") or 0) >= 72]

        by_zone: Dict[str, Dict[str, Any]] = {}
        for x in items:
            zid = x.get("zone_id") or "orihuela"
            z = by_zone.setdefault(
                zid,
                {
                    "zone_id": zid,
                    "zone_name": x.get("zone_name", zid),
                    "total_count": 0,
                    "highlighted_count": 0,
                    "solar_m2_prices": [],
                    "casa_m2_prices": [],
                    "min_eur_m2": None,
                },
            )
            z["total_count"] += 1
            if x.get("is_highlighted"):
                z["highlighted_count"] += 1
            em2 = x.get("eur_per_m2")
            if em2 and 20 <= em2 <= 2500:
                if x.get("asset_type") == "casa_planta_baja":
                    z["casa_m2_prices"].append(em2)
                elif x.get("asset_type") in ("solar_urbano", "solar_urbanizable"):
                    z["solar_m2_prices"].append(em2)
                if z["min_eur_m2"] is None or em2 < z["min_eur_m2"]:
                    z["min_eur_m2"] = em2

        zone_stats = {}
        for zid, z in by_zone.items():
            s_prices = z.pop("solar_m2_prices")
            c_prices = z.pop("casa_m2_prices")
            z["avg_solar_eur_m2"] = round(statistics.mean(s_prices), 1) if s_prices else None
            z["median_solar_eur_m2"] = round(statistics.median(s_prices), 1) if s_prices else None
            z["avg_casa_eur_m2"] = round(statistics.mean(c_prices), 1) if c_prices else None
            z["median_casa_eur_m2"] = round(statistics.median(c_prices), 1) if c_prices else None
            zone_stats[zid] = z

        all_solar_m2 = [
            x["eur_per_m2"]
            for x in highlighted
            if x.get("eur_per_m2") and x.get("asset_type") in ("solar_urbano", "solar_urbanizable")
        ]
        all_casa_m2 = [
            x["eur_per_m2"]
            for x in highlighted
            if x.get("eur_per_m2") and x.get("asset_type") == "casa_planta_baja"
        ]

        return {
            "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_listings": len(items),
            "retirados_count": len(retirados),
            "sin_filtro_count": sum(1 for x in items if x.get("sin_filtro")),
            "republicados_count": len(
                {x.get("prop_id") for x in items if (x.get("republicaciones") or 0) > 0 and x.get("prop_id")}
            ),
            "highlighted_listings": len(highlighted),
            "secondary_listings": len(items) - len(highlighted),
            "chollos_count": len(chollos),
            "price_drops_count": len(drops),
            "median_solar_eur_m2": round(statistics.median(all_solar_m2), 1) if all_solar_m2 else 210.0,
            "median_casa_eur_m2": round(statistics.median(all_casa_m2), 1) if all_casa_m2 else 450.0,
            "zones": zone_stats,
        }

    def export_web_data(self) -> Dict[str, Any]:
        """
        Exporta docs/data/listings.json y docs/data/listings.js (para que el dashboard funcione
        tanto en GitHub Pages vía fetch como abriendo docs/index.html en local con doble clic).
        """
        listings = self.get_all_listings()
        stats = self.compute_stats(listings)
        auctions = self.get_active_auctions()
        stats["auctions_count"] = len(auctions)
        stats["auctions_target_count"] = sum(1 for a in auctions if a.get("is_target_type"))

        alertas = self.get_alertas()
        stats["alertas_count"] = len(alertas)
        stats["alertas_altas_count"] = sum(1 for a in alertas if a.get("gravedad") == "alta")
        stats["alertas_7d_count"] = sum(1 for a in alertas if (a.get("dias") or 99) <= 7)

        payload = {
            "stats": stats,
            "listings": listings,
            "auctions": auctions,
            "alertas": alertas,
        }

        json_path = os.path.join(self.docs_data_dir, "listings.json")
        js_path = os.path.join(self.docs_data_dir, "listings.js")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        with open(js_path, "w", encoding="utf-8") as f:
            f.write("window.__SOLARES_DATA__ = ")
            json.dump(payload, f, ensure_ascii=False)
            f.write(";\n")

        return payload
