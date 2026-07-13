## Detection results

| Metric | Value |
|---|---|
| Detection rate | 100.0% |
| False positive rate | 0.131% |
| Mean detection latency (ticks) | 0.46 |
| Mean containment latency (ticks) | 0.31 |

## Security ON vs OFF: impact prevented (summed across runs)

| Scenario | Cost prevented | Emissions prevented | Unnecessary generation prevented (MWh) |
|---|---|---|---|
| COORDINATED_FDI | 29.8355 | 0.1989 | 0.0 |
| LOAD_INFLATION | 522.0785 | 3.4805 | 3.5337 |
| LOAD_SUPPRESSION | 158.6107 | 1.0574 | 2.4291 |

Unnecessary generation (MWh) is the deviation from the true load and is the
reliable cross-scenario signal: with the trusted data gateway's constraint
reconstruction (gateway/trusted_data_gateway.py), a sensor's dispatched value is
either an exact algebraic solve from currently-trusted peers or withheld entirely,
never an approximate guess, so unnecessary generation with security on is 0.0
across every scored scenario above.

Cost and emissions prevented follow from that same withhold-or-solve behavior
filtered through optimization/optimizer.py's dispatch stub, which charges nothing
for a withheld tick rather than modeling any fallback generation decision. Once
enough of a scenario's attack window ends up withheld (the substation's own
constraint peers correlated into containment too - see the Trusted Data Gateway
section of the README), security-on can accumulate less total cost than
security-off even where the underlying attack briefly caused an under- or
over-generation before containment reacted. Treat unnecessary generation MWh as
the primary signal and cost/emissions as secondary evidence shaped by the stub,
not a standalone claim about real dispatch economics.

COORDINATED_FDI shifts feeder sensors, not the substation the optimizer dispatches
from, so its own reading stays correct in most runs and ON/OFF dispatch is
identical; the small numbers above come from the minority of runs where the
attack's cross-sensor physics evidence reaches HIGH_RISK and containment engages.
The underlying attack is still caught in every run regardless (see detection rate).
