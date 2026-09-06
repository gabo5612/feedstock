# crucible — plataforma local-first de riesgo de costo de insumos metálicos

**Fecha:** 2026-09-02
**Relación con el resto:** proyecto insignia del paso 2 de `~/Desktop/Gabo/CONTEXTO-AI-PORTFOLIO-CV.md` §7.
**Decisiones tomadas:** encuadre = metales / costo de insumos · stack = Python + React.

---

## 0. Qué es, en una frase

Una planta metalúrgica compra cobre, aluminio, oro, platino y energía. Su margen lo
decide el costo de esos insumos. `crucible` ingiere los precios crudos, los normaliza,
deriva features, detecta anomalías y régimen, pronostica con **backtest walk-forward
honesto**, y lo sirve en vivo — **todo corriendo dentro de la planta**.

**Lo que NO es:** un bot de trading. No promete ganarle al mercado. La afirmación
defendible es *"acá está el error out-of-sample de cada modelo contra el baseline naive,
medido, reproducible"*. Esa es toda la diferencia frente a un portfolio con gráficos bonitos.

---

## 1. Verificación de fuentes de datos — hecha el 2026-09-02

No asumido. Probado con `curl` desde esta máquina, esta fecha.

### ✅ Funciona sin API key

**Yahoo Finance chart API** — `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}`
(requiere header `User-Agent`; sin él responde vacío)

| Ticker | Instrumento | Precio verificado hoy |
|---|---|---|
| `GC=F` | Oro (Dec 26) | 4428.1 |
| `SI=F` | Plata (Dec 26) | 65.87 |
| `HG=F` | Cobre (Dec 26) | 6.605 |
| `ALI=F` | Aluminio (Nov 26) | 3437.5 |
| `PL=F` | Platino (Oct 26) | 1765.6 |
| `PA=F` | Paladio (Dec 26) | 1361.0 |
| `NG=F` | Gas natural (Oct 26) | 3.009 |
| `CL=F` | Crudo WTI (Oct 26) | 90.69 |
| `DX-Y.NYB` | Índice dólar ICE | 99.596 |
| `USDCNY=X` | USD/CNY | 6.71 |
| `USDSAR=X` | USD/SAR | 3.7549 |
| `EURUSD=X` | EUR/USD | 1.1589 |
| `^SPGSIN` | S&P GSCI Industrial Metals | 618.88 |
| `XME` / `COPX` | ETFs de metales / mineras de cobre | 119.46 / 89.9 |

**Profundidad verificada:**
- Diario: `period1`/`period2` en epoch → **2515 velas en 10 años** (2016-09-06 → 2026-09-02). ✔
- ⚠️ `range=max&interval=1d` **NO da diario**: devolvió solo 268 puntos para 26 años
  (Yahoo lo submuestrea a mensual en silencio). **Hay que paginar con period1/period2 por
  tramos.** Este es exactamente el tipo de bug que pasa desapercibido.
- Intradía 1m: **6936 velas en 5 días** por instrumento. Yahoo solo retiene ~7 días de 1m,
  así que el histórico intradía **se acumula corriendo el ingester**, no se descarga.

**Kraken** `api.kraken.com/0/public/OHLC` — ✔ velas 1m, sin key.
**Coinbase** `api.exchange.coinbase.com/products/{p}/candles` — ✔ sin key.
(Ambos solo si se quiere una fuente de volumen alto para estresar el pipeline.)

### 🔑 Funciona con key gratis (registro, sin tarjeta)
- **FRED** (`api.stlouisfed.org`) — índices PPI de metales, producción industrial, tasas.
  Endpoint responde; error explícito `api_key is not set`. Registro en fred.stlouisfed.org.
- **EIA v2** (`api.eia.gov`) — precios de gas y electricidad. Mismo caso.

### ❌ Bloqueado / descartado
- **Binance** — `"Service unavailable from a restricted location"`. **Geo-bloqueado desde
  acá.** Descartado como fuente.
- **Stooq** — devuelve un challenge JavaScript anti-bot, no CSV. Descartado.
- **LME (níquel, zinc, estaño reales)** — es de pago. No hay ticker gratis.
  Proxies disponibles: `^SPGSIN`, `XME`, `COPX`.
- ⚠️ **Trampa detectada:** `ZN=F` **no es zinc** — es el futuro del bono del Tesoro a 10 años
  (devolvió 107.5, "10-Year T-Note Futures"). Meterlo en un dataset de metales habría
  contaminado todo el modelo **sin error visible**. Anotado a propósito: el registro de
  instrumentos lleva `display_name` verificado contra la respuesta de la fuente, no el
  ticker a secas.

### Nota de honestidad sobre Yahoo
La chart API es no oficial y sin contrato de servicio. Para un proyecto de portfolio está
bien; para producción no. **Por eso el ingester va detrás de una interfaz `SourceAdapter`:
cambiar a un feed pago (o al LME real) es escribir una clase, no reescribir el sistema.**
Eso se documenta como decisión, no se esconde.

---

## 2. Entorno local — estado verificado hoy

| Herramienta | Estado |
|---|---|
| Python | 3.14.6 (`/opt/homebrew/bin/python3`) |
| Stack ML en 3.14 | ✅ **`lightgbm` + `polars` + `statsmodels` + `scikit-learn` instalan sin problema** (probado con `uv venv --python 3.14`) |
| `uv` | ✅ instalado |
| Node | v24.16.0 ✅ |
| Ollama | binario presente, **servidor no corriendo** (`ollama serve`) |
| Docker | ❌ **no instalado** |
| psql | ❌ no instalado (irrelevante: va en contenedor) |

**Bloqueante único:** Docker. Sin él no hay Postgres/Timescale ni el entregable
"`docker compose up` sin internet". Instalar **Colima** (`brew install colima docker docker-compose`)
o Docker Desktop.

---

## 3. Arquitectura

```
  fuentes            INGESTA           ALMACENAMIENTO        PROCESO            SERVICIO
  ───────            ───────           ──────────────        ───────            ────────
  Yahoo    ─┐
  FRED     ─┼─▶  SourceAdapter  ─▶   raw.ohlcv_ingest   ─▶  core.bar      ─▶  FastAPI
  EIA      ─┤    (idempotente,        (append-only,          (normalizado,      + SSE
  Kraken   ─┘     con reintento)       inmutable)             deduplicado)      ──▶ React
                                              │                    │
                                              │                    ▼
                                              │             feat.feature
                                              │             (versionado)
                                              │                    │
                                              │                    ▼
                                              │        BACKTEST WALK-FORWARD
                                              │        naive → ARIMA → LightGBM
                                              │                    │
                                              │                    ▼
                                              └──────▶  model.prediction / model.metric
                                                                   │
                                                                   ▼
                                                        Ollama local + pgvector
                                                        (narrativa CON CITA)
```

**Todo en un `docker compose`:** `timescale/timescaledb-ha` (trae pgvector), el ingester,
la API, el dashboard, Ollama. Levanta en una máquina sin internet una vez cacheadas las
imágenes y el modelo.

---

## 4. Modelo de datos

```sql
-- CAPA CRUDA: sagrada. Nunca se modifica. Todo lo demás se reconstruye desde acá.
raw.ohlcv_ingest (
  source, symbol, interval, ts,
  open, high, low, close, volume,
  ingested_at, payload_hash, request_id
)  -- hypertable en ts; PK (source,symbol,interval,ts) → reingesta idempotente
   -- compresión a los 7 días

core.instrument (symbol, source_ticker, display_name_verified, asset_class, unit, currency)
core.bar        (symbol, interval, ts, ohlcv, is_gap)   -- normalizado, huecos marcados
feat.feature    (symbol, ts, name, value, feature_version)
model.run       (run_id, model, params, feature_version, train_window, git_sha, created_at)
model.prediction(run_id, symbol, origin_ts, horizon, yhat, lo80, hi80)
model.metric    (run_id, symbol, horizon, metric, value)
```

### El invariante que va escrito en el código
Espejo del `"cosine distance is meaningless"` del Content Tool:

> *Una fila de `model.prediction` solo es comparable con otra si comparte `feature_version`
> y fue producida por un origen walk-forward que jamás vio datos posteriores a `origin_ts`.
> El entrenador y el backtester importan la lógica de corte desde este mismo módulo,
> por esa razón.*

### El guard de fuga de datos ← el artefacto que más vale
Un test determinista que, para cada feature en cada `origin_ts`, afirma que ningún insumo
proviene de un timestamp posterior. **Falla el CI si se rompe.**

El *look-ahead bias* es el error que hace que el 95% de los proyectos de predicción de
precios en GitHub sean basura con gráficos preciosos. Tener un test que lo prohíbe, en CI,
es la pieza más convincente del proyecto entero — y es la misma idea de `crew`:
**verificación determinista, ningún modelo juzgando a otro modelo.**

---

## 5. De dónde sale el volumen real (honesto)

8 instrumentos × 2515 velas diarias = **~20 mil filas**. Eso no es "grandes cantidades de datos".
El volumen genuino está en otro lado:

| Fuente de volumen | Orden de magnitud |
|---|---|
| Barras 1m acumuladas por el ingester (8 instr. × ~1400/día) | ~11k filas/día, ~4M/año |
| Features derivadas (~40 features × ventanas × instrumentos) | ×40 sobre lo anterior |
| **Artefactos de backtest** — cada origen walk-forward × horizonte × modelo × versión de features | **10 años × 8 instr. × 30 horizontes × 4 modelos × 5 versiones ≈ 12M filas de predicción** |

**El volumen viene del backtest, no de los precios.** Y esa es justamente la razón
legítima para Timescale: consultas analíticas sobre decenas de millones de filas
particionadas por tiempo. No es Timescale porque suena bien.

---

## 6. La escalera de modelos

Ninguno se acepta sin superar al de abajo, medido out-of-sample:

| Nivel | Modelo | Rol |
|---|---|---|
| 0 | **Naive** (mañana = hoy) | El baseline. En precios es brutalmente difícil de vencer |
| 1 | ARIMA / ETS | Clásico, interpretable |
| 2 | LightGBM sobre features de lag | El que suele ganar en la práctica |
| 3 | Red temporal | Solo si el nivel 2 se queda corto |

**Métricas:** MASE contra naive estacional · precisión direccional · pinball loss ·
cobertura real del intervalo al 80%.

**Regla de publicación:** el número se publica como sale. Si el naive gana a horizonte 1 día
y LightGBM gana a 30, se dice exactamente eso. Un resultado negativo bien medido es
evidencia de ingeniería; uno inflado destruye la credibilidad de todo el portfolio
(regla §8 del contexto: *no inventar métricas*).

---

## 7. Capa de lenguaje (local)

Ollama + pgvector, sobre el mismo Postgres:
- *"¿por qué se movió el cobre esta semana?"* → RAG sobre notas/reportes ingestados,
  **respuesta con cita a fuente y fecha**.
- **El número nunca lo inventa el modelo:** los valores salen de una consulta SQL; el LLM
  solo redacta. Los números en el prompt vienen de la DB y se citan.

Es el port on-prem que §5 del contexto ya identificó: embeddings locales (`bge-m3` /
`nomic-embed`), generación local (Qwen), Postgres auto-hospedado. **No es aprender algo
nuevo — es portar lo que ya domina del Content Tool.**

---

## 8. Hitos, cada uno con criterio de aceptación verificable

| # | Hito | Se acepta cuando |
|---|---|---|
| M0 | Docker + Timescale arriba | `docker compose up` levanta, extensiones `timescaledb` y `vector` presentes |
| M1 | Ingesta + backfill 10 años, 12 instrumentos | Reporte de conteo de filas y huecos por instrumento; reingesta no duplica |
| M2 | Features + **guard de fuga en CI** | El test de look-ahead corre y falla al inyectarle una fuga a propósito |
| M3 | Backtest + baseline naive **publicado primero** | Tabla de MASE/direccional del naive por horizonte. Fija la vara antes de competir |
| M4 | ARIMA + LightGBM contra el baseline | Tabla comparativa out-of-sample, sin editar |
| M5 | Anomalías + régimen + dashboard en vivo | SSE empujando; panel de anomalías con umbral justificado |
| M6 | Ollama con citas + compose offline | Corre con el wifi apagado; toda respuesta trae fuente y fecha |

---

## 9. Cómo se cuenta en el CV (§4 del contexto)

Cierra 5 huecos abiertos:

| Hueco | Cómo lo cierra |
|---|---|
| ❌ Evals | El harness de backtest **es** el eval: reproducible, con guard de fuga en CI |
| ❌ Sustrato on-prem | Postgres + Ollama + workers, todo self-hosted |
| ❌ Infra / red aislada | `docker compose up` sin internet |
| ❌ Dominio metalúrgico | Cobre, aluminio, oro, energía, riesgo de costo de insumos |
| ❌ Servir modelos on-prem | Ollama/vLLM en la capa de lenguaje |

Y sostiene el eje narrativo de §1: **los datos no salen de la máquina.**

---

## 10. Antes de escribir código

1. **Instalar Docker** — `brew install colima docker docker-compose && colima start`. Bloqueante de M0.
2. **Keys gratis** (opcional, solo para FRED/EIA en M1+): fred.stlouisfed.org y eia.gov/opendata.
3. **Decidir versión de Python** — 3.14 funciona (probado). Igual conviene fijarla en
   `.python-version` con `uv` para que el contenedor y la máquina coincidan.


### 🔑 Keys — dónde viven

Las keys de **FRED** y **EIA v2** están en `crucible/.env`, que `.gitignore` excluye.
Se leen con `os.environ["FRED_API_KEY"]` / `["EIA_API_KEY"]`, nunca hardcodeadas.

> Estuvieron en texto plano en este mismo archivo hasta el 2026-09-06. Se movieron porque
> este documento es material de handoff y acompañaría al repo si `crucible` se publica —
> una key en un `.md` de portfolio es una filtración esperando la fecha. **Si el archivo
> llegó a estar en algún commit o copia, revocá y regenerá las dos** en
> fred.stlouisfed.org y eia.gov/opendata: es gratis y toma un minuto.