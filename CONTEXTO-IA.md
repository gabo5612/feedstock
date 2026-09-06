# Contexto para IA

> **crucible — riesgo de costo de insumos metálicos, local-first**
>
> Ingiere precios de metales y energía, deriva features sin fuga de datos, calcula el costo unitario real de una planta y mide si conviene comprar hoy — todo corriendo dentro de la planta, sin internet.

Este archivo existe para que un asistente de IA —o una persona con prisa— entienda el
proyecto **completo** sin ir leyendo archivos al azar. El orden de lectura de abajo no es
arbitrario: cada archivo asume lo del anterior.

## 🔗 Abrir con el contexto ya cargado

**[▸ Abrir en ChatGPT con este proyecto explicado](https://chatgpt.com/?q=Quiero%20que%20entiendas%20a%20fondo%20el%20proyecto%20%60crucible%60%20%28c%C3%B3digo%20local%2C%20pedile%20al%20usuario%20los%20archivos%29.%0A%0Acrucible%20%E2%80%94%20riesgo%20de%20costo%20de%20insumos%20met%C3%A1licos%2C%20local-first%0AIngiere%20precios%20de%20metales%20y%20energ%C3%ADa%2C%20deriva%20features%20sin%20fuga%20de%20datos%2C%20calcula%20el%20costo%20unitario%20real%20de%20una%20planta%20y%20mide%20si%20conviene%20comprar%20hoy%20%E2%80%94%20todo%20corriendo%20dentro%20de%20la%20planta%2C%20sin%20internet.%0A%0ALe%C3%A9%20estos%20archivos%20EN%20ESTE%20ORDEN%2C%20porque%20cada%20uno%20asume%20el%20anterior%3A%0A1.%20%60README.md%60%20%E2%80%94%20qu%C3%A9%20es%2C%20qu%C3%A9%20NO%20es%20%28no%20es%20un%20bot%20de%20trading%29%20y%20el%20estado%20por%20hito%0A2.%20%60src%2Fcrucible%2Finstruments.py%60%20%E2%80%94%20el%20registro%20y%20por%20qu%C3%A9%20%60ZN%3DF%60%20no%20es%20zinc%0A3.%20%60src%2Fcrucible%2Fsources%2Fyahoo.py%60%20%E2%80%94%20por%20qu%C3%A9%20%60range%3Dmax%60%20miente%20y%20hay%20que%20paginar%0A4.%20%60src%2Fcrucible%2Fleakcheck.py%60%20%E2%80%94%20el%20guard%20de%20fuga%3A%20el%20artefacto%20que%20m%C3%A1s%20vale%0A5.%20%60src%2Fcrucible%2Fsignals.py%60%20%E2%80%94%20la%20se%C3%B1al%20de%20compra%20y%20su%20backtest%20contra%20comprar%20sin%20mirar%0A6.%20%60src%2Fcrucible%2Fbasket.py%60%20%E2%80%94%20la%20canasta%20de%20costo%2C%20exposici%C3%B3n%20y%20escenarios%0A7.%20%60src%2Fcrucible%2Fquality.py%60%20%E2%80%94%20el%20monitor%20de%20calidad%20y%20por%20qu%C3%A9%20corrigi%C3%B3%20su%20propio%20mensaje%0A%0APrest%C3%A1%20especial%20atenci%C3%B3n%20a%20los%20comentarios%20del%20c%C3%B3digo%3A%20explican%20POR%20QU%C3%89%20algo%20se%20hace%20de%20una%20manera%20y%20no%20de%20otra%2C%20y%20casi%20siempre%20hay%20un%20bug%20real%20detr%C3%A1s.%0A%0ACuando%20termines%2C%20respondeme%20estas%20preguntas%20con%20evidencia%20del%20c%C3%B3digo%3A%0A-%20%C2%BFPor%20qu%C3%A9%20la%20se%C3%B1al%20de%20compra%20dice%20que%20comprar%20cobre%20barato%20sali%C3%B3%20PEOR%20hist%C3%B3ricamente%3F%0A-%20%C2%BFC%C3%B3mo%20se%20prueba%20que%20ninguna%20feature%20mira%20el%20futuro%3F%0A-%20%C2%BFPor%20qu%C3%A9%20el%20escenario%20%27qu%C3%A9%20pasa%20si%27%20NO%20propaga%20el%20shock%20v%C3%ADa%20correlaci%C3%B3n%3F%0A-%20%C2%BFPor%20qu%C3%A9%20las%20conversiones%20de%20unidades%20fallan%20fuerte%20en%20vez%20de%20asumir%3F%0A%0ANo%20resumas%20el%20README%20y%20ya.%20Quiero%20que%20puedas%20discutir%20las%20decisiones%20de%20dise%C3%B1o.)**

Ese link lleva el prompt pre-cargado. Si preferís armarlo a mano, pegá esto:

```text
Quiero que entiendas a fondo el proyecto `crucible` (código local, pedile al usuario los archivos).

crucible — riesgo de costo de insumos metálicos, local-first
Ingiere precios de metales y energía, deriva features sin fuga de datos, calcula el costo unitario real de una planta y mide si conviene comprar hoy — todo corriendo dentro de la planta, sin internet.

Leé estos archivos EN ESTE ORDEN, porque cada uno asume el anterior:
1. `README.md` — qué es, qué NO es (no es un bot de trading) y el estado por hito
2. `src/crucible/instruments.py` — el registro y por qué `ZN=F` no es zinc
3. `src/crucible/sources/yahoo.py` — por qué `range=max` miente y hay que paginar
4. `src/crucible/leakcheck.py` — el guard de fuga: el artefacto que más vale
5. `src/crucible/signals.py` — la señal de compra y su backtest contra comprar sin mirar
6. `src/crucible/basket.py` — la canasta de costo, exposición y escenarios
7. `src/crucible/quality.py` — el monitor de calidad y por qué corrigió su propio mensaje

Prestá especial atención a los comentarios del código: explican POR QUÉ algo se hace de una manera y no de otra, y casi siempre hay un bug real detrás.

Cuando termines, respondeme estas preguntas con evidencia del código:
- ¿Por qué la señal de compra dice que comprar cobre barato salió PEOR históricamente?
- ¿Cómo se prueba que ninguna feature mira el futuro?
- ¿Por qué el escenario 'qué pasa si' NO propaga el shock vía correlación?
- ¿Por qué las conversiones de unidades fallan fuerte en vez de asumir?

No resumas el README y ya. Quiero que puedas discutir las decisiones de diseño.
```

## Orden de lectura

| # | Archivo | Por qué |
|---|---|---|
| 1 | `README.md` | qué es, qué NO es (no es un bot de trading) y el estado por hito |
| 2 | `src/crucible/instruments.py` | el registro y por qué `ZN=F` no es zinc |
| 3 | `src/crucible/sources/yahoo.py` | por qué `range=max` miente y hay que paginar |
| 4 | `src/crucible/leakcheck.py` | el guard de fuga: el artefacto que más vale |
| 5 | `src/crucible/signals.py` | la señal de compra y su backtest contra comprar sin mirar |
| 6 | `src/crucible/basket.py` | la canasta de costo, exposición y escenarios |
| 7 | `src/crucible/quality.py` | el monitor de calidad y por qué corrigió su propio mensaje |

## Las preguntas que este proyecto responde

- ¿Por qué la señal de compra dice que comprar cobre barato salió PEOR históricamente?
- ¿Cómo se prueba que ninguna feature mira el futuro?
- ¿Por qué el escenario 'qué pasa si' NO propaga el shock vía correlación?
- ¿Por qué las conversiones de unidades fallan fuerte en vez de asumir?

## Cómo está escrito este código

Tres cosas que se repiten en todo el repositorio y conviene saber antes de leerlo:

1. **Los comentarios explican el *porqué*, no el *qué*.** Si un comentario dice que algo
   se hace de una manera rara, ahí hay un bug real detrás, casi siempre uno silencioso.
2. **Lo que no se pudo medir se dice, no se rellena.** Un `n/a` es una respuesta; un cero
   de relleno es una mentira que después se copia a un README.
3. **Los tests que importan son los que prueban que la verificación sirve** — no solo que
   el código pasa. Buscá los que inyectan un fallo a propósito y exigen que sea detectado.

---
*Generado el 2026-09-06. Si el proyecto cambió mucho, este archivo puede estar viejo: el
código manda.*
