'''
Checks MicroQuantumGraph's tracked expectation values against an exact
statevector, computed with micromoth's own simulator.

The ExpectationValue model is exact for weight<=2 Paulis when the coupling map
is fully connected (every CZ flip lands on a Pauli the model is tracking).
On a sparse coupling map it infers untracked terms from products, so these
tests use a full coupling map wherever they assert exactness.

Run:  uv run python -m pytest tests -q      (or just: uv run python tests/test_microquantumgraph.py)
'''

import os
import sys
from math import pi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'microquantumgraph'))

from micromoth import QuantumCircuit, simulate          # noqa: E402
from expectationvalue import ExpectationValue           # noqa: E402
from microquantumgraph import MicroQuantumGraph, build_circuit  # noqa: E402

TOL = 1e-9

_P = {'I': [[1, 0], [0, 1]],
      'X': [[0, 1], [1, 0]],
      'Y': [[0, -1j], [1j, 0]],
      'Z': [[1, 0], [0, -1]]}


def exact(qc, pauli):
    '''<pauli> on the statevector of qc. Index 0 of `pauli` is qubit 0.'''
    sv = [complex(a, b) for a, b in simulate(qc, get='statevector')]
    total = 0j
    for i, amp_i in enumerate(sv):
        if amp_i == 0:
            continue
        amp, j = amp_i, i
        for q, char in enumerate(pauli):
            bit = (j >> q) & 1
            m = _P[char]
            if m[bit][bit] != 0:            # I or Z: diagonal
                amp *= m[bit][bit]
            else:                            # X or Y: flips the bit
                amp *= m[1 - bit][bit]
                j ^= (1 << q)
        total += sv[j].conjugate() * amp
    return total.real


def all_weight2(n):
    out = []
    for q in range(n):
        for p in 'XYZ':
            s = ['I'] * n
            s[q] = p
            out.append(''.join(s))
    for q0 in range(n):
        for q1 in range(q0 + 1, n):
            for p in ['XX', 'XY', 'XZ', 'YX', 'YY', 'YZ', 'ZX', 'ZY', 'ZZ']:
                s = ['I'] * n
                s[q0], s[q1] = p[0], p[1]
                out.append(''.join(s))
    return out


def assert_matches(build, n):
    ev = ExpectationValue(n)            # full coupling map -> exact
    ev.apply_circuit(build())
    for pauli in all_weight2(n):
        got = ev.pauli_decomp[pauli]
        want = exact(build(), pauli)
        assert abs(got - want) < TOL, f'{pauli}: got {got}, want {want}'


# --- gate set ---------------------------------------------------------------

def test_hadamard_maps_z_to_x():
    # The bug this guards: rz(pi/2).ry(pi/2).rz(pi/2) is not H. It leaves the
    # state on +Y, so every X and Y in the output was swapped.
    assert_matches(lambda: _c(2, lambda c: c.h(0)), 2)


def test_bell_state_signs():
    # |Phi+> has <XX>=+1, <YY>=-1, <ZZ>=+1. Getting XX=-1 means H was wrong.
    qc = _c(2, lambda c: (c.h(0), c.cx(0, 1)))
    ev = ExpectationValue(2)
    ev.apply_circuit(qc)
    assert abs(ev.pauli_decomp['XX'] - 1.0) < TOL
    assert abs(ev.pauli_decomp['YY'] + 1.0) < TOL
    assert abs(ev.pauli_decomp['ZZ'] - 1.0) < TOL


def test_rotations():
    assert_matches(lambda: _c(3, lambda c: (c.rx(0.7, 0), c.rz(1.3, 1), c.ry(-0.4, 2))), 3)


def test_cx():
    assert_matches(lambda: _c(3, lambda c: (c.h(0), c.cx(0, 1), c.cx(1, 2))), 3)


def test_crx_is_a_dialable_entangler():
    for theta in [0.0, 0.3, pi / 2, pi]:
        assert_matches(lambda t=theta: _c(2, lambda c: (c.h(0), c.crx(t, 0, 1))), 2)


def test_crx_at_zero_is_identity_and_at_pi_is_cx():
    zero = _graph(_c(2, lambda c: (c.h(0), c.crx(0.0, 0, 1))))
    assert abs(zero.get_correlation(0, 1)) < 1e-9
    full = _graph(_c(2, lambda c: (c.h(0), c.crx(pi, 0, 1))))
    assert abs(full.get_relationship(0, 1)['ZZ'] - 1.0) < TOL


def test_swap():
    assert_matches(lambda: _c(3, lambda c: (c.rx(0.9, 0), c.swap(0, 2))), 3)


# --- coupling map -----------------------------------------------------------

def test_default_coupling_map_has_no_self_edges():
    ev = ExpectationValue(4)
    assert all(j != k for j, k in ev.coupling_map)
    assert ev.coupling_map == [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]
    for q, ns in ev.neighbours.items():
        assert q not in ns
        assert len(ns) == len(set(ns))


def test_sparse_coupling_map_tracks_only_its_edges():
    ring = [[0, 1], [1, 2], [2, 3], [3, 0]]
    g = MicroQuantumGraph(build_circuit({'low': .2, 'mid': .6, 'high': .1, 'rms': .8}, 4, ring),
                          coupling_map=ring)
    assert 'ZIZI' in g.backend.pauli_decomp or 'ZIZI' not in g.backend.pauli_decomp
    assert 'ZZII' in g.backend.pauli_decomp          # edge 0-1, tracked
    assert 'ZIZI' not in g.backend.pauli_decomp      # 0-2 is not an edge
    # ... and asking for it still answers, from the marginals
    assert isinstance(g.get_relationship(0, 2)['ZZ'], float)


def test_pairs_alias_still_works():
    ev = ExpectationValue(3, pairs=[[0, 1], [1, 2]])
    assert ev.coupling_map == [[0, 1], [1, 2]]
    assert ev.pairs == ev.coupling_map


# --- incremental updates ----------------------------------------------------

def test_incremental_update_matches_full_replay():
    ring = [[0, 1], [1, 2], [2, 3], [3, 0]]
    feats = {'low': .3, 'mid': .6, 'high': .2, 'rms': .7}
    g = MicroQuantumGraph(build_circuit(feats, 4, ring), coupling_map=ring)
    for _ in range(3):
        for inst in build_circuit(feats, 4, ring).data:
            g.qc.data.append(inst)
        g.update_tomography(incremental=True)
    incremental = dict(g.backend.pauli_decomp)

    g2 = MicroQuantumGraph(g.qc, coupling_map=ring)   # replay from scratch
    for pauli, value in incremental.items():
        assert abs(value - g2.backend.pauli_decomp[pauli]) < 1e-9, pauli


# --- derived scalars --------------------------------------------------------

def test_correlation_is_zero_for_a_product_state():
    g = _graph(_c(3, lambda c: (c.rx(0.5, 0), c.rx(1.1, 1), c.rx(0.2, 2))))
    for a, b in [(0, 1), (1, 2), (0, 2)]:
        assert g.get_correlation(a, b) < 1e-9


def test_correlation_is_one_for_a_bell_pair():
    g = _graph(_c(2, lambda c: (c.h(0), c.cx(0, 1))))
    assert abs(g.get_correlation(0, 1) - 1.0) < 1e-9


def test_purity_drops_when_a_qubit_entangles():
    assert abs(_graph(_c(2, lambda c: c.rx(0.4, 0))).get_purity(0) - 1.0) < 1e-9
    assert _graph(_c(2, lambda c: (c.h(0), c.cx(0, 1)))).get_purity(0) < 1e-9


def test_silence_gives_an_uncorrelated_state():
    ring = [[0, 1], [1, 2], [2, 3], [3, 0]]
    silent = {'low': 0.0, 'mid': 0.0, 'high': 0.0, 'rms': 0.0}
    g = MicroQuantumGraph(build_circuit(silent, 4, ring), coupling_map=ring)
    for a, b in ring:
        assert g.get_correlation(a, b) < 1e-9


def test_build_circuit_accepts_per_qubit_features():
    ring = [[0, 1], [1, 2], [2, 3], [3, 0]]
    feats = [{'low': .1 * i, 'mid': .2 * i, 'high': .05 * i, 'rms': .5} for i in range(4)]
    g = MicroQuantumGraph(build_circuit(feats, 4, ring), coupling_map=ring)
    blochs = [tuple(round(v, 6) for v in g.get_bloch(q).values()) for q in range(4)]
    assert len(set(blochs)) == 4, 'each qubit should follow its own mic'


# --- helpers ----------------------------------------------------------------

def _c(n, apply):
    qc = QuantumCircuit(n)
    apply(qc)
    return qc


def _graph(qc):
    return MicroQuantumGraph(qc)


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc}')
    print(f'\n{failures} failure(s)')
    sys.exit(1 if failures else 0)
