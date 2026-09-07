from micromoth import QuantumCircuit

class MicroQuantumGraph():
    def __init__(self, quantumcircuit):
        print("Hello world!")
        
        self.qc = quantumcircuit # micromoth.QuantumCircuit object
        self.num_qubits = quantumcircuit.num_qubits
        
        
        
        