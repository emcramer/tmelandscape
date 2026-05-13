# Concept: parameter sampling (step 1)

> _Placeholder — will be filled in during Phase 2._

Step 1 of the pipeline samples the ABM parameter space and pairs each combination with initial cell positions from [`tissue_simulator`](https://github.com/emcramer/tissue_simulator). The output is a **sweep manifest** that the external simulation runner consumes.

Default sampler: Latin Hypercube (`pyDOE3`). Alternatives: Sobol, Halton (via `scipy.stats.qmc`).
