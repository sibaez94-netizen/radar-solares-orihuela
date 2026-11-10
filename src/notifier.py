# -*- coding: utf-8 -*-
"""
Generador y enviador del Informe Diario por Email (Gmail SMTP / Resend API).
Incluye resumen ejecutivo, Top Chollos (>= 180 m²), Bajadas de Precio detectadas,
Nuevas incorporaciones y comparativa de €/m² por pedanía/municipio.
"""

import datetime
import json
import os
import smtplib
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional


class EmailNotifier:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.smtp_host = (os.environ.get("SMTP_HOST") or "").strip() or "smtp.gmail.com"
        raw_port = (os.environ.get("SMTP_PORT") or "").strip() or "465"
        self.smtp_port = int(raw_port) if raw_port.isdigit() else 465
        self.smtp_user = (os.environ.get("SMTP_USER") or os.environ.get("IMAP_USER") or "").strip()
        self.smtp_password = (os.environ.get("SMTP_PASSWORD") or os.environ.get("IMAP_PASSWORD") or "").strip()
        self.resend_api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
        self.to_email = (os.environ.get("NOTIFY_EMAIL") or "").strip() or self.smtp_user
        self.dashboard_url = (os.environ.get("DASHBOARD_URL") or "").strip()

    def build_daily_html(
        self,
        stats: Dict[str, Any],
        all_listings: List[Dict[str, Any]],
        run_diff: Dict[str, Any],
        auctions: Optional[List[Dict[str, Any]]] = None,
        auction_diff: Optional[Dict[str, Any]] = None,
    ) -> str:
        auctions_html = self.render_auctions_html(auctions or [], auction_diff or {})
        today_str = datetime.date.today().strftime("%d/%m/%Y")
        highlighted = [x for x in all_listings if x.get("is_highlighted")]
        chollos = sorted(
            [x for x in highlighted if (x.get("chollo_score") or 0) >= 72],
            key=lambda x: x.get("chollo_score", 0),
            reverse=True,
        )[:6]
        drops = sorted(
            [x for x in all_listings if (x.get("price_drop_pct") or 0) > 0],
            key=lambda x: x.get("price_drop_pct", 0),
            reverse=True,
        )[:6]
        new_items = [x for x in run_diff.get("new_items", []) if x.get("is_highlighted")][:6]

        def fmt_eur(v: Optional[float]) -> str:
            if not v:
                return "Consultar"
            return f"{int(round(v)):,}".replace(",", ".") + " €"

        def render_rows(items: List[Dict[str, Any]], show_drop: bool = False) -> str:
            if not items:
                return '<p style="color:#64748b;font-size:14px;">Sin novedades en este bloque hoy.</p>'
            html_rows = []
            for it in items:
                score = it.get("chollo_score", 50)
                badge_bg = "#16a34a" if score >= 80 else "#d97706" if score >= 70 else "#475569"
                drop_badge = ""
                if show_drop and (it.get("price_drop_pct") or 0) > 0:
                    drop_badge = (
                        f'<span style="background:#dcfce7;color:#15803d;padding:2px 8px;'
                        f'border-radius:99px;font-size:12px;font-weight:700;margin-left:6px;">'
                        f'▼ -{it["price_drop_pct"]:.1f}% (-{fmt_eur(it.get("price_drop_eur"))})</span>'
                    )
                reasons_str = " · ".join(it.get("chollo_reasons", [])[:2])
                eur_m2_str = f'{it["eur_per_m2"]:.0f} €/m²' if it.get("eur_per_m2") else "—"
                html_rows.append(
                    f"""
                    <div style="border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:10px;background:#ffffff;">
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <span style="font-size:12px;font-weight:700;text-transform:uppercase;color:#0f766e;">
                          {it.get("zone_name")} · {it.get("asset_label")}
                        </span>
                        <span style="background:{badge_bg};color:#fff;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:700;">
                          Score {score}/100
                        </span>
                      </div>
                      <a href="{it.get("url")}" style="color:#0f172a;font-size:16px;font-weight:700;text-decoration:none;">
                        {it.get("title")}
                      </a>
                      <div style="margin-top:8px;font-size:14px;color:#334155;">
                        <strong style="font-size:17px;color:#0f172a;">{fmt_eur(it.get("price_eur"))}</strong>
                        {drop_badge}
                        &nbsp;|&nbsp; <strong>{it.get("effective_plot_m2", 0):.0f} m²</strong> parcela
                        &nbsp;|&nbsp; <strong>{eur_m2_str}</strong>
                        &nbsp;|&nbsp; <span style="color:#64748b;">{it.get("portal")}</span>
                      </div>
                      {f'<div style="margin-top:6px;font-size:12px;color:#475569;">💡 {reasons_str}</div>' if reasons_str else ''}
                    </div>
                    """
                )
            return "\n".join(html_rows)

        # Tabla resumen por zona
        zone_rows = []
        for zid, z in stats.get("zones", {}).items():
            s_med = f'{z["median_solar_eur_m2"]:.0f} €/m²' if z.get("median_solar_eur_m2") else "—"
            c_med = f'{z["median_casa_eur_m2"]:.0f} €/m²' if z.get("median_casa_eur_m2") else "—"
            min_m2 = f'{z["min_eur_m2"]:.0f} €/m²' if z.get("min_eur_m2") else "—"
            zone_rows.append(
                f"""
                <tr>
                  <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-weight:600;">{z.get("zone_name")}</td>
                  <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:center;">{z.get("highlighted_count", 0)}</td>
                  <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;">{s_med}</td>
                  <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;">{c_med}</td>
                  <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;color:#15803d;font-weight:700;">{min_m2}</td>
                </tr>
                """
            )

        dash_btn = (
            f'<div style="text-align:center;margin:22px 0;">'
            f'<a href="{self.dashboard_url}" style="background:#0f766e;color:#ffffff;padding:12px 24px;'
            f'border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;">'
            f'Abrir Panel Web Interactivo</a></div>'
            if self.dashboard_url
            else ""
        )

        return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Resumen Diario Solares Orihuela y Vega Baja</title></head>
<body style="margin:0;padding:20px;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#0f172a;">
  <div style="max-width:680px;margin:0 auto;background:#f8fafc;border-radius:14px;overflow:hidden;border:1px solid #cbd5e1;">
    <div style="background:linear-gradient(135deg,#134e4a,#0f766e);color:#ffffff;padding:22px 24px;">
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;opacity:0.85;">Radar Inmobiliario · Vega Baja</div>
      <h1 style="margin:6px 0 4px;font-size:22px;">Solares y Casas a Reformar · {today_str}</h1>
      <div style="font-size:13px;opacity:0.9;">Orihuela · Montepinar · Raiguero de Bonanza · Raiguero de Levante · Benferri · Granja de Rocamora</div>
    </div>

    <div style="padding:20px 24px;">
      <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:18px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;text-align:center;">
        <tr>
          <td style="padding:12px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Objetivo ≥ 180 m²</div>
            <div style="font-size:22px;font-weight:800;color:#0f766e;">{stats.get("highlighted_listings", 0)}</div>
          </td>
          <td style="padding:12px;border-left:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Chollos Detectados</div>
            <div style="font-size:22px;font-weight:800;color:#16a34a;">{stats.get("chollos_count", 0)}</div>
          </td>
          <td style="padding:12px;border-left:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Bajadas de Precio</div>
            <div style="font-size:22px;font-weight:800;color:#d97706;">{stats.get("price_drops_count", 0)}</div>
          </td>
          <td style="padding:12px;border-left:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Mediana Solar</div>
            <div style="font-size:20px;font-weight:800;color:#0f172a;">{stats.get("median_solar_eur_m2", 0):.0f} €/m²</div>
          </td>
        </tr>
      </table>

      {dash_btn}

      <h2 style="font-size:17px;border-bottom:2px solid #0f766e;padding-bottom:6px;margin-top:22px;">🔥 Top Chollos y Oportunidades (Parcela ≥ 180 m²)</h2>
      {render_rows(chollos, show_drop=True)}

      {auctions_html}

      <h2 style="font-size:17px;border-bottom:2px solid #d97706;padding-bottom:6px;margin-top:24px;">📉 Bajadas de Precio Registradas</h2>
      {render_rows(drops, show_drop=True)}

      <h2 style="font-size:17px;border-bottom:2px solid #2563eb;padding-bottom:6px;margin-top:24px;">🆕 Últimas Incorporaciones Destacadas</h2>
      {render_rows(new_items, show_drop=False)}

      <h2 style="font-size:17px;border-bottom:2px solid #475569;padding-bottom:6px;margin-top:24px;">📊 Evolución €/m² por Zona</h2>
      <table width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;overflow:hidden;">
        <thead>
          <tr style="background:#f1f5f9;color:#475569;text-align:left;">
            <th style="padding:8px 10px;">Zona / Pedanía</th>
            <th style="padding:8px 10px;text-align:center;">Activos ≥180m²</th>
            <th style="padding:8px 10px;text-align:right;">Mediana Solar</th>
            <th style="padding:8px 10px;text-align:right;">Mediana Casa</th>
            <th style="padding:8px 10px;text-align:right;">Mínimo €/m²</th>
          </tr>
        </thead>
        <tbody>
          {"".join(zone_rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>"""

    @staticmethod
    def render_auctions_html(auctions: List[Dict[str, Any]], auction_diff: Dict[str, Any]) -> str:
        import html as _h

        def eur(v: Optional[float]) -> str:
            return "—" if not v else f"{int(round(v)):,}".replace(",", ".") + " €"

        def fecha(iso: Optional[str]) -> str:
            if not iso:
                return "—"
            try:
                d = datetime.datetime.fromisoformat(iso)
                dias = (d.date() - datetime.date.today()).days
                extra = " (hoy)" if dias == 0 else (f" (en {dias} días)" if dias > 0 else "")
                return d.strftime("%d/%m/%Y %H:%M") + extra
            except Exception:
                return iso

        errors = "".join(
            f'<p style="background:#fffbeb;border:1px solid #fcd34d;color:#92400e;padding:8px 12px;border-radius:8px;font-size:13px;">⚠️ {_h.escape(e)}</p>'
            for e in (auction_diff.get("errors") or [])
        )
        targets = [a for a in auctions if a.get("is_target_type")]
        others = [a for a in auctions if not a.get("is_target_type")]
        new_ids = {a.get("id") for a in (auction_diff.get("new_auctions") or [])}
        rows = []
        for a in targets[:10]:
            m2 = a.get("superficie_efectiva_m2")
            desc_pct = a.get("descuento_vs_mercado_pct")
            riesgos = "".join(f"<li>{_h.escape(r)}</li>" for r in (a.get("riesgos") or []))
            pros = " · ".join(_h.escape(r) for r in (a.get("score_reasons") or []))
            badge_new = '<span style="background:#dcfce7;color:#166534;padding:2px 7px;border-radius:999px;font-size:11px;font-weight:700;margin-left:6px;">NUEVA</span>' if a.get("id") in new_ids else ""
            rows.append(f'''
            <div style="border:1px solid #cbd5e1;border-radius:10px;padding:12px 14px;margin-bottom:10px;background:#ffffff;">
              <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;">{_h.escape(a.get("asset_label",""))} · {_h.escape(a.get("localidad",""))} · {_h.escape(a.get("tipo_subasta",""))}{badge_new}</div>
              <div style="font-size:15px;font-weight:800;margin-top:3px;"><a href="{_h.escape(a.get("url","#"))}" style="color:#0f766e;text-decoration:none;">{_h.escape(a.get("id_subasta",""))}{(" · Lote " + str(a["lote"])) if a.get("lote") else ""} · {_h.escape(a.get("direccion",""))}</a></div>
              <div style="font-size:13px;margin-top:6px;color:#0f172a;">
                <b>Valor subasta:</b> {eur(a.get("valor_subasta_eur"))} · <b>Tasación:</b> {eur(a.get("tasacion_eur"))} · <b>Puja mínima:</b> {_h.escape(a.get("puja_minima_texto") or "—")} · <b>Depósito:</b> {eur(a.get("deposito_eur"))}<br>
                <b>Superficie:</b> {f"{m2:.0f} m²" if m2 else "no consta"} · <b>Frente al €/m² de la zona:</b> {("—" if desc_pct is None else (f"{desc_pct:.0f}% por debajo" if desc_pct >= 0 else f"{-desc_pct:.0f}% por encima"))} · <b>Cierra:</b> {fecha(a.get("fecha_fin"))} · <b>Pujas:</b> {_h.escape((a.get("pujas") or {}).get("texto",""))}
              </div>
              {f'<div style="font-size:12.5px;color:#166534;margin-top:5px;">✅ {pros}</div>' if pros else ""}
              {"".join(f'<a href="{_h.escape(doc["url"])}" style="font-size:12px;color:#7c3aed;margin-right:10px;">📄 {_h.escape(doc["titulo"])}</a>' for doc in (a.get("documentos") or []))}
              {f'<ul style="font-size:12.5px;color:#991b1b;margin:6px 0 0 18px;padding:0;">{riesgos}</ul>' if riesgos else ""}
            </div>''')
        body = "".join(rows) or '<p style="color:#64748b;font-size:14px;">Hoy no hay subastas de solares o casas en tus zonas.</p>'
        otros_txt = (
            f'<p style="font-size:12.5px;color:#64748b;">Además hay {len(others)} subasta(s) de pisos, locales o fincas rústicas en tus zonas (en el panel, pestaña Subastas BOE).</p>'
            if others else ""
        )
        return f'''
      <h2 style="font-size:17px;border-bottom:2px solid #7c3aed;padding-bottom:6px;margin-top:24px;">⚖️ Subastas públicas del BOE en tus zonas</h2>
      {errors}
      <p style="font-size:12.5px;color:#475569;margin:0 0 10px;">El "descuento" compara el valor de subasta con el €/m² de referencia de la zona; es orientativo. Antes de pujar: nota simple y certificación de cargas del Registro, catastro y visita exterior. Para pujar hay que consignar el depósito (normalmente el 5%).</p>
      {body}
      {otros_txt}'''

    def send_daily_report(
        self,
        stats: Dict[str, Any],
        all_listings: List[Dict[str, Any]],
        run_diff: Dict[str, Any],
        preview_path: Optional[str] = None,
        auctions: Optional[List[Dict[str, Any]]] = None,
        auction_diff: Optional[Dict[str, Any]] = None,
    ) -> bool:
        html_body = self.build_daily_html(stats, all_listings, run_diff, auctions=auctions, auction_diff=auction_diff)

        # Guardar siempre una vista previa HTML para poder verla desde el navegador
        if preview_path:
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(html_body)

        today_str = datetime.date.today().strftime("%d/%m/%Y")
        chollos_n = stats.get("chollos_count", 0)
        drops_n = stats.get("price_drops_count", 0)
        n_new_auctions = len([a for a in ((auction_diff or {}).get("new_auctions") or []) if a.get("is_target_type")])
        subject = f"[Radar Solares Orihuela] {today_str} · {chollos_n} chollos y {drops_n} bajadas de precio"
        if n_new_auctions:
            subject += f" · {n_new_auctions} subasta(s) BOE nueva(s)"

        # 1. Envío por Resend API si está configurada
        if self.resend_api_key and self.to_email:
            try:
                payload = json.dumps(
                    {
                        "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
                        "to": [e.strip() for e in self.to_email.split(",") if e.strip()],
                        "subject": subject,
                        "html": html_body,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.resend.com/emails",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    if 200 <= r.status < 300:
                        print(f"[Email] Informe diario enviado por Resend a {self.to_email}")
                        return True
            except Exception as e:
                print(f"[Email] Error con Resend API: {e}")

        # 2. Envío por Gmail / SMTP estándar si está configurado
        if self.smtp_user and self.smtp_password and self.to_email:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = self.smtp_user
                msg["To"] = self.to_email
                msg.attach(MIMEText(html_body, "html", "utf-8"))

                if self.smtp_port == 465:
                    with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20) as server:
                        server.login(self.smtp_user, self.smtp_password)
                        server.sendmail(
                            self.smtp_user,
                            [e.strip() for e in self.to_email.split(",") if e.strip()],
                            msg.as_string(),
                        )
                else:
                    with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as server:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                        server.sendmail(
                            self.smtp_user,
                            [e.strip() for e in self.to_email.split(",") if e.strip()],
                            msg.as_string(),
                        )
                print(f"[Email] Informe diario enviado por SMTP a {self.to_email}")
                return True
            except Exception as e:
                print(f"[Email] Error enviando correo SMTP: {e}")

        return False
