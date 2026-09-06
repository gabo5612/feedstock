# crucible

Plataforma **local-first** de riesgo de costo de insumos metálicos. Ingiere los precios
crudos, los normaliza, deriva features, pronostica con backtest walk-forward honesto y lo
sirve en vivo — **todo corriendo dentro de la planta**.

**Lo que NO es:** un bot de trading. No promete ganarle al mercado. La afirmación
defendible es *"acá está el error out-of-sample de cada modelo contra el baseline naive,
medido y reproducible"*.

## Estado: M1 de 6

| Hito | | |
|---|---|---|
| **M0** | Docker + Timescale + pgvector | ✅ |
| **M1** | Ingesta + backfill 10 años, 12 instrumentos | ✅ |
| **M2** | Features + **guard de fuga en CI** | ✅ |
| M3 | Backtest + baseline naive publicado primero | ⬜ |
| M4 | ARIMA + LightGBM contra el baseline | ⬜ |
| M5 | Anomalías + régimen + dashboard | ⬜ |
| M6 | Ollama con citas + compose offline | ⬜ |

## La canasta de costo

Define la mezcla real de un producto (*"340 kg de cobre, 120 de aluminio, 0,8 MWh"*) y el
dashboard deja de mostrar precios genéricos para mostrar **tu costo unitario**.

Sobre la mezcla de ejemplo, medido: el costo subió **+47,8% en un año**, y el **92,2%
depende del cobre** — cubrir el gas (0,1%) no cambiaría nada.

Las unidades se convierten explícitamente y **fallan fuerte** ante lo desconocido: una
conversión implícita kg↔lb daría un costo 2,2 veces equivocado sin producir ningún error.
La onza troy (31,1 g) está separada de la común (28,35 g) porque confundirlas mete un 10%
de error en oro y plata.

## ¿Es buen momento para comprar?

**No predice el precio.** Dice dónde está hoy respecto de su propia historia y **qué pasó
después las veces anteriores que estuvo ahí**, contra el baseline de comprar sin mirar.

El resultado, medido sobre 10 años y publicado tal cual: **la intuición no se sostiene, y
en varios instrumentos está invertida.**

| instrumento | banda | n | ventaja |
|---|---|---|---|
| copper | muy_barato | 286 | **−1,8** |
| aluminium | muy_barato | 641 | **+3,3** |
| natgas | barato | 505 | **−4,9** |
| natgas | muy_caro | 384 | **+5,7** |

Comprar cobre barato salió *peor* que comprar en un día cualquiera. En gas está invertido.
Solo el aluminio se comporta como dice el sentido común.

Los cortes son quintiles elegidos **antes** de correr el backtest y no se movieron después.
El panel muestra la ventaja medida junto a la banda, y su color lo decide la evidencia:
una banda "muy barato" con ventaja negativa se pinta en rojo.

## Dashboard

```bash
.venv/bin/python -m uvicorn crucible.api.main:app --port 8090
# abrir http://127.0.0.1:8090
```

Buscar por nombre, filtrar por clase de activo, elegir hasta 8 instrumentos y comparar.
**Se sirve del mismo proceso que lee la base:** no hay servicio externo ni telemetría, y
funciona en una planta sin internet. Sin dependencias de front — los gráficos son SVG
escrito a mano.

Tres decisiones de lectura, no de estética:

- **Comparación indexada a base 100, nunca dos ejes.** El cobre vale ~6,7 USD/lb y el oro
  ~4 477 USD/oz. Superponerlos con escalas distintas hace que dos líneas se crucen por
  cómo se dibujó el gráfico y no por lo que hicieron los precios.
- **La correlación es de retornos diarios, no de precios.** Dos series con tendencia dan
  correlación alta aunque no tengan relación — la trampa clásica de este cálculo.
- **Ocho series es el tope**, porque es lo que valida la paleta. Un noveno color no se
  inventa: se recorta la selección.

## Levantar

```bash
docker-compose up -d                    # Timescale + pgvector en :5434
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/backfill.py    # los 12 instrumentos, 10 años
.venv/bin/python -m pytest
```

## Lo ingerido (medido el 2026-09-06)

**30 302 filas · 12 instrumentos · 0 errores · 0 huecos · 2016-09 → 2026-09**

Cada instrumento trae ~2 514 velas diarias en 10 años. Reingesta verificada idempotente:
correr el backfill de nuevo sobre el mismo tramo inserta **0 filas**.

## Dos cosas que sostienen todo lo demás

### 1. `ZN=F` no es zinc

Es el futuro del bono del Tesoro a 10 años, y Yahoo lo devuelve sin ningún error. Meterlo
en un dataset de metales lo contaminaría **sin una sola señal de que algo anda mal**, y un
modelo entrenado encima daría números perfectamente plausibles y perfectamente falsos.

Por eso cada instrumento declara un `expect_name` que **tiene** que aparecer en el nombre
que devuelve la fuente, y la verificación corre **antes de escribir una sola fila**:

```
zinc: el ticker 'ZN=F' devuelve '10-Year T-Note Futures,Dec-2026', que no contiene
'Zinc'. NO se ingirio nada.
```

### 2. `range=max` miente en silencio

`range=max&interval=1d` **no devuelve diario**: Yahoo lo submuestrea a mensual sin avisar.
Verificado dos veces sobre el cobre:

| petición | puntos en 10 años |
|---|---|
| `range=max&interval=1d` | **268** |
| `period1`/`period2` paginado | **2 515** |

Un backfill hecho con `range=max` produce un dataset que *parece* completo y no lo es. Por
eso el adaptador pagina por tramos.

## Arquitectura

Cuatro capas, y la división no es cosmética:

- **`raw`** — append-only y sagrada. PK `(source, symbol, interval, ts)` → reingesta
  idempotente. Nunca se modifica.
- **`core`** — normalizada, huecos marcados. Se **reconstruye** desde `raw`: si una
  normalización resulta estar mal, se corrige sin volver a pedirle nada a la fuente —
  que además puede haber cambiado o desaparecido.
- **`feat`** — versionada. Dos predicciones solo son comparables si comparten
  `feature_version`.
- **`model`** — `run`, `prediction`, `metric`.

La ingesta habla solo con `SourceAdapter`. Cambiar a un feed pago —o al LME real— es
escribir una clase, no reescribir el sistema. Eso es lo que hace honesto usar la chart API
de Yahoo, que es no oficial y sin contrato de servicio.
