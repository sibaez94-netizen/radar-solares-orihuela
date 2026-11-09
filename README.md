# Radar Autónomo de Solares y Casas de Pueblo a Reformar (Orihuela y Vega Baja)

Agente independiente 100% gratuito que monitoriza diariamente **solares urbanos**, **solares urbanizables** y **casas antiguas de planta baja a reformar o derribar** en:
- **Orihuela** (Casco histórico, centro, Rabaloche, San Antón, Capuchinos…)
- **Montepinar**
- **Raiguero de Bonanza** (y variantes como *Riguero de Bonanza* / *Rincón de Bonanza*)
- **Raiguero de Levante** (*Riguero de Levante*)
- **Benferri** (*Benfis Park* y casco urbano)
- **Granja de Rocamora**
- **Pedanías cercanas** (La Aparecida, Hurchillo, Arneva, Desamparados, Molins, La Campaneta, San Bartolomé…)

> **Filtro automático inteligente:** Guarda todos los inmuebles detectados en la base de datos histórica (`data/solares.db`), pero **destaca en la vista principal y en el correo diario solo aquellos con parcela ≥ 180 m²**, descartando automáticamente *Orihuela Costa* (playa), pisos en altura y fincas rústicas agrícolas no edificables. Además convierte automáticamente **tahúllas** (`1 tahúlla = 1.118 m²`) cuando aparecen en las descripciones locales.

---

## 🚀 Cómo ver el Panel Web ahora mismo en tu PC

1. Abre directamente el archivo **`docs/index.html`** con doble clic en tu navegador (Chrome, Edge, Safari o Firefox).
2. También puedes ver cómo queda el **Informe Diario por Correo** abriendo **`docs/last_email_preview.html`** o pulsando el botón **"📩 Ver Email Diario"** arriba a la derecha en el panel.
3. Para ejecutar el agente manualmente desde tu ordenador en cualquier momento:
   ```bash
   python main.py
   ```

---

## ☁️ Puesta en marcha en la Nube Gratis (GitHub Actions + GitHub Pages)

El sistema está diseñado para correr **100% gratis para siempre** usando **GitHub Actions** (ejecución diaria + base de datos versionada) y **GitHub Pages** (Panel Web accesible desde el móvil o PC).

### Paso 1: Subir esta carpeta a un repositorio de GitHub
1. Crea un repositorio en [GitHub](https://github.com/new) (por ejemplo `radar-solares-orihuela`).
2. Sube todos los archivos de esta carpeta.
3. En tu repositorio de GitHub, ve a **Settings → Pages**:
   - En **Build and deployment → Source**, elige **Deploy from a branch**.
   - Selecciona la rama `main` y la carpeta **`/docs`** y pulsa **Save**.
   - En 1 minuto tendrás tu panel online en `https://TU-USUARIO.github.io/radar-solares-orihuela/`.

### Paso 2: Configurar el correo diario y el lector anti-bloqueo de Idealista/Fotocasa (5 min)
Los grandes portales como **Idealista** y **Fotocasa** bloquean con *DataDome* las IPs de servidores en la nube. Para saltarse ese bloqueo al **100% sin pagar proxies**, el agente incluye un lector automático de alertas IMAP (`src/scrapers/imap_alerts.py`):

1. Entra en tu cuenta gratuita de **Idealista**, **Fotocasa** y **Milanuncios**, dibuja en el mapa tu zona (*Orihuela, Montepinar, Raiguero, Benferri, Granja de Rocamora*) para **Terrenos** y para **Casas de planta baja / a reformar**, y activa **"Guardar búsqueda → Recibir alertas por email"**.
2. En tu cuenta de Gmail, crea una **Contraseña de Aplicación** (en *Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones*).
3. En tu repositorio de GitHub, ve a **Settings → Secrets and variables → Actions → New repository secret** y añade:
   - `IMAP_USER`: tu correo (ej. `tucorreo@gmail.com`)
   - `IMAP_PASSWORD`: la contraseña de aplicación de 16 letras de Gmail
   - `SMTP_USER`: el mismo correo (`tucorreo@gmail.com`)
   - `SMTP_PASSWORD`: la misma contraseña de aplicación de 16 letras
   - `NOTIFY_EMAIL`: el correo donde quieres recibir cada mañana el resumen y los chollos
   - `DASHBOARD_URL`: la URL de tu GitHub Pages (ej. `https://TU-USUARIO.github.io/radar-solares-orihuela/`)

---

## ⚙️ Añadir más inmobiliarias locales de la Vega Baja

Puedes añadir cualquier web de inmobiliaria local en el archivo **`config.json`** dentro de `local_agencies_urls`. El parser universal (`src/scrapers/local_agencies_scraper.py`) detecta automáticamente fichas de Inmovilla, Witei, WordPress Real Estate y portales bancarios (Solvia, Aliseda, Haya).
