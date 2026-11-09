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


class StorageManager:
    def __init__(self, db_path: Optional[str] = None, docs_data_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(base_dir, "data", "solares.db")
        self.docs_data_dir = docs_data_dir or os.path.join(base_dir, "docs", "data")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.docs_data_dir, exist_ok=True)
        self._init_db()

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

        with self._connect() as conn:
            for item in analyzed_items:
                # Ignorar pisos en altura o costa si están excluidos
                if item.get("asset_type") == "descartado_piso" or item.get("is_orihuela_costa"):
                    continue

                lid = item["id"]
                cur_price = item.get("price_eur")
                row = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()

                if row is None:
                    # Nuevo anuncio detectado
                    conn.execute(
                        """
                        INSERT INTO listings (
                            id, portal, title, url, zone_id, zone_name, tier, location_raw,
                            lat, lon, asset_type, asset_label, is_target_type, is_orihuela_costa,
                            initial_price_eur, price_eur, min_price_eur, max_price_eur,
                            price_drop_eur, price_drop_pct,
                            surface_plot_m2, surface_built_m2, effective_plot_m2,
                            eur_per_m2, discount_vs_ref_pct, is_highlighted,
                            chollo_score, chollo_reasons_json, description, image_url, phone,
                            first_seen_at, last_seen_at, last_price_change_at, status, times_seen
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            0, 0,
                            ?, ?, ?,
                            ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, NULL, 'new', 1
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
                    new_items.append(item)
                else:
                    # Anuncio ya conocido: comprobar si ha cambiado de precio
                    prev_price = row["price_eur"]
                    init_price = row["initial_price_eur"] or cur_price
                    min_price = row["min_price_eur"] or cur_price
                    max_price = row["max_price_eur"] or cur_price
                    last_change_at = row["last_price_change_at"]
                    status = "active"

                    if cur_price and prev_price and abs(cur_price - prev_price) >= 50:
                        diff_eur = cur_price - prev_price
                        diff_pct = round((diff_eur / prev_price) * 100.0, 2)
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
                            eur_per_m2 = COALESCE(?, eur_per_m2),
                            discount_vs_ref_pct = COALESCE(?, discount_vs_ref_pct),
                            is_highlighted = ?,
                            chollo_score = ?,
                            chollo_reasons_json = ?,
                            last_seen_at = ?,
                            last_price_change_at = ?,
                            status = ?,
                            times_seen = times_seen + 1
                        WHERE id = ?
                        """,
                        (
                            cur_price,
                            min_price,
                            max_price,
                            drop_eur,
                            drop_pct,
                            item.get("eur_per_m2"),
                            item.get("discount_vs_ref_pct"),
                            1 if item.get("is_highlighted") else 0,
                            item.get("chollo_score", row["chollo_score"]),
                            json.dumps(item.get("chollo_reasons", []), ensure_ascii=False),
                            now_str,
                            last_change_at,
                            status,
                            lid,
                        ),
                    )

        return {
            "new_items": new_items,
            "price_drops": price_drops,
            "price_increases": price_increases,
            "ran_at": now_str,
        }

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
            out.append(d)
        return out

    def compute_stats(self, listings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        items = listings if listings is not None else self.get_all_listings()
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
        payload = {
            "stats": stats,
            "listings": listings,
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
