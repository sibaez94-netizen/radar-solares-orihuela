# -*- coding: utf-8 -*-
"""
Lector automático de alertas por correo (IMAP) para Idealista, Fotocasa, Milanuncios,
Pisos.com, Habitaclia y Yaencontre.
Permite saltarse al 100% los bloqueos anti-bot (DataDome / Cloudflare) desde GitHub Actions
leyendo los correos de alertas gratuitas guardadas por el usuario.
"""

import email
import html
import imaplib
import os
import re
from email.header import decode_header
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse


class ImapAlertsReader:
    PORTAL_SENDERS = {
        "Idealista": ["idealista.com"],
        "Fotocasa": ["fotocasa.es", "alerts.fotocasa.es"],
        "Milanuncios": ["milanuncios.com"],
        "Pisos.com": ["pisos.com"],
        "Habitaclia": ["habitaclia.com"],
        "Yaencontre": ["yaencontre.com"],
    }

    def __init__(
        self,
        host: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        lookback_days: int = 7,
    ):
        self.host = (host or os.environ.get("IMAP_HOST") or "").strip() or "imap.gmail.com"
        self.user = (user or os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER") or "").strip()
        self.password = (password or os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or "").strip()
        self.lookback_days = lookback_days

    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def fetch_alerts(self) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []

        items: List[Dict[str, Any]] = []
        try:
            mail = imaplib.IMAP4_SSL(self.host)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            # Buscar correos de los últimos N días
            import datetime

            since_date = (datetime.date.today() - datetime.timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            status, data = mail.search(None, f'(SINCE "{since_date}")')
            if status != "OK" or not data or not data[0]:
                mail.logout()
                return []

            msg_ids = data[0].split()[-80:]  # Procesar hasta los 80 correos más recientes
            for mid in reversed(msg_ids):
                res, msg_data = mail.fetch(mid, "(RFC822)")
                if res != "OK" or not msg_data:
                    continue
                for part in msg_data:
                    if isinstance(part, tuple):
                        msg = email.message_from_bytes(part[1])
                        portal = self._detect_portal(msg)
                        if not portal:
                            continue
                        subject = self._decode_str(msg.get("Subject", ""))
                        body_html = self._extract_html(msg)
                        if body_html:
                            extracted = self.parse_alert_html(body_html, portal=portal, subject=subject)
                            items.extend(extracted)

            mail.logout()
        except Exception as e:
            print(f"[IMAP] Aviso al leer buzón de alertas: {e}")

        return items

    def _detect_portal(self, msg: email.message.Message) -> Optional[str]:
        from_hdr = self._decode_str(msg.get("From", "")).lower()
        subj_hdr = self._decode_str(msg.get("Subject", "")).lower()
        for portal, domains in self.PORTAL_SENDERS.items():
            if any(d in from_hdr or d in subj_hdr for d in domains):
                return portal
        return None

    @staticmethod
    def _decode_str(val: str) -> str:
        if not val:
            return ""
        parts = decode_header(val)
        out = []
        for content, enc in parts:
            if isinstance(content, bytes):
                out.append(content.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(content))
        return "".join(out)

    @staticmethod
    def _extract_html(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        return ""

    def parse_alert_html(self, raw_html: str, portal: str = "Idealista", subject: str = "") -> List[Dict[str, Any]]:
        """
        Extrae anuncios individuales de un correo HTML de Idealista, Fotocasa, Milanuncios, Pisos.com, etc.
        """
        results: List[Dict[str, Any]] = []
        clean_html = html.unescape(raw_html)

        # Extraer todos los enlaces y su contexto alrededor (600 caracteres antes/después)
        link_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        seen_urls = set()

        for match in link_pattern.finditer(clean_html):
            href = match.group(1).strip()
            anchor_text = re.sub(r"<[^>]+>", " ", match.group(2)).strip()
            real_url = self._unwrap_tracking_url(href)

            if not self._is_property_url(real_url):
                continue

            base_url = real_url.split("?")[0].rstrip("/")
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)

            # Ventana de contexto alrededor del enlace para capturar precio, m2 y descripción
            start_ctx = max(0, match.start() - 350)
            end_ctx = min(len(clean_html), match.end() + 900)
            snippet_html = clean_html[start_ctx:end_ctx]
            snippet_txt = re.sub(r"<[^>]+>", " ", snippet_html)
            snippet_txt = re.sub(r"\s+", " ", snippet_txt).strip()

            # Extraer precio (€)
            price_match = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,7})\s*€", snippet_txt)
            price_eur = float(price_match.group(1).replace(".", "")) if price_match else None

            # Extraer m²
            m2_match = re.search(r"(\d{1,3}(?:\.\d{3})*|\d{2,6})\s*m[²2]", snippet_txt, re.IGNORECASE)
            surface_m2 = float(m2_match.group(1).replace(".", "")) if m2_match else None

            title = anchor_text if len(anchor_text) > 10 else subject or f"Inmueble en {portal}"
            results.append(
                {
                    "portal": f"{portal} (Alerta Email)",
                    "title": title[:160],
                    "url": base_url,
                    "price_eur": price_eur,
                    "surface_plot_m2": surface_m2,
                    "description": snippet_txt[:500],
                    "location": title,
                }
            )

        return results

    @staticmethod
    def _unwrap_tracking_url(url: str) -> str:
        """Limpia redirecciones de tracking en correos si contienen el destino en query params."""
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            for key in ("url", "u", "dest", "target", "redirect"):
                if key in qs and qs[key]:
                    cand = unquote(qs[key][0])
                    if cand.startswith("http"):
                        return cand
        except Exception:
            pass
        return url

    @staticmethod
    def _is_property_url(url: str) -> bool:
        u = url.lower()
        patterns = [
            r"idealista\.com/(?:inmueble|pro)/?\d+",
            r"fotocasa\.es/.*/comprar/(?:terreno|vivienda|casa|edificio)/",
            r"milanuncios\.com/(?:venta-de-)?(?:solares|terrenos|casas|chalets)[^\"']*-\d+\.htm",
            r"pisos\.com/comprar/(?:terreno|solar|casa|chalet)-",
            r"habitaclia\.com/comprar-",
            r"yaencontre\.com/venta/(?:terrenos|casas)/inmueble-",
        ]
        return any(re.search(p, u) for p in patterns)
