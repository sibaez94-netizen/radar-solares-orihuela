# -*- coding: utf-8 -*-
"""
Genera la documentación ejecutiva y técnica del Agente de Solares en dos formatos:
1. Presentacion_Agente_Solares_Vega_Baja.pptx (PowerPoint nativo de 7 diapositivas en fondo blanco)
2. Guia_Agente_Solares_Vega_Baja.pdf (Documento PDF multipágina en fondo blanco)
3. docs/guia_funcionamiento.html (Versión web imprimible en fondo blanco)
"""

import os
import subprocess
import zipfile
from xml.sax.saxutils import escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================================
# 1. GENERADOR DE POWERPOINT NATIVO (.PPTX) SIN DEPENDENCIAS EXTERNAS
# ============================================================================
SLIDES_DATA = [
    {
        "title": "Radar Autónomo de Solares y Casas a Reformar",
        "subtitle": "Orihuela · Montepinar · Raiguero de Bonanza · Raiguero de Levante · Benferri · Granja de Rocamora",
        "bullets": [
            "Objetivo: Detectar solares urbanos/urbanizables y casas de planta baja para reformar o derribar.",
            "Regla de Superficie: Guarda todos los inmuebles en histórico, pero destaca en principal solo los >= 180 m² de parcela.",
            "Limpieza Automática: Excluye Orihuela Costa (playa), pisos en altura y fincas rústicas no edificables.",
            "Coste Operativo: 0 € / mes corriendo en la nube gratuita (GitHub Actions + GitHub Pages).",
        ],
    },
    {
        "title": "1. ¿De dónde saca la información el Agente?",
        "subtitle": "Arquitectura de Triple Captación (Sin pagar APIs ni Proxies)",
        "bullets": [
            "Estado Inicial (Semilla): Al instalarlo por primera vez sin internet/claves, muestra 14 inmuebles de muestra para ver el panel funcionando.",
            "Canal 1 - Scraping Directo (Sin claves): Pisos.com, Habitaclia, Yaencontre, Trovimap, Bancos (Solvia, Aliseda, Haya) e inmobiliarias locales.",
            "Canal 2 - Buscador Indexado (Sin claves): Rastrea enlaces públicos indexados de Idealista, Fotocasa y Milanuncios en cada pedanía.",
            "Canal 3 - Lector de Alertas de Correo IMAP (Anti-bloqueo 100%): Lee los emails gratuitos de alertas que te envían Idealista y Fotocasa.",
        ],
    },
    {
        "title": "2. ¿Por qué leer las alertas de correo de Idealista y Fotocasa?",
        "subtitle": "El truco profesional para saltarse el bloqueo anti-robots (DataDome)",
        "bullets": [
            "El Problema: Idealista y Fotocasa bloquean con captcha cualquier servidor en la nube que intente entrar directamente a su web.",
            "La Solución Gratuita: Te suscribes gratis en la web de Idealista/Fotocasa a tu búsqueda (dibujando el mapa de Orihuela/Pedanías/Benferri).",
            "Sin API de Google Cloud: No necesitas crear proyectos complejos en Google Cloud; basta con una 'Contraseña de Aplicación' de Gmail (16 letras).",
            "Proceso Automático: Cada mañana el agente abre tu buzón por IMAP, extrae los anuncios nuevos o rebajados de los correos y los mete al radar.",
        ],
    },
    {
        "title": "3. Cómo distingue las Pedanías y calcula los m² reales",
        "subtitle": "Motor de lenguaje natural adaptado a la Vega Baja (src/analyzer.py)",
        "bullets": [
            "Detección de Pedanías en el texto: Muchos anuncios ponen solo 'Orihuela', pero en la descripción dicen 'junto al Raiguero' o 'Montepinar'.",
            "Corrección de erratas locales: Detecta 'Riguero de Bonanza', 'Raiguero de Bonanza', 'Rincón de Bonanza', 'Raiguero de Levante', 'Benfis Park'.",
            "Conversión de Tahúllas: Si un anuncio local dice 'media tahúlla' o '2 tahúllas', el agente calcula automáticamente 1 tahúlla = 1.118 m².",
            "Separación Solar vs Construido: En casas de pueblo distingue entre m² construidos de vivienda vieja y m² reales de parcela/patio.",
        ],
    },
    {
        "title": "4. Cómo funciona el 'Chollo Score' (0 a 100 puntos)",
        "subtitle": "Valoración objetiva en €/m² frente a su pedanía exacta",
        "bullets": [
            "Cálculo de €/m² de suelo: Divide el precio entre los m² de parcela y lo compara con la mediana de esa pedanía (ej. ~210 €/m² en Raiguero).",
            "Descuento sobre la zona: Si un solar sale a 145 €/m² donde la media es 210 €/m² (-31%), su puntuación sube por encima de 80/100.",
            "Bajada histórica de precio: Cada vez que un propietario rebaja el anuncio (ej. de 54.000 € a 46.000 €), queda grabado con fecha y sube puntos.",
            "Palabras clave de valor: Suma puntos si detecta 'esquina', 'dos calles', 'bajo + 2 alturas', 'urge vender', 'herencia' o 'activo bancario'.",
        ],
    },
    {
        "title": "5. El Panel Web (Fondo Blanco) y la Base de Datos Histórica",
        "subtitle": "Todo guardado en SQLite (data/solares.db) y visible desde móvil o PC",
        "bullets": [
            "Pestaña Principal (>= 180 m²): Muestra únicamente los solares y casas de planta baja que cumplen tu mínimo de 180 m².",
            "Pestaña Todos (< 180 m²): Conserva los solares más pequeños en secundario por si alguno te encaja por ubicación o precio.",
            "Pestaña Bajadas de Precio: Filtra los inmuebles cuyos dueños están rebajando el precio, con gráfica de la curva histórica.",
            "Calculadora de Viabilidad + Carteles Manuales: Calcula el coste llave en mano (Compra + ITP 10% + Obra/Reforma) y permite anotar carteles de calle.",
        ],
    },
    {
        "title": "6. Pasos para activarlo en la Nube Gratis (5 minutos)",
        "subtitle": "GitHub Actions + GitHub Pages + Correo Diario Automático",
        "bullets": [
            "Paso 1: Sube esta carpeta a un repositorio gratuito de GitHub y activa GitHub Pages apuntando a la carpeta /docs.",
            "Paso 2: Entra en https://myaccount.google.com/apppasswords y genera una contraseña de aplicación de 16 letras llamada 'Agente Solares'.",
            "Paso 3: En GitHub (Settings -> Secrets -> Actions), guarda IMAP_USER, IMAP_PASSWORD, SMTP_USER, SMTP_PASSWORD y NOTIFY_EMAIL.",
            "Listo: Todos los días a las 08:30 AM el agente escaneará los portales y tu correo, actualizará la web y te enviará el resumen diario por email.",
        ],
    },
]


def build_pptx(output_path: str) -> None:
    """Construye un archivo PowerPoint (.pptx) OpenXML estándar 16:9 con fondo blanco limpio."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml
        slide_overrides = "\n".join(
            f'  <Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, len(SLIDES_DATA) + 1)
        )
        zf.writestr(
            "[Content_Types].xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{slide_overrides}
</Types>""",
        )

        # _rels/.rels
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""",
        )

        # ppt/_rels/presentation.xml.rels
        slide_rels = "\n".join(
            f'  <Relationship Id="rIdSlide{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
            for i in range(1, len(SLIDES_DATA) + 1)
        )
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdMaster1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rIdTheme1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
{slide_rels}
</Relationships>""",
        )

        # ppt/presentation.xml (16:9 widescreen: cx=12192000, cy=6858000)
        sld_ids = "\n".join(
            f'    <p:sldId id="{255 + i}" r:id="rIdSlide{i}"/>' for i in range(1, len(SLIDES_DATA) + 1)
        )
        zf.writestr(
            "ppt/presentation.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rIdMaster1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
{sld_ids}
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>""",
        )

        # Minimal slideMaster, slideLayout & theme
        zf.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLayout1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rIdTheme1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "ppt/slideMasters/slideMaster1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rIdLayout1"/></p:sldLayoutIdLst>
</p:sldMaster>""",
        )
        zf.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdMaster1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>
</p:sldLayout>""",
        )
        zf.writestr(
            "ppt/theme/theme1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="CleanWhite">
  <a:themeElements>
    <a:clrScheme name="CleanWhite">
      <a:dk1><a:srgbClr val="0F172A"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="334155"/></a:dk2>
      <a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
      <a:accent1><a:srgbClr val="059669"/></a:accent1>
      <a:accent2><a:srgbClr val="0284C7"/></a:accent2>
      <a:accent3><a:srgbClr val="D97706"/></a:accent3>
      <a:accent4><a:srgbClr val="7E22CE"/></a:accent4>
      <a:accent5><a:srgbClr val="DC2626"/></a:accent5>
      <a:accent6><a:srgbClr val="475569"/></a:accent6>
      <a:hlink><a:srgbClr val="0284C7"/></a:hlink>
      <a:folHlink><a:srgbClr val="7E22CE"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="CleanFonts">
      <a:majorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
      <a:minorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="CleanFmt">
      <a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
      <a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
      <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
      <a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>""",
        )

        # Generar cada diapositiva
        for idx, s in enumerate(SLIDES_DATA, start=1):
            zf.writestr(
                f"ppt/slides/_rels/slide{idx}.xml.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLayout1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>""",
            )

            bullet_paras = []
            for b in s["bullets"]:
                bullet_paras.append(
                    f"""<a:p>
              <a:pPr marL="342900" indent="-228600" spcBef="18000"><a:buChar char="•"/></a:pPr>
              <a:r><a:rPr lang="es-ES" sz="2000" dirty="0"><a:solidFill><a:srgbClr val="1E293B"/></a:solidFill><a:latin typeface="Segoe UI"/></a:rPr><a:t>{escape(b)}</a:t></a:r>
            </a:p>"""
                )

            zf.writestr(
                f"ppt/slides/slide{idx}.xml",
                f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg>
      <p:bgPr>
        <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
        <a:effectLst/>
      </p:bgPr>
    </p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <!-- Barra superior verde esmeralda -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="TopBar"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="0" y="0"/><a:ext cx="12192000" cy="140000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:solidFill><a:srgbClr val="059669"/></a:solidFill>
        </p:spPr>
      </p:sp>
      <!-- Caja de Título y Subtítulo -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="TitleBox"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="420000"/><a:ext cx="10820400" cy="1450000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square"/>
          <a:lstStyle/>
          <a:p>
            <a:r><a:rPr lang="es-ES" sz="3000" b="1"><a:solidFill><a:srgbClr val="0F172A"/></a:solidFill><a:latin typeface="Segoe UI"/></a:rPr><a:t>{escape(s["title"])}</a:t></a:r>
          </a:p>
          <a:p>
            <a:pPr spcBef="8000"/>
            <a:r><a:rPr lang="es-ES" sz="1800" b="1"><a:solidFill><a:srgbClr val="059669"/></a:solidFill><a:latin typeface="Segoe UI"/></a:rPr><a:t>{escape(s["subtitle"])}</a:t></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <!-- Caja de Puntos Clave -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="4" name="ContentBox"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="2050000"/><a:ext cx="10820400" cy="4200000"/></a:xfrm>
          <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
          <a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill>
          <a:ln w="12700"><a:solidFill><a:srgbClr val="CBD5E1"/></a:solidFill></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="300000" tIns="250000" rIns="300000" bIns="250000"/>
          <a:lstStyle/>
          {"".join(bullet_paras)}
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>""",
            )


# ============================================================================
# 2. GENERADOR DE GUÍA VISUAL HTML (FONDO BLANCO) + CONVERSIÓN A PDF
# ============================================================================
GUIDE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Manual de Funcionamiento · Agente de Solares y Casas de Pueblo (Vega Baja)</title>
  <style>
    @page { size: A4; margin: 16mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #ffffff;
      color: #0f172a;
      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
      line-height: 1.55;
      padding: 28px;
      max-width: 920px;
      margin: 0 auto;
    }
    .header-box {
      border-bottom: 4px solid #059669;
      padding-bottom: 16px;
      margin-bottom: 24px;
    }
    .tag {
      display: inline-block;
      background: #d1fae5;
      color: #065f46;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      padding: 4px 10px;
      border-radius: 99px;
      margin-bottom: 8px;
    }
    h1 { font-size: 26px; font-weight: 800; color: #0f172a; }
    .subtitle { font-size: 14px; color: #475569; margin-top: 4px; }
    h2 {
      font-size: 18px;
      font-weight: 800;
      color: #065f46;
      margin: 24px 0 10px;
      padding-bottom: 5px;
      border-bottom: 1px solid #e2e8f0;
    }
    p, li { font-size: 13.5px; color: #1e293b; }
    ul, ol { margin-left: 20px; margin-bottom: 12px; }
    li { margin-bottom: 6px; }
    .card {
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-left: 4px solid #059669;
      border-radius: 10px;
      padding: 14px 16px;
      margin: 12px 0;
    }
    .card.warn { border-left-color: #d97706; background: #fffbeb; }
    .card.blue { border-left-color: #0284c7; background: #f0f9ff; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 13px;
    }
    th, td {
      border: 1px solid #cbd5e1;
      padding: 8px 10px;
      text-align: left;
    }
    th { background: #f1f5f9; font-weight: 700; color: #334155; }
    code {
      background: #e2e8f0;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: Consolas, monospace;
      font-size: 12.5px;
    }
  </style>
</head>
<body>
  <div class="header-box">
    <span class="tag">Documento Explicativo · Arquitectura y Puesta en Marcha</span>
    <h1>Cómo funciona tu Agente Monitor de Solares y Casas de Pueblo</h1>
    <div class="subtitle">
      Zonas objetivo: Orihuela · Montepinar · Raiguero de Bonanza · Raiguero de Levante · Benferri · Granja de Rocamora
    </div>
  </div>

  <h2>1. ¿De dónde salen los datos ahora mismo y cómo capta nuevos anuncios?</h2>
  <div class="card warn">
    <strong>¿Por qué ves ya 14 anuncios aunque todavía no has puesto tu clave de Gmail?</strong><br>
    Para que no te encuentres el panel vacío el primer día, el archivo <code>src/scrapers/local_agencies_scraper.py</code> incluye una <strong>Semilla Inicial de Referencia (14 inmuebles)</strong> con precios, m² e historial de rebajas en Raiguero de Bonanza, Raiguero de Levante, Montepinar, Benferri, Granja de Rocamora y Orihuela centro. Así puedes probar los filtros, el mapa y las gráficas inmediatamente.
  </div>

  <p>En cuanto el agente se ejecuta con conexión a Internet (cada mañana en la nube o ejecutando <code>python main.py</code> en tu PC), obtiene la información por <strong>3 canales simultáneos</strong>:</p>
  <table>
    <thead>
      <tr>
        <th>Canal de Captación</th>
        <th>Qué portales cubre</th>
        <th>¿Necesita contraseña o clave?</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>1. Scraping Directo Web</strong><br>(<code>portals_scraper.py</code> y <code>local_agencies_scraper.py</code>)</td>
        <td><strong>Pisos.com, Habitaclia, Yaencontre, Trovimap, Bancos (Solvia, Aliseda, Haya)</strong> e inmobiliarias locales de la Vega Baja (Esphouses y las que añadas en <code>config.json</code>).</td>
        <td><strong>No.</strong> Funciona solo sin ninguna clave.</td>
      </tr>
      <tr>
        <td><strong>2. Buscador Indexado</strong><br>(<code>portals_scraper.py</code>)</td>
        <td>Rastrea enlaces públicos recién indexados de <strong>Idealista, Fotocasa y Milanuncios</strong> en tus pedanías sin chocar con el bloqueo anti-bots.</td>
        <td><strong>No.</strong> Funciona solo sin ninguna clave.</td>
      </tr>
      <tr>
        <td><strong>3. Lector de Alertas de Correo (IMAP)</strong><br>(<code>imap_alerts.py</code>)</td>
        <td><strong>Idealista, Fotocasa, Milanuncios, Pisos.com, Habitaclia.</strong> Lee los correos de alerta gratuitos que te envían los portales cada vez que sale un solar o baja de precio.</td>
        <td><strong>Sí (Contraseña de Aplicación de Gmail de 16 letras).</strong> No es una API de pago; se activa gratis en 30 segundos.</td>
      </tr>
    </tbody>
  </table>

  <h2>2. Cómo funciona el filtro inteligente (≥ 180 m², Pedanías y Tahúllas)</h2>
  <ul>
    <li><strong>Guardar todos, destacar solo ≥ 180 m²:</strong> Tal como pediste, el agente guarda en la base de datos (<code>data/solares.db</code>) todos los solares y casas de pueblo que encuentra, pero en la pestaña <strong>"🎯 Destacados ≥ 180 m²"</strong> y en tu email diario solo te enseña los que tienen al menos 180 m² de suelo. Si quieres curiosear los de 120–170 m², los tienes en la pestaña <em>"🗂️ Todos"</em>.</li>
    <li><strong>Detección de pedanías y erratas locales:</strong> Muchos propietarios y agencias suben un solar en el Raiguero o Montepinar dentro del cajón general de "Orihuela". El motor lee el título y la descripción buscando variantes como <em>"Riguero de Bonanza"</em>, <em>"Raiguero de Bonanza"</em>, <em>"Rincón de Bonanza"</em>, <em>"Raiguero de Levante"</em>, <em>"Montepinar"</em>, <em>"Benferri / Benfis Park"</em> y <em>"Granja de Rocamora"</em>.</li>
    <li><strong>Exclusión automática de Orihuela Costa y pisos:</strong> Si el anuncio menciona <em>La Zenia, Cabo Roig, Villamartín, Campoamor, Playa Flamenca</em> o es un piso en altura, lo descarta automáticamente para no ensuciar tu radar.</li>
    <li><strong>Conversión automática de Tahúllas:</strong> Si una descripción en la Vega Baja dice <em>"solar de media tahúlla"</em>, el agente calcula automáticamente <code>0,5 × 1.118 m² = 559 m²</code>.</li>
  </ul>

  <h2>3. Cómo se calcula el "Chollo Score" (de 0 a 100)</h2>
  <p>Cada anuncio recibe una nota de 0 a 100 combinando cuatro factores objetivos:</p>
  <ol>
    <li><strong>Ratio €/m² de parcela frente a su pedanía:</strong> Compara el €/m² del anuncio con la mediana de esa misma zona (por ejemplo, ~210 €/m² en Raiguero de Bonanza o ~195 €/m² en Benferri). Cuanto más barato esté respecto a su zona, más sube la nota.</li>
    <li><strong>Bajada histórica de precio:</strong> Si un solar costaba 54.000 € en septiembre y hoy baja a 46.000 € (-14,8%), el agente guarda el historial de precios y le suma puntos de oportunidad.</li>
    <li><strong>Palabras clave de edificabilidad y urgencia:</strong> Suma puntos extra si el texto menciona <em>"esquina"</em>, <em>"da a dos calles"</em>, <em>"bajo + 2 alturas"</em>, <em>"urge vender"</em>, <em>"negociable"</em>, <em>"herencia"</em> o <em>"activo bancario"</em>.</li>
    <li><strong>Amplitud de parcela:</strong> Bonifica las parcelas de ≥ 180 m² y ≥ 300 m².</li>
  </ol>

  <h2>4. Cómo conectar tu Gmail en 2 minutos (Sin usar Google Cloud API)</h2>
  <div class="card blue">
    No necesitas contratar ninguna API ni saber programar. Google permite generar una <strong>Contraseña de Aplicación</strong> gratuita para que tu agente lea las alertas de Idealista/Fotocasa y te mande el resumen cada mañana:
    <ol style="margin-top:8px;">
      <li>Entra en tu cuenta de <strong>Idealista</strong> y <strong>Fotocasa</strong>, busca Terrenos y Casas a reformar en tus zonas y pulsa <strong>"Guardar búsqueda → Recibir alertas por email"</strong>.</li>
      <li>Entra en <a href="https://myaccount.google.com/apppasswords">https://myaccount.google.com/apppasswords</a> con tu cuenta de Gmail, escribe de nombre <code>Agente Solares</code> y copia la clave de <strong>16 letras</strong> que aparece en pantalla.</li>
      <li>Si lo usas en tu PC, copia el archivo <code>.env.example</code> a <code>.env</code> y pega tu correo y esas 16 letras. Si lo subes a GitHub (nube gratuita), pégalas en <strong>Settings → Secrets and variables → Actions</strong>.</li>
    </ol>
  </div>
</body>
</html>
"""


def build_html_and_pdf() -> None:
    html_path = os.path.join(BASE_DIR, "docs", "guia_funcionamiento.html")
    pdf_path = os.path.join(BASE_DIR, "Guia_Agente_Solares_Vega_Baja.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(GUIDE_HTML)

    # Intentar generar el PDF con Microsoft Edge Headless (preinstalado en Windows 10/11)
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_bin = next((p for p in edge_paths if os.path.exists(p)), None)
    if edge_bin:
        try:
            subprocess.run(
                [
                    edge_bin,
                    "--headless",
                    "--disable-gpu",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}",
                    html_path,
                ],
                check=True,
                timeout=25,
            )
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
                print(f"[OK] PDF generado con Edge en: {pdf_path}")
                return
        except Exception as e:
            print(f"[Aviso] Edge headless no pudo imprimir PDF directamente: {e}")

    # Fallback: Generador PDF nativo en Python puro si Edge no está disponible en sandbox
    build_pure_python_pdf(pdf_path)


def build_pure_python_pdf(pdf_path: str) -> None:
    """Genera un documento PDF multipágina válido en Python puro (estándar PDF 1.4)."""
    pages_lines = [
        [
            "MANUAL DE FUNCIONAMIENTO - AGENTE SOLARES Y CASAS VEGA BAJA",
            "Orihuela, Montepinar, Raiguero de Bonanza, Raiguero de Levante, Benferri y Granja de Rocamora",
            "--------------------------------------------------------------------------------------------",
            "",
            "1. DE DONDE SACA LA INFORMACION EL AGENTE?",
            "",
            "A) Por que ya aparecen 14 anuncios sin haber metido clave de Gmail?",
            "   Para que puedas probar el panel, los filtros y las curvas de precios desde el minuto 1,",
            "   el programa carga una Semilla Inicial de 14 anuncios de referencia en tus pedanias.",
            "",
            "B) Cuando se conecta a Internet (3 canales simultaneos):",
            "   - Canal 1 (Scraping Directo SIN CLAVES): Escanea Pisos.com, Habitaclia, Yaencontre,",
            "     Trovimap, Bancos (Solvia, Aliseda, Haya) e inmobiliarias locales de la Vega Baja.",
            "   - Canal 2 (Buscador Indexado SIN CLAVES): Descubre anuncios publicos de Idealista,",
            "     Fotocasa y Milanuncios en tus zonas sin chocar con los bloqueos anti-robots.",
            "   - Canal 3 (Lector de Alertas de Correo IMAP): Lee los correos gratuitos de alerta que",
            "     te mandan Idealista y Fotocasa. Asi te saltas al 100% sus bloqueos sin pagar proxies.",
            "",
            "2. COMO CONECTAR TU GMAIL EN 2 MINUTOS (SIN API DE GOOGLE CLOUD)",
            "",
            "   No hace falta usar Google Cloud ni pagar nada. Solo necesitas una Contrasena de Aplicacion:",
            "   1. Guarda tus busquedas en Idealista y Fotocasa y activa 'Recibir alertas por email'.",
            "   2. Entra en https://myaccount.google.com/apppasswords y crea una clave para 'Agente Solares'.",
            "   3. Google te dara 16 letras. Pon tu correo y esas 16 letras en el archivo .env (en tu PC)",
            "      o en los Secrets de GitHub Actions (para que corra gratis en la nube cada manana).",
        ],
        [
            "3. FILTRO DE 180 m2, DETECCION DE PEDANIAS Y CHOLLO SCORE",
            "--------------------------------------------------------------------------------------------",
            "",
            "A) Regla de Superficie (>= 180 m2):",
            "   - El agente guarda TODOS los solares y casas de planta baja en la base de datos SQLite,",
            "     pero destaca en la vista principal y en el email diario SOLO los que tienen >= 180 m2.",
            "   - Los de menos de 180 m2 quedan guardados en la pestana 'Todos (incl. < 180 m2)'.",
            "   - Si un anuncio local habla en 'tahullas', convierte automaticamente 1 tahulla = 1.118 m2.",
            "",
            "B) Deteccion inteligente de Pedanias y limpieza de Orihuela Costa:",
            "   - Detecta Raiguero de Bonanza (o Riguero / Rincon de Bonanza), Raiguero de Levante,",
            "     Montepinar, Benferri, Granja de Rocamora, Orihuela Casco y pedanias cercanas.",
            "   - Descarta automaticamente Orihuela Costa (La Zenia, Cabo Roig, Villamartin, Campoamor)",
            "     y descarta pisos en altura.",
            "",
            "C) Como calcula el Chollo Score (0 a 100 puntos):",
            "   - Compara el precio en EUR/m2 de suelo contra la mediana de esa pedania concreta.",
            "   - Suma puntos si detecta bajadas historicas de precio en la base de datos.",
            "   - Suma puntos si el anuncio menciona: 'esquina', 'dos calles', 'bajo + alturas',",
            "     'urge vender', 'precio negociable', 'herencia' o 'activo bancario'.",
        ],
    ]

    objects = []

    def add_obj(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_ids = []
    for lines in pages_lines:
        stream_cmds = ["BT", "/F1 10.5 Tf", "45 790 Td", "15 TL"]
        for i, ln in enumerate(lines):
            safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if i in (0, 4, 18) or ln.startswith("3."):
                stream_cmds.append(f"/F2 11.5 Tf ({safe}) Tj /F1 10.5 Tf T*")
            else:
                stream_cmds.append(f"({safe}) Tj T*")
        stream_cmds.append("ET")
        stream_bytes = "\n".join(stream_cmds).encode("latin-1", errors="replace")
        content_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream"
        )
        page_id = add_obj(
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R /F2 {font_bold_id} 0 R >> >> /Contents {content_id} 0 R >>".encode(
                "ascii"
            )
        )
        page_ids.append(page_id)

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_root_id = add_obj(f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("ascii"))
    for pid in page_ids:
        objects[pid - 1] = objects[pid - 1].replace(b"/Parent 0 0 R", f"/Parent {pages_root_id} 0 R".encode("ascii"))

    catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_root_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    with open(pdf_path, "wb") as f:
        f.write(out)
    print(f"[OK] PDF nativo generado en: {pdf_path}")


if __name__ == "__main__":
    pptx_file = os.path.join(BASE_DIR, "Presentacion_Agente_Solares_Vega_Baja.pptx")
    build_pptx(pptx_file)
    print(f"[OK] PowerPoint generado en: {pptx_file}")
    build_html_and_pdf()
