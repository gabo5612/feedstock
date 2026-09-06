# AI context

> **feedstock — local-first input-cost risk for a metals plant**
>
> Ingests metal and energy prices, derives features with no data leakage, computes a plant's real unit cost and measures whether today is a good time to buy — all running inside the plant, without internet.

This file exists so an AI assistant — or a person in a hurry — can understand the project
**in full** without reading files at random. The reading order below is not arbitrary: each
file assumes the previous one.

## 🔗 Open with the context already loaded

**[▸ Open in ChatGPT with this project explained](https://chatgpt.com/?q=I%20want%20you%20to%20understand%20the%20%60feedstock%60%20project%20%28local%20code%20%E2%80%94%20ask%20the%20user%20for%20the%20files%29%20thoroughly.%0A%0Afeedstock%20%E2%80%94%20local-first%20input-cost%20risk%20for%20a%20metals%20plant%0AIngests%20metal%20and%20energy%20prices%2C%20derives%20features%20with%20no%20data%20leakage%2C%20computes%20a%20plant%27s%20real%20unit%20cost%20and%20measures%20whether%20today%20is%20a%20good%20time%20to%20buy%20%E2%80%94%20all%20running%20inside%20the%20plant%2C%20without%20internet.%0A%0ARead%20these%20files%20IN%20THIS%20ORDER%2C%20because%20each%20assumes%20the%20previous%20one%3A%0A1.%20%60README.md%60%20%E2%80%94%20what%20it%20is%2C%20what%20it%20is%20NOT%20%28not%20a%20trading%20bot%29%2C%20status%20per%20milestone%0A2.%20%60src%2Ffeedstock%2Finstruments.py%60%20%E2%80%94%20the%20registry%20and%20why%20%60ZN%3DF%60%20is%20not%20zinc%0A3.%20%60src%2Ffeedstock%2Fsources%2Fyahoo.py%60%20%E2%80%94%20why%20%60range%3Dmax%60%20lies%20and%20you%20have%20to%20paginate%0A4.%20%60src%2Ffeedstock%2Fleakcheck.py%60%20%E2%80%94%20the%20leakage%20guard%3A%20the%20artefact%20that%20matters%20most%0A5.%20%60src%2Ffeedstock%2Fsignals.py%60%20%E2%80%94%20the%20buy%20signal%20and%20its%20backtest%20against%20buying%20blind%0A6.%20%60src%2Ffeedstock%2Fbasket.py%60%20%E2%80%94%20the%20cost%20basket%2C%20exposure%20and%20scenarios%0A7.%20%60src%2Ffeedstock%2Fquality.py%60%20%E2%80%94%20the%20data-quality%20monitor%20and%20why%20it%20corrected%20its%20own%20message%0A%0APay%20particular%20attention%20to%20the%20code%20comments%3A%20they%20explain%20WHY%20something%20is%20done%20one%20way%20and%20not%20another%2C%20and%20there%20is%20almost%20always%20a%20real%20bug%20behind%20it.%0A%0AWhen%20you%27re%20done%2C%20answer%20these%20questions%20with%20evidence%20from%20the%20code%3A%0A-%20Why%20does%20the%20buy%20signal%20say%20buying%20cheap%20copper%20historically%20did%20WORSE%3F%0A-%20How%20is%20it%20proven%20that%20no%20feature%20looks%20into%20the%20future%3F%0A-%20Why%20does%20the%20what-if%20scenario%20NOT%20propagate%20the%20shock%20via%20correlation%3F%0A-%20Why%20do%20unit%20conversions%20fail%20loudly%20instead%20of%20assuming%3F%0A%0ADon%27t%20just%20summarise%20the%20README.%20I%20want%20you%20to%20be%20able%20to%20discuss%20the%20design%20decisions.)**

That link carries the prompt pre-loaded. If you'd rather assemble it yourself, paste this:

```text
I want you to understand the `feedstock` project (local code — ask the user for the files) thoroughly.

feedstock — local-first input-cost risk for a metals plant
Ingests metal and energy prices, derives features with no data leakage, computes a plant's real unit cost and measures whether today is a good time to buy — all running inside the plant, without internet.

Read these files IN THIS ORDER, because each assumes the previous one:
1. `README.md` — what it is, what it is NOT (not a trading bot), status per milestone
2. `src/feedstock/instruments.py` — the registry and why `ZN=F` is not zinc
3. `src/feedstock/sources/yahoo.py` — why `range=max` lies and you have to paginate
4. `src/feedstock/leakcheck.py` — the leakage guard: the artefact that matters most
5. `src/feedstock/signals.py` — the buy signal and its backtest against buying blind
6. `src/feedstock/basket.py` — the cost basket, exposure and scenarios
7. `src/feedstock/quality.py` — the data-quality monitor and why it corrected its own message

Pay particular attention to the code comments: they explain WHY something is done one way and not another, and there is almost always a real bug behind it.

When you're done, answer these questions with evidence from the code:
- Why does the buy signal say buying cheap copper historically did WORSE?
- How is it proven that no feature looks into the future?
- Why does the what-if scenario NOT propagate the shock via correlation?
- Why do unit conversions fail loudly instead of assuming?

Don't just summarise the README. I want you to be able to discuss the design decisions.
```

## Reading order

| # | File | Why |
|---|---|---|
| 1 | `README.md` | what it is, what it is NOT (not a trading bot), status per milestone |
| 2 | `src/feedstock/instruments.py` | the registry and why `ZN=F` is not zinc |
| 3 | `src/feedstock/sources/yahoo.py` | why `range=max` lies and you have to paginate |
| 4 | `src/feedstock/leakcheck.py` | the leakage guard: the artefact that matters most |
| 5 | `src/feedstock/signals.py` | the buy signal and its backtest against buying blind |
| 6 | `src/feedstock/basket.py` | the cost basket, exposure and scenarios |
| 7 | `src/feedstock/quality.py` | the data-quality monitor and why it corrected its own message |

## The questions this project answers

- Why does the buy signal say buying cheap copper historically did WORSE?
- How is it proven that no feature looks into the future?
- Why does the what-if scenario NOT propagate the shock via correlation?
- Why do unit conversions fail loudly instead of assuming?

## How this code is written

Three things that repeat throughout the repository and are worth knowing before reading it:

1. **Comments explain the *why*, not the *what*.** If a comment says something is done in an
   odd way, there is a real bug behind it — almost always a silent one.
2. **What could not be measured is stated, not filled in.** An `n/a` is an answer; a filler
   zero is a lie that later gets copied into a README.
3. **The tests that matter are the ones proving the verification works** — not just that the
   code passes. Look for the ones that inject a failure on purpose and require it to be
   caught.

---
*Generated 2026-09-06. If the project has moved on, this file may be stale: the code wins.*
