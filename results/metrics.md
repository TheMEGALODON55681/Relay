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
| COORDINATED_FDI | -0.1971 | -0.0013 | -0.0121 |
| LOAD_INFLATION | 212.988 | 1.4194 | 3.4019 |
| LOAD_SUPPRESSION | -145.9402 | -0.9728 | 2.3031 |

Unnecessary generation (MWh) is the deviation from the true load and is the
reliable cross-scenario signal. Dollar cost prevented can be negative for
LOAD_SUPPRESSION: without security the optimizer under-generates against a
falsely low reading, which is cheaper but unsafe (insufficient reserve); with
security dispatch is restored to the true, higher load, which costs more but
removes the deviation from truth. That is security working as intended, not a
regression - see PROJECT_PLAN.md Section 6.

COORDINATED_FDI shifts feeder sensors, not the substation the optimizer dispatches
from, so its own reading stays correct in most runs and ON/OFF dispatch is
identical. In a minority of runs the substation's cross-sensor physics evidence
still implicates it, containment quarantines it as a precaution, and the gateway's
estimate introduces a small deviation from its own already-correct live reading -
the near-zero or slightly negative numbers above are that estimation noise, not a
detection failure: the underlying attack is still caught (see detection rate).
