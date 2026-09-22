# Workflow — MicroQuantumGraph realtime microengine

Step-by-step execution of the plan. One step at a time, each with a review gate. Do not start a step
until the previous gate is green.

Reference numbers and reasoning live in the plan document; this file is the checklist.

Conventions:
- `[ ]` not started, `[~]` in progress, `[x]` done.
- Every step ends with `pytest tests -q` green. If it is not green, the step is not done.
- Commits are small and named after the step. No "wip" commits.

---

## Step 0 — Commit what exists, fix the repo hygiene

Why: `microquantumgraph/*.py` are modified-not-staged and `td/`, `tests/`, `__init__.py` are untracked.
Nothing is gitignored; a `git stash` or fresh clone loses most of the project.

- [ ] 0.1 Baseline: `.venv/bin/python -B tests/test_microquantumgraph.py` → `0 failure(s)`.
- [ ] 0.2 `.gitignore`: add `.DS_Store` and `pairwise-tomography/` (nested git clone, not ours).
- [ ] 0.3 `git rm --cached` the four tracked `.DS_Store` files.
- [ ] 0.4 Commit 1 — `microquantumgraph/` (core + `__init__.py`).
- [ ] 0.5 Commit 2 — `tests/`.
- [ ] 0.6 Commit 3 — `td/` as-is (bugs included; every later fix is then a reviewable diff).
- [ ] 0.7 Commit 4 — chore: gitignore + `.DS_Store` removal + this file.
- [ ] 0.8 Fix branch tracking: `MicroQuantumGraph` currently tracks `origin/interactive`.
      `git branch --set-upstream-to` is not enough — push with `-u origin MicroQuantumGraph`.
- [ ] 0.9 **Gate (needs your go):** push to `origin` (your fork, `artreadcode/QuantumGraph`), then
      create the private repo under `moth-quantum` and push there with full history.

Review gate: `git status` clean, `git log --oneline -5` shows the four commits, tests green on a fresh
clone of the new repo.

---

## Step 1 — Physics core (plan §3, Phase 1)

Why: the shipping default topology (`ring`) is numerically wrong (§3.1), the entangler has a dead zone
(§3.2), and the coupling-map normaliser has a dedupe bug (`ring(2)` phantom edge).

Files: `microquantumgraph/expectationvalue.py`, `microquantumgraph/microquantumgraph.py`,
`tests/test_microquantumgraph.py`.

- [ ] 1.1 `expectationvalue.py`: dedupe + canonicalise the coupling map
      (`sorted({(min(a,b), max(a,b))})`). Test: `ring(2)` yields 11 channels, not 14.
- [ ] 1.2 `microquantumgraph.py`: split `coupling_map` into `gated` and `tracked`. `gated` must be a
      forest — validate at construction, raise `ValueError` with the offending cycle. `tracked ⊇ gated`
      — validate, raise. Test: star gated under ring tracking raises.
- [ ] 1.3 New ansatz builder (replaces `build_circuit`'s circuit shape):
      `ry(pi/2)` on every qubit → `rzz(phi_e)` per gated edge → nothing else in-circuit.
      `rzz(theta, a, b)` = `cx(a,b); rz(theta,b); cx(a,b)` — already in `_get_gates`'s supported set.
      Skip any gate with `|angle| < 1e-6`. Test: zero-angle gate emitted vs skipped, 0.891 vs 0.000.
- [ ] 1.4 `theta_for(c)`: `asin(sqrt(sqrt(1 + 3c²) − 1))`, clamp `c` to `[0, 1]`.
      Test: requested `c` vs measured correlation, `c ∈ {0, 0.1, …, 1.0}`, error < 1e-12.
- [ ] 1.5 Analytic frame lift: `rz(alpha); ry(gamma)` applied as `R = Ry(gamma) @ Rz(alpha)` to the
      Bloch vector and `M → R_a M R_bᵀ`, in plain Python, after the engine runs.
      Test: 20 random frame pairs vs. running the frames in-circuit, discrepancy < 1e-12.
- [ ] 1.6 Fidelity suite against the statevector oracle already in the test file: chain/star/forest
      exact < 1e-12 at n = 4, 5, 8; ring and full error > 0.1 (regression — they must stay rejected);
      tilt ≠ π/2 error > 0.1 (the invariant must fail loudly if someone removes it); depth-2 error > 0.5.
- [ ] 1.7 Remove `ring` and `full` from the topology helpers; add `star`, `chain`, `forest`.
- [ ] 1.8 Demote `update_tomography(incremental=True)`: keep it, document the collapse (§3.3), mark it
      "not for realtime use" in the docstring.

Review gate: all of the above as tests, all green; old 16 tests still green.

---

## Step 2 — Layer 2 API (plan §4, Phase 4)

Why: this is the product. Raw Pauli values are the escape hatch, not the interface.

Files: new `microquantumgraph/engine.py`, `tests/test_engine.py`.

- [ ] 2.1 `GraphEngine(spec)` where `spec` = `GraphSpec.star(n, hub=0)` / `.chain(n)` / `.forest(...)`.
- [ ] 2.2 `Controls`: `coupling: dict[edge, float 0..1]`, `azimuth: list[float]`, `polar: list[float]`.
      Tilt is fixed at π/2 and not a field.
- [ ] 2.3 `engine.step(controls) → Readout` with per node `presence` (= purity), `tilt` (= ⟨Z⟩),
      `hue` (= atan2(⟨Y⟩, ⟨X⟩)); per edge `bond` (= `get_correlation`), `sync` (= ⟨ZZ⟩).
- [ ] 2.4 `engine.raw()` → Layer 1 (Bloch + 9 Paulis per tracked pair).
- [ ] 2.5 Gestures: `couple(a, b, amount)` → sets `coupling[(a,b)] = theta_for(amount)`;
      `preset(edge, name)` for `'classical' | 'phase' | 'lead' | 'follow'` → sets the two endpoint
      frames; `release()` → decays every coupling toward 0 over N frames;
      `focus(new_hub)` → **sequential** crossfade: outgoing edges to 0 first, then incoming from 0.
      Test: the gated graph is a forest at every intermediate frame of `focus()`.
- [ ] 2.6 `engine.channels()` → stable, ordered channel-name list (qubits first, then edges, sorted).
      Test: same graph in a different edge spelling gives an identical list.

Review gate: a test drives a 5-node star using only `couple`/`preset`/`focus` and Layer 2 reads;
monogamy asserted (one leaf at 0.9, others at 0 → that leaf's hub-bond > 0.7, the others < 0.01;
all at 0.9 → all four within 1e-9 of each other).

---

## Step 3 — Audio mapping and temporal behaviour (plan Phase 3)

Why: `rms`-only input must never be a dead zone, and smoothing must happen before the state is built.

Files: new `microquantumgraph/mapping.py`, `tests/test_mapping.py`. (Show-specific knowledge lives
only here.)

- [ ] 3.1 `agreement(bands_a, bands_b)` = `cos_similarity × sqrt(geometric_mean_level)`, both in
      `[0, 1]`. Test: identical non-zero bands → high; one side silent → exactly 0.
- [ ] 3.2 Per-qubit frame from timbre: `alpha = π · (high − low)/(high + low + ε)`,
      `gamma = π · level`. Test: any `alpha`/`gamma` leaves `bond` unchanged (basis-only).
- [ ] 3.3 Angle-domain smoothing: asymmetric one-pole (attack ~60–80 ms, release ~400–600 ms) + slew
      limit. Azimuth smoothed on the circle (EMA of `cos`/`sin`, recover with `atan2`).
      Test: a state with constant true purity keeps purity constant to 1e-9 under smoothing.
- [ ] 3.4 Regression test encoding why `_blend` is removed: output-domain EMA on the same state drives
      purity below 0.05.
- [ ] 3.5 Monotonicity + range tests: each edge monotone in its own driver (zero decreasing steps over
      40 random settings of the others); correlation span > 0.9; `sync` reaches beyond ±0.8; silence
      gives exactly 0.

Review gate: tests green; run the current `build_circuit` against 3.5 and confirm it fails (it should
— that is the point).

---

## Step 4 — Package and relocate (plan Phase 5)

Why: `micromoth.py` is not in this repo, `pyproject.toml` forbids TD's Python 3.11, and `td/` carries a
`sys.path` hack.

- [ ] 4.1 Vendor `micromoth.py` → `microquantumgraph/_vendor/micromoth.py`, Apache-2.0 header intact.
      Import as `try: import micromoth / except ImportError: from ._vendor import micromoth`.
- [ ] 4.2 `pyproject.toml`: `requires-python = ">=3.9"`; `[tool.setuptools.packages.find]`;
      distribution name `microquantumgraph`; `dependencies = []`; qiskit stack behind
      `[project.optional-dependencies] full`. Test: `pip install .` into a bare 3.11 venv, import works
      with zero third-party packages.
- [ ] 4.3 Move `QuantumAudioGraph` out of `td/qg_td.py` into `engine.py` (or delete it if `GraphEngine`
      covers it). Delete the `sys.path` block and the `try/except ImportError` in
      `microquantumgraph.py`. Deploy = copy the package directory whole; add its parent to TD's path.
- [ ] 4.4 `td/quantum_callbacks.py`: topology menu `star | chain | forest`; new `Maxqubits` par;
      output is fixed-width sized by `Maxqubits` (absent qubits/edges emit 0.0); add `qg_ok`, `qg_age`,
      `qg_n` channels; rate-limit the error-path `debug()`; hold-last-frame bounded at ~2 s then decay.
- [ ] 4.5 `td/README.md`: fix the merge order (`select3, select2, select4, select5`) and the `filter7`
      bypass claim.

Review gate: tests green under TD's own interpreter
(`/Applications/TouchDesigner.app/Contents/Frameworks/Python.framework/Versions/3.11/bin/python3.11`).

---

## Step 5 — TD mock, written recipe (plan Phase 6)

Why: the junior never built it. A written recipe survives TD build-version skew; a `.toe` does not.

File: `td/MOCK_BUILD.md`.

- [ ] 5.1 Source switch (live CoreAudio / file / synthetic); driver + device set at `onStart` by
      platform, never hardcoded (ASIO is Windows-only).
- [ ] 5.2 4-channel mic simulation from one input: band filters (LP 250 / BP 600 / BP 1800 / HP 4000)
      + delays (5 / 11 / 17 / 23 ms).
- [ ] 5.3 `null16` contract reproduced exactly: channels `mid, mid1, mid2, mid3`, merge order
      `select3, select2, select4, select5`.
- [ ] 5.4 `Micgain` as a parameter (default 15.6, expect to trim ~20 dB for a laptop mic).
- [ ] 5.5 Scenario table (`silent, solo1, pair12, all_unison, antiphase, drift`), injected at feature
      level so runs are reproducible.
- [ ] 5.6 Readout: per-node Bloch dot, per-edge `bond` bar, and a naive `min/max` correlation beside it
      as the control. A/B switch between audio-direct and quantum-driven.

Review gate (in TD, on the Mac): `pair12` raises hub–leaf1 and hub–leaf2, others flat; `all_unison`
raises all; `antiphase` stays near zero despite full level; `solo1` moves only its own node's
`presence`. If `antiphase` does not stay near zero, stop — the mapping is wrong.

---

## Step 6 — Fix the remote client (plan Phase 8)

Why: `td/qg_api_callbacks.py` targets the real, documented `graph-v1` engine correctly but has two bugs
and has never run.

- [ ] 6.1 `mod('quantum_api_callbacks')` → `mod('qg_api_callbacks')` (or rename the file).
- [ ] 6.2 Module-global `STATE` → per-operator storage.
- [ ] 6.3 One integration test against `graph-v1` in EMU mode with a fixed `seed`
      (needs a `moth_…` API key; skip the test if the key is absent).

Review gate: the test round-trips `process → status → result` and lands `tomography.bloch` into the
Table DAT contract.

---

## Step 7 — Performance core (plan §2, Phase 2)

Why: 85% of per-frame cost is string-keyed dict overhead. Not blocking (0.69 ms vs. 16.67 ms budget),
so it comes after correctness.

- [ ] 7.1 `ExpectationValueNP`: flat `float64` array; index tables for `_rotate` pairs and `cz`
      permutations precomputed once per topology; per-frame work is gather/scatter.
- [ ] 7.2 Backend selection: numpy if importable, else pure-Python. Same interface.
- [ ] 7.3 Agreement test: both backends within 1e-12 on the full fidelity suite.
- [ ] 7.4 Benchmark, recorded in the repo: p99 at n = 4/8/16/24 for both backends. Compare against the
      projected 40–50×; write down the actual number.

Review gate: both backends agree; measured (not projected) numbers committed.

---

## Step 8 — Hosted service (plan §8, Phase 7) — deferred

Do not start until Steps 0–7 are done and a second consumer of the microengine exists. Design is in
the plan (§8, "Service design"). Host pattern: `mothbackend` (own chart, cluster-internal). For the
show: local process on the venue LAN, not the cluster.
