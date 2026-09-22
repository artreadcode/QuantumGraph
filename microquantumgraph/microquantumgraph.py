# The micro-version of the original QuantumGraph.py.

from math import pi

try:                                  # installed as a package
    from .expectationvalue import ExpectationValue
except ImportError:                   # When the project is on the testing stage on TD
    from expectationvalue import ExpectationValue


class MicroQuantumGraph():

    def __init__(self, quantumcircuit, coupling_map=None, k=2):
        '''
        Args:
            quantumcircuit: a micromoth.QuantumCircuit.
            coupling_map: list of [j,k] pairs -- the graph edges. Only these
                pairs get an exact two-qubit entry; everything else falls back
                to the product of the two marginals. Defaults to fully
                connected, which is O(n^2) Pauli terms and gets slow fast.
            k: Pauli weight tracked by the model. 2 is the whole point.
        '''
        self.qc = quantumcircuit
        self.num_qubits = quantumcircuit.num_qubits
        self.backend = ExpectationValue(self.num_qubits, k=k,
                                        coupling_map=coupling_map)
        self.coupling_map = self.backend.coupling_map
        self.observables = self.get_observables()
        self._applied = 0
        self.update_tomography()

    def get_observables(self):
        '''Every Pauli the model can answer for: 3 per qubit, 9 per edge.'''
        observables = []
        for qubit0 in range(self.num_qubits):
            for pauli in ['X', 'Y', 'Z']:
                full_pauli = ['I'] * self.num_qubits
                full_pauli[qubit0] = pauli
                observables.append(''.join(full_pauli))
        for qubit0, qubit1 in self.coupling_map:
            for pauli in ['XX', 'XY', 'XZ', 'YX', 'YY', 'YZ', 'ZX', 'ZY', 'ZZ']:
                full_pauli = ['I'] * self.num_qubits
                full_pauli[qubit0] = pauli[0]
                full_pauli[qubit1] = pauli[1]
                observables.append(''.join(full_pauli))
        return observables

    def update_tomography(self, incremental=False):
        '''
        Folds self.qc into the tracked state.

        incremental=True applies only the gates appended since the last call,
        which is what makes a per-frame update cost the new gates instead of
        the whole history. It is only correct if you append to self.qc and
        never rewrite it.
        '''
        if incremental and 0 < self._applied <= len(self.qc.data):
            tail = _tail_circuit(self.qc, self._applied)
            self.backend.apply_circuit(tail, reinitialize=False)
        else:
            self.backend.apply_circuit(self.qc, reinitialize=True)
        self._applied = len(self.qc.data)
        self.pauli_decomp = self.backend.pauli_decomp
        return self.backend

    def get_bloch(self, qubit):
        '''<X>, <Y>, <Z> for one qubit.'''
        expectation = {}
        full_pauli = ['I'] * self.num_qubits
        for pauli in ['X', 'Y', 'Z']:
            full_pauli[qubit] = pauli
            expectation[pauli] = self.pauli_decomp[''.join(full_pauli)]
        return expectation

    def get_relationship(self, qubit0, qubit1):
        '''The nine two-qubit Pauli expectation values for a pair.'''
        relationship = {}
        bloch0 = bloch1 = None
        full_pauli = ['I'] * self.num_qubits
        for pauli in ['XX', 'XY', 'XZ', 'YX', 'YY', 'YZ', 'ZX', 'ZY', 'ZZ']:
            full_pauli[qubit0] = pauli[0]
            full_pauli[qubit1] = pauli[1]
            key = ''.join(full_pauli)
            if key in self.pauli_decomp:
                relationship[pauli] = self.pauli_decomp[key]
            else:
                # Not an edge of the graph: the model never tracked it, so the
                # best available answer is the uncorrelated one.
                if bloch0 is None:
                    bloch0 = self.get_bloch(qubit0)
                    bloch1 = self.get_bloch(qubit1)
                relationship[pauli] = bloch0[pauli[0]] * bloch1[pauli[1]]
            full_pauli[qubit0] = 'I'
            full_pauli[qubit1] = 'I'
        return relationship

    # --- derived scalars, the things a visual actually wants ----------------

    def get_purity(self, qubit):
        '''
        Bloch vector length, 0..1. 1 = a definite pure direction, 0 = maximally
        mixed, which for this model means the qubit's information has leaked
        into its correlations with neighbours.
        '''
        b = self.get_bloch(qubit)
        return (b['X'] ** 2 + b['Y'] ** 2 + b['Z'] ** 2) ** 0.5

    def get_correlation(self, qubit0, qubit1):
        '''
        How much the pair knows about each other beyond what each knows alone:
        0 = independent, 1 = maximally correlated. This is the scalar to drive
        a visual with -- it is the one number that cannot be reconstructed
        from the two mic levels separately.
        '''
        rel = self.get_relationship(qubit0, qubit1)
        b0 = self.get_bloch(qubit0)
        b1 = self.get_bloch(qubit1)
        total = 0.0
        for pauli, value in rel.items():
            connected = value - b0[pauli[0]] * b1[pauli[1]]
            total += connected ** 2
        return min(1.0, (total / 3.0) ** 0.5)


def _tail_circuit(qc, start):
    '''A circuit holding only qc.data[start:], for incremental updates.'''
    tail = qc.__class__(qc.num_qubits, qc.num_clbits)
    tail.data = list(qc.data[start:])
    return tail


# --- audio -> circuit ------------------------------------------------------

def build_circuit(features, num_qubits, coupling_map, angle_scale=0.5,
                  QuantumCircuit=None):
    '''
    Maps audio features onto a micromoth circuit.

    Args:
        features: either one dict, or a list of dicts -- one per qubit, cycled
            if shorter than num_qubits. Keys 'low', 'mid', 'high', 'rms', all
            expected in 0..1.
              low, mid, high -> single-qubit rotation angles
              rms            -> how hard the pair is entangled, continuously,
                                so silence really does give an uncorrelated
                                state instead of a fully entangled one
        num_qubits: graph nodes.
        coupling_map: list of [j,k] edges to entangle.
        angle_scale: fraction of pi a feature of 1.0 rotates by. 0.5 is the
            default because a full pi is not monotonic in loudness: rx(pi)
            takes a qubit back to a definite state, so correlation peaks
            mid-level and collapses to zero at full level. Measured mean edge
            correlation on a 4-qubit ring, uniform level 0.0 -> 1.0:
                pi   : .00 .02 .09 .18 .18 .11 .21 .28 .25 .09 .00
                pi/2 : .00 .01 .03 .10 .19 .29 .34 .34 .34 .30 .25
            Loud should not mean nothing happens. Pass 1.0 to get the old
            behaviour back.
        QuantumCircuit: injected for testing; defaults to micromoth's.

    Returns a micromoth QuantumCircuit.
    '''
    if QuantumCircuit is None:
        from micromoth import QuantumCircuit

    if isinstance(features, dict):
        features = [features]

    def f(i):
        return features[i % len(features)]

    qc = QuantumCircuit(num_qubits)

    turn = pi * angle_scale

    for i in range(num_qubits):
        qc.rx(turn * f(i).get('mid', 0.0), i)
        qc.rz(turn * f(i).get('high', 0.0), i)

    # A bare cx is all-or-nothing. crx(theta) dials the entanglement with the
    # level, so the graph breathes rather than switching.
    for j, k in coupling_map:
        rms = 0.5 * (f(j).get('rms', 0.0) + f(k).get('rms', 0.0))
        if rms > 0.0:
            qc.crx(pi * rms, j, k)

    for i in range(num_qubits):
        qc.rx(turn * f(i).get('low', 0.0), i)

    return qc
