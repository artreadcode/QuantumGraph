# QuantumGraph in TouchDesigner

Two lanes, different jobs. Do not mix them up.

| | **Local lane** (`qg_td.py`) | **API lane** (`qg_api_callbacks.py`) |
|---|---|---|
| Latency | 0.8–2.6 ms, per frame | seconds to hours (job pipeline, IBM queue) |
| Runs | inside TD's own Python 3.11 | on `api.mothquantum.com` |
| Needs | nothing installed | an API key, network, credits |
| Gives | `get_bloch`, `get_relationship`, correlations | the same **plus** `set_bloch` / `set_relationship`, real QPU counts |
| Use for | every frame of the show | presets, cues, a "this ran on hardware" moment |

The API cannot drive a frame. `graph-v1` is a four-step job (`build → submit →
collect → format`) and the reference client polls with `time.sleep(2)`. That is
not a tuning problem, it is the shape of the thing. Anything that has to move
with the music runs locally.

## Install

1. Copy six files into one folder next to the `.toe` — say `python/`:
   `micromoth.py`, `expectationvalue.py`, `microquantumgraph.py`,
   `qg_td.py`, `quantum_callbacks.py`, `qg_api_callbacks.py`.
2. TD → *Edit → Preferences → Python 64-bit Module Path*, or set the project's
   **Search Path** (`/local` → `Python` page) to that folder.
3. `import qg_td` in a Textport. That is the whole install — no pip, no venv,
   no qiskit. Verified against TouchDesigner 2025.33070's own Python 3.11.

## What the show does today

Measured from `UNVEIL DOME INDEVIDUAL RENDER REBUILD.161.toe`, not guessed:

```
audiodevin1  (ASIO "Merging_Audio_Device", 6 ch)
  └─ null9
      ├─ mic1  = chan3 ─→ audioAnalysis1 ─→ select3 ┐
      ├─ mic2  = chan4 ─→ audioAnalysis  ─→ select2 │  each: "mid low high"
      ├─ mic3  = chan5 ─→ audioAnalysis2 ─→ select4 │
      ├─ mic4  = chan6 ─→ audioAnalysis3 ─→ select5 ┘
      └─ SETERO_MIX = chan1 → audioAnalysis4 → select1 → math14 → null19
                                                          └→ Noise_speed_add → speed1 → null3
                                                             (drives every noise TOP's t4d)

  select{2,3,4,5} → math{2,1,16,20}  (chanop "add": low+mid+high → one channel)
                  → math{12,11,17,21} (gain 15.6)
                  → merge1 → filter7 (width 1.48) → null16
                                                     └ channels: mid, mid1, mid2, mid3

  null16 → mic_data_1..4 (Constant CHOPs, const0value = op('null16')['mid'..'mid3'])
         → vox_particles in1..in4
```

Inside `vox_particles`, each mic's single scalar fans out to five Math CHOPs
that remap it into a parameter range, and those drive POPs by expression:

| driven parameter | driver CHOP | remap range |
|---|---|---|
| `noise5.period` | `1_period` | 0.01 → 0.035 |
| `noise5.amp1` | `1_amp` (via `filter1`) | 0.001 → 0.01 |
| `particle1.birthrate` | `1_part_number` | 6000 → 10000 |
| `particle1.speed` | `1_tru_speed` | 0 → 2 |
| `transform7.ty` | `1_up_speed` (via `filter4`) | 0.001 → 0.0005 |

Heads 2–4 repeat this exactly (`L_period2`, `L_amp2`, `l_num_part2`,
`Tru_speed2`, `L_UP_speed2`, …).

**The gap:** every one of those parameters is a function of *one* mic. Four
independent scalars, four independent particle systems. Nothing in the patch
expresses a *relationship between* mics — which is precisely what a quantum
graph is for.

## Where the quantum CHOP goes

Tap the analysis before it collapses to one number per mic, and add a second
signal alongside the existing one. Nothing is removed.

```
select2 ┐
select3 ├─→ merge_analysis (Merge CHOP)  ──→ quantum (Script CHOP)
select4 │      channels:                         ├ q0_x q0_y q0_z q0_purity …
select5 ┘      low  mid  high                    └ e0_1_corr e0_1_zz e0_1_xx …
               low1 mid1 high1
               low2 mid2 high2               (Merge auto-suffixes duplicates —
               low3 mid3 high3                same convention null16 uses)
```

`quantum` is a Script CHOP with `quantum_callbacks.py` as its DAT. Add the
custom pars listed at the top of that file (`Numqubits`, `Topology`,
`Smoothing`, `Active`).

Then rebind, per head *i* coupled to head *j*:

| parameter | today | proposed |
|---|---|---|
| `noise.amp1` | mic *i* level | **unchanged** — local presence stays audio |
| `particle.birthrate` | mic *i* level | **unchanged** |
| `noise.period` | mic *i* level | `op('quantum')['e{i}_{j}_corr']` — correlated heads share texture scale |
| `particle.speed` | mic *i* level | `op('quantum')['q{i}_purity']` — a qubit that has entangled away its own state slows down |
| `transform.ty` | mic *i* level | `op('quantum')['q{i}_z']` — signed, so the rise can reverse |

Keep the existing Math CHOP remaps in place; only the *source* changes. Put a
Math CHOP between `quantum` and each consumer for range and gain — `*_corr`
lands in roughly 0.0–0.5 in practice, not 0–1.

## Build the mockup first

Do not edit the 540 KB show file to find out whether this reads. Build
`quantum_mockup.toe` with just:

`audiofilein1` (or `audiodevin1`) → 4 × `select` → 4 × `audioAnalysis`
→ `merge_analysis` → `quantum` → one copy of the `particle1` / `noise5` /
`transform7` chain lifted from `vox_particles`.

That is ~15 operators and it answers the only question that matters: does an
audience see the difference between four mics that agree and four that do not.
Port it into the show once it does.

## Numbers

Per-frame cost of the local lane, measured in TD's own 3.11 interpreter,
ring topology, one core:

| qubits | edges | mean | p99 |
|---|---|---|---|
| 4 | 4 | 0.74 ms | 0.80 ms |
| 8 | 8 | 1.58 ms | 1.72 ms |
| 12 | 12 | 2.59 ms | 2.72 ms |
| 16 | 16 | 3.63 ms | 3.76 ms |

A 60 fps frame is 16.7 ms.

**Edges cost, not qubits.** The same model, same interpreter, `Topology = full`:

| qubits | edges | mean |
|---|---|---|
| 4 | 6 | 1.87 ms |
| 6 | 15 | 8.59 ms |
| 8 | 28 | 23.98 ms |
| 10 | 45 | 52.07 ms |
| 12 | 66 | 98.89 ms |

Eight fully-connected qubits already misses 60 fps. Set `Topology` to `ring`
or `chain` and stay there; `full` is a debugging option, not a show option.

Two more things not to do per frame:

- `ExpectationValue.get_counts()` — 11 ms for 256 shots on 8 qubits. You do not
  need it: the correlations *are* the signal, sampling them back into
  bitstrings only throws information away.
- Anything on the API lane.

## Known limits

- The model tracks Pauli weight ≤ 2. It is **exact** for those when the
  coupling map is fully connected. On a sparse map, a CZ can rotate a tracked
  Pauli onto an untracked one, and the model infers that term from a product of
  smaller ones. Correlations along graph edges stay meaningful; treat
  `get_relationship` on a non-edge as decoration.
- `get_correlation` is a connected-correlation norm, not concurrence. It is
  0 for a product state and 1 for a Bell pair, which is what a visual needs.
- Response is monotone in level but not linear, and plateaus near the top —
  see the table in `build_circuit`'s docstring. Gain-stage it downstream.
