'''
QuantumGraph for TouchDesigner -- the per-frame engine.

Pure stdlib plus `micromoth` and `microquantumgraph`. No qiskit, no scipy,
nothing to pip install into TouchDesigner's Python. Drop this folder next to
the .toe, add it to the project's Search Path, and `import qg_td`.

Contract:
    engine = QuantumAudioGraph(num_qubits=4, coupling_map=[[0,1],[1,2],[2,3],[3,0]])
    values = engine.step({'low': [...], 'mid': [...], 'high': [...]})
    # values is a flat {channel_name: float}

Cost, measured on this machine (CPython 3.12, one core):
    4 qubits  / 4 edges  ->  0.36 ms/frame
    8 qubits  / 8 edges  ->  0.78 ms/frame
    12 qubits / 12 edges ->  1.26 ms/frame
    8 qubits  / 16 edges ->  3.65 ms/frame
A 60 fps frame is 16.7 ms, so this fits with room to spare *as long as the
coupling map stays sparse*. Fully connected at 12 qubits is 50 ms -- 20 fps.
Edges, not qubits, are what costs.
'''

import os
import sys

# Works both from the repo (library one level up) and from a deploy folder
# where micromoth.py / expectationvalue.py / microquantumgraph.py sit right
# here next to this file.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (_HERE, os.path.join(_HERE, '..', 'microquantumgraph')):
    _candidate = os.path.abspath(_candidate)
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from microquantumgraph import MicroQuantumGraph, build_circuit   # noqa: E402


def ring(n):
    '''The cheap default: each node coupled to the next, closing the loop.'''
    return [[i, (i + 1) % n] for i in range(n)]


class QuantumAudioGraph:
    '''
    Holds one graph and re-prepares it every frame from the current audio
    features. Rebuilding from scratch each frame (rather than appending) is
    deliberate: the state should track the audio now, not accumulate the whole
    history of the show.
    '''

    def __init__(self, num_qubits=4, coupling_map=None, smoothing=0.0):
        self.num_qubits = num_qubits
        self.coupling_map = coupling_map or ring(num_qubits)
        self.smoothing = smoothing          # 0 = none, ->1 = heavier lag
        self.graph = None
        self.values = {}
        self._last_error = None

    # -- the per-frame call --------------------------------------------------

    def step(self, features):
        '''
        Args:
            features: {'low': [..], 'mid': [..], 'high': [..], 'rms': [..]},
                each a list of per-mic values in 0..1. Lists shorter than
                num_qubits are cycled, so 4 mics can drive 8 qubits.
        Returns:
            {channel_name: float}. On an internal error the previous frame's
            values are returned unchanged and `last_error` is set -- a dropped
            quantum frame must never drop a render frame.
        '''
        try:
            per_qubit = self._per_qubit(features)
            circuit = build_circuit(per_qubit, self.num_qubits, self.coupling_map)
            self.graph = MicroQuantumGraph(circuit, coupling_map=self.coupling_map)
            self._blend(self._read())
            self._last_error = None
        except Exception as exc:                       # noqa: BLE001
            self._last_error = repr(exc)
        return self.values

    @property
    def last_error(self):
        return self._last_error

    @property
    def channel_names(self):
        '''Stable, ordered -- a Script CHOP needs the same channels every cook.'''
        names = []
        for q in range(self.num_qubits):
            names += [f'q{q}_x', f'q{q}_y', f'q{q}_z', f'q{q}_purity']
        for a, b in self.coupling_map:
            names += [f'e{a}_{b}_corr', f'e{a}_{b}_zz', f'e{a}_{b}_xx']
        return names

    # -- internals -----------------------------------------------------------

    def _per_qubit(self, features):
        out = []
        for q in range(self.num_qubits):
            entry = {}
            for band in ('low', 'mid', 'high', 'rms'):
                series = features.get(band)
                if not series:
                    entry[band] = 0.0
                else:
                    entry[band] = _clamp(series[q % len(series)])
            if not features.get('rms'):
                # No explicit level channel: the band energy is the level.
                entry['rms'] = _clamp(max(entry['low'], entry['mid'], entry['high']))
            out.append(entry)
        return out

    def _read(self):
        g, out = self.graph, {}
        for q in range(self.num_qubits):
            bloch = g.get_bloch(q)
            out[f'q{q}_x'] = bloch['X']
            out[f'q{q}_y'] = bloch['Y']
            out[f'q{q}_z'] = bloch['Z']
            out[f'q{q}_purity'] = g.get_purity(q)
        for a, b in self.coupling_map:
            rel = g.get_relationship(a, b)
            out[f'e{a}_{b}_corr'] = g.get_correlation(a, b)
            out[f'e{a}_{b}_zz'] = rel['ZZ']
            out[f'e{a}_{b}_xx'] = rel['XX']
        return out

    def _blend(self, fresh):
        s = self.smoothing
        if not self.values or s <= 0.0:
            self.values = fresh
            return
        for key, value in fresh.items():
            self.values[key] = self.values.get(key, value) * s + value * (1.0 - s)


def _clamp(value, lo=0.0, hi=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return lo
    if value != value:              # NaN: a dead mic channel should read silent
        return lo
    return lo if value < lo else (hi if value > hi else value)


# -- reading the show's audioAnalysis components ----------------------------

def features_from_chop(chop, num_mics=4):
    '''
    Pulls {'low': [...], 'mid': [...], 'high': [...]} out of a CHOP holding the
    merged outputs of several audioAnalysis containers.

    TouchDesigner's Merge CHOP suffixes duplicate channel names, so merging
    four audioAnalysis outputs that each carry `low mid high` gives
    `low mid high low1 mid1 high1 low2 ...` -- the same convention the show's
    own `null16` already uses for `mid mid1 mid2 mid3`.
    '''
    features = {}
    for band in ('low', 'mid', 'high'):
        series = []
        for i in range(num_mics):
            name = band if i == 0 else f'{band}{i}'
            channel = chop.chan(name) if chop is not None else None
            series.append(float(channel[0]) if channel is not None else 0.0)
        features[band] = series
    return features
