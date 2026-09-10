from micromoth import QuantumCircuit
from quantumgraph.ExpectationValue import ExpectationValue

class MicroQuantumGraph():
    def __init__(self, quantumcircuit):
        self.qc = quantumcircuit # micromoth.QuantumCircuit object
        self.observables = self.get_observables()
        self.backend = self.update_tomography()
        # self.update_tomography()
        # All these three are needed in MicroQuantumGraph.
    
    def get_observables(self):
        observables = []
        for qubit0 in range(self.qc.num_qubits):
            for pauli in ['X', 'Y', 'Z']:
                full_pauli = ['I'] * self.qc.num_qubits
                full_pauli[qubit0] = pauli
                obs = ''.join(full_pauli)
                observables.append(obs)
            
            for qubit1 in range(qubit0+1, self.qc.num_qubits):
                full_pauli = ['I'] * self.qc.num_qubits
                for pauli in ['XX', 'XY', 'XZ', 'YX', 'YY', 'YZ', 'ZX', 'ZY', 'ZZ']:
                    full_pauli[qubit0] = pauli[0]
                    full_pauli[qubit1] = pauli[1]
                    obs = ''.join(full_pauli)
                    observables.append(obs)
        return observables
    
    def update_tomography(self):
        # from the original, this only uses ExpectationValue.
        backend = ExpectationValue(self.qc.num_qubits)
        backend.apply_circuit(self.qc)
        self.pauli_decomp = backend.pauli_decomp
        return backend
    
    def get_bloch(self, qubit):
        ''' Returns per-qubit values '''
        
        expectation = {}
        full_pauli = ['I'] * self.qc.num_qubits
        for pauli in ['X', 'Y', 'Z']:
            full_pauli[qubit] = pauli
            expectation[pauli] = self.pauli_decomp[''.join(full_pauli)]
        return expectation

    def get_relationship(self, qubit0, qubit1):
        ''' Returns per-pair values '''
        relationship = []
        
        return relationship


# This totally new module function will define
# how audio values will create and modify quantum circuit
def build_circuit(features, num_qubits, pairs):
    ''' 
    Map audio features to a micromoth circuit.
    
    Attributes:
    - features: dict with 'low', 'mid', 'high', 'rms', each 0..1.
        - low, mid, high: per-qubit rotation angles (More entangling gates richer per-pair values but per-qubit will be less impactful.)
        - rms: Overall level so use it as a gate on entanglement so silence gives a calm state.
    - num_qubits: number of qubits (graph nodes)
    - pairs: list of [j, k] qubit pairs to entangle.
    
    Returns a MicroMoth QuantumCircuit.
    '''
    qc = QuantumCircuit(num_qubits)
    # TODO
    return qc
        