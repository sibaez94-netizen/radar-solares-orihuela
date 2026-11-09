# -*- coding: utf-8 -*-
"""
Punto de entrada principal del Agente Monitor de Solares y Casas de Pueblo (Orihuela y Vega Baja).
Se ejecuta diariamente desde GitHub Actions o manualmente con `python main.py`.
"""

import argparse
import os
import sys
from typing import Any, Dict, List

from src.analyzer import PropertyAnalyzer, load_config
from src.notifier import EmailNotifier
from src.scrapers.imap_alerts import ImapAlertsReader
from src.scrapers.local_agencies_scraper import LocalAgenciesAndBanksScraper, get_initial_market_baseline
from src.scrapers.portals_scraper import PortalsScraper
from src.storage import StorageManager


def load_dotenv_file(base_dir: str) -> None:
    """Carga variables de un archivo .env local si existe (sin requerir python-dotenv)."""
    env_path = os.path.join(base_dir, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if "tu_correo@" in v or "xxxx" in v or "tu-usuario" in v:
                continue
            if k and k not in os.environ:
                os.environ[k] = v


def seed_historical_baseline(storage: StorageManager, analyzer: PropertyAnalyzer) -> None:
    """
    Si la base de datos está vacía, inicializa con el histórico de referencia de las zonas
    objetivo (incluyendo su evolución histórica de precios) para tener comparativa desde el día 1.
    """
    existing = storage.get_all_listings()
    if existing:
        return

    print("[Init] Inicializando base de datos con referencias y series históricas de la Vega Baja...")
    baseline_items = get_initial_market_baseline()

    for raw in baseline_items:
        prev_prices = raw.get("prev_prices", [])
        current_price = raw["price_eur"]

        # Si tiene histórico previo, insertar primero los precios pasados cronológicamente
        if prev_prices:
            for dt_str, old_p in prev_prices:
                snap = dict(raw)
                snap["price_eur"] = old_p
                analyzed_old = analyzer.analyze_raw_item(snap)
                storage.upsert_listings([analyzed_old], now_iso=f"{dt_str}T08:00:00Z")

        # Insertar el estado actual y recalcular score considerando la bajada acumulada
        first_price = prev_prices[0][1] if prev_prices else current_price
        drop_pct = round(((first_price - current_price) / first_price) * 100.0, 1) if first_price > current_price else 0.0
        raw_cur = dict(raw)
        raw_cur["price_drop_pct"] = drop_pct
        analyzed_cur = analyzer.analyze_raw_item(raw_cur)
        storage.upsert_listings([analyzed_cur])


def run_agent(skip_network: bool = False) -> Dict[str, Any]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv_file(base_dir)
    config = load_config(os.path.join(base_dir, "config.json"))
    analyzer = PropertyAnalyzer(config)
    storage = StorageManager()

    # 1. Asegurar histórico inicial si la BD está recién creada
    seed_historical_baseline(storage, analyzer)

    raw_collected: List[Dict[str, Any]] = []
    sources_summary: Dict[str, int] = {}

    if not skip_network:
        # 2. Leer alertas de correo IMAP (Idealista, Fotocasa, Milanuncios, Pisos.com...)
        imap_reader = ImapAlertsReader()
        if imap_reader.is_configured():
            print("[1/3] Leyendo alertas de correo IMAP (Idealista / Fotocasa / Milanuncios)...")
            imap_items = imap_reader.fetch_alerts()
            sources_summary["imap_alerts"] = len(imap_items)
            raw_collected.extend(imap_items)
        else:
            print("[1/3] IMAP no configurado en variables de entorno (saltando lectura de buzón).")
            sources_summary["imap_alerts"] = 0

        # 3. Escanear portales nacionales e índices web
        print("[2/3] Escaneando portales inmobiliarios y buscadores indexados...")
        portals = PortalsScraper()
        portal_items = portals.run_all()
        sources_summary["portals"] = len(portal_items)
        raw_collected.extend(portal_items)

        # 4. Escanear inmobiliarias locales de la Vega Baja y bancos
        print("[3/3] Escaneando inmobiliarias locales de la Vega Baja y activos bancarios...")
        local_scraper = LocalAgenciesAndBanksScraper(config.get("local_agencies_urls", []))
        local_items = local_scraper.run_all()
        sources_summary["local_and_banks"] = len(local_items)
        raw_collected.extend(local_items)

    # 5. Analizar, clasificar y filtrar cada anuncio
    analyzed_list: List[Dict[str, Any]] = []
    for raw in raw_collected:
        analyzed = analyzer.analyze_raw_item(raw)
        analyzed_list.append(analyzed)

    diff = storage.upsert_listings(analyzed_list)
    storage.log_run(
        total_scraped=len(raw_collected),
        new_count=len(diff["new_items"]),
        drops_count=len(diff["price_drops"]),
        inc_count=len(diff["price_increases"]),
        sources=sources_summary,
    )

    # 6. Exportar JSON y JS para el Panel Web
    payload = storage.export_web_data()
    stats = payload["stats"]
    listings = payload["listings"]

    # 7. Generar vista previa del email diario y enviarlo si procede
    notifier = EmailNotifier(config)
    preview_email_path = os.path.join(base_dir, "docs", "last_email_preview.html")
    notifier.send_daily_report(stats, listings, diff, preview_path=preview_email_path)

    print(
        f"[OK] Base de datos actualizada: {stats['total_listings']} inmuebles totales | "
        f"{stats['highlighted_listings']} destacados (>=180 m²) | "
        f"{stats['chollos_count']} chollos | {stats['price_drops_count']} con bajada de precio."
    )
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Monitor de Solares y Casas a Reformar - Vega Baja")
    parser.add_argument("--offline", action="store_true", help="Ejecuta solo con datos en caché/locales sin llamadas de red")
    args = parser.parse_args()
    run_agent(skip_network=args.offline)
