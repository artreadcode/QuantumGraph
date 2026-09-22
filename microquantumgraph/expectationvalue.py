# The micro-version of the original ExpectationValue.py of original QuantumGraph.py
from math import cos, sin, pi
import itertools, copy
import math
import random

class ExpectationValue():
    
    def __init__(self, n, k=2, coupling_map=None, pairs=None):

        self.n = n
        self.k = k

        coupling_map = coupling_map if coupling_map is not None else pairs

        if coupling_map: # This one is for MicroMoth because it uses 'coupling_map' rather than 'pairs'.
            self.coupling_map = [[min(j, k_), max(j, k_)] for j, k_ in coupling_map
                                 if j != k_]
        else:
            self.coupling_map = [[i, j] for i in range(n) for j in range(i + 1, n)]

        self.neighbours = self._get_neighbours()

        self.paths = [[j] for j in range(self.n)]
        for _ in range(self.k - 1):
            new_paths = []
            for path in self.paths:
                q0 = path[-1]
                for q1 in self.neighbours[q0]:
                    if q1 not in path:
                        new_path = copy.copy(path)
                        new_path.append(q1)
                        new_paths.append(new_path)
            self.paths = new_paths

        self.initialize_decomp()

    # `pairs` kept as a read-only alias so older call sites keep working.
    @property
    def pairs(self):
        return self.coupling_map

    def initialize_decomp(self):
        '''Resets the tracked state to |0...0>.'''
        paulis = ['I', 'X', 'Y', 'Z']

        self.pauli_decomp = {}
        for path in self.paths:
            for pauli_k in itertools.product(*(paulis for _ in range(self.k))):
                pauli_n = ['I'] * self.n
                for j, q in enumerate(path):
                    pauli_n[q] = pauli_k[j]
                self.pauli_decomp[''.join(pauli_n)] = float(
                    'X' not in pauli_k and 'Y' not in pauli_k)

        self._supported_by = [{p: [] for p in ['I', 'X', 'Y', 'Z']}
                              for _ in range(self.n)]
        for pauli_n in self.pauli_decomp:
            for q in range(self.n):
                self._supported_by[q][pauli_n[q]].append(pauli_n)

    def _get_neighbours(self):
        neighbours = {j: [] for j in range(self.n)}
        for [j, k] in self.coupling_map:
            if k not in neighbours[j]:
                neighbours[j].append(k)
            if j not in neighbours[k]:
                neighbours[k].append(j)
        return neighbours
    
    def _get_gates(self,qc):
        '''
        Turns a circuit into a list of tuples describing rx, ry, rz and cz gates.
        Replaced Qiskit Transpile from the original.
        '''

        gates = []
        # H = U3(pi/2, 0, pi), which the original applies as rz(lam), ry(the),
        # rz(phi) -- i.e. rz(pi) then ry(pi/2). The earlier rz(pi/2).ry(pi/2).
        # rz(pi/2) is a different gate and swaps X with Y in every result.
        def h(q):
            gates.append(('rz', pi, q))
            gates.append(('ry', pi/2, q))

        def cx(s, t):
            h(t); gates.append(('cz', s, t)); h(t)
            
        for gate in qc.data:
            name = gate[0]
            if name == 'rx':
                gates.append(('rx', float(gate[1]), gate[2]))
            elif name == 'rz':
                gates.append(('rz', float(gate[1]), gate[2]))
            elif name == 'x':
                gates.append(('rx', pi, gate[1]))
            elif name == 'h':
                h(gate[1])
            elif name == 'cx':
                s, t = gate[1], gate[2]
                cx(s, t)
            elif name == 'crx':
                # Qiskit's CRX definition, written in the gate set this model
                # tracks exactly. A dialable entangler -- identity at theta=0,
                # cx at theta=pi -- so audio level can fade a graph edge in and
                # out instead of switching it.
                theta, s, t = float(gate[1]), gate[2], gate[3]
                gates.append(('rz', pi/2, t))
                cx(s, t)
                gates.append(('ry', -theta/2, t))
                cx(s, t)
                gates.append(('ry', theta/2, t))
                gates.append(('rz', -pi/2, t))
            elif name == 'swap':
                s, t = gate[1], gate[2]
                cx(s, t); cx(t, s); cx(s, t)
            elif name in ('init', 'm'):
                continue # ignore because it's useless here
            else:
                print(name+' not supported.')     

        return gates
        
    def _rotate(self,q,pp0,pp1,theta):
        e0,e1 = self.pauli_decomp[pp0],self.pauli_decomp[pp1]
        self.pauli_decomp[pp0] = cos(theta)*e0 + sin(theta)*e1
        self.pauli_decomp[pp1] = -sin(theta)*e0 + cos(theta)*e1
    
    def _change_char(self,string,char,index):
        list_string = list(string)
        list_string[index] = char
        return ''.join(list_string)
    
    def apply_circuit(self, qc, verbose=False, reinitialize=True):
        '''
        Applies `qc` to the tracked state.

        Args:
            reinitialize: reset to |0...0> first (default). Pass False to fold
                `qc` onto the state already tracked -- that is what makes a
                per-frame update cost only the new gates.
        '''
        if reinitialize:
            self.initialize_decomp()

        gates = self._get_gates(qc)
        
        flips = {'XI':'XZ',
                 'YI':'YZ',
                 'IX':'ZX',
                 'XX':'YY',
                 'YX':'XY',
                 'ZX':'IX',
                 'IY':'ZY',
                 'XY':'YX',
                 'YY':'XX',
                 'ZY':'IY',
                 'XZ':'XI',
                 'YZ':'YI'}
                
        for gate in gates:
            
            if verbose:
                print()
                print(gate)
            
            if gate[0]!='cz':
                
                # unpack gate
                rotation,theta,q = gate
                
                # determine which paulis it will affect
                if rotation=='rx':
                    p0,p1 = 'Z','Y'
                if rotation=='ry':
                    p0,p1 = 'X','Z'
                if rotation=='rz':
                    p0,p1 = 'Y','X'

                for pp0 in self._supported_by[q][p0]:
                    pp1 = pp0[:q] + p1 + pp0[q+1::]
                    self._rotate(q,pp0,pp1,theta)
                    
                    if verbose:
                        if abs(self.pauli_decomp[pp0])>0.01 or abs(self.pauli_decomp[pp1])>0.01:
                            print('Rotate',pp0,'and',pp1)
                    
            else:
                
                decomp_diff = {}
                
                # unpack gate
                q0,q1 = gate[1],gate[2]
                                
                # loop through all the possible paulis on q0
                for p0_0 in ['I','X','Y','Z']: 
                    # loop through all n-qubit paulis that contain it
                    for pp0 in self._supported_by[q0][p0_0]:
                        
                        # get the 2-qubit pauli on q0 and q1
                        p0 = p0_0 + pp0[q1]
                        
                        if p0 in flips:
                            # get the 2-qubit pauli that cz flips this to
                            p1 = flips[p0]
                            # construct the corresponding n-qubit paulis
                            pp1 = self._change_char(pp0,p1[0],q0)
                            pp1 = self._change_char(pp1,p1[1],q1)

                            # if it is in pauli_decomp, flip them
                            if pp1 in self.pauli_decomp:                               
                                if verbose:
                                    if abs(self.pauli_decomp[pp0])>0.01 or abs(self.pauli_decomp[pp1])>0.01:
                                        if pp0 not in decomp_diff:
                                            print('Swap',pp0,'with',pp1)
                                decomp_diff[pp0] = self.pauli_decomp[pp1] * (-1)**(p0 in ['XY','YX'])
                                decomp_diff[pp1] = self.pauli_decomp[pp0] * (-1)**(p1 in ['XY','YX'])
                                
                            # otherwise infer a value and use that
                            else:
                                # determine the qubits on which pp1 has support
                                support = []
                                for j,char in enumerate(pp1):
                                    if char!='I':
                                        support.append(j)
                                
                                # get all possible bipartitions
                                bipartitions = []
                                for partition in itertools.product(*(range(2) for _ in range(len(support)))):
                                    parts = [[],[]]
                                    if 0 in partition and 1 in partition:
                                        for j,s in enumerate(support):
                                            parts[partition[j]].append(s)
                                        bipartitions.append(parts)
                                
                                # make a list of pairs of paulis products that combine to pp1
                                partitioned_pp1s = []
                                for parts in bipartitions:
                                    partitioned_pp1 = []
                                    for j,part in enumerate(parts):
                                        sub_pp1 = ['I']*self.n
                                        for j in part:
                                            sub_pp1[j] = pp1[j]
                                        partitioned_pp1.append(''.join(sub_pp1))
                                    partitioned_pp1s.append(partitioned_pp1)
                                
                                e1 = 0
                                partion_used = []
                                for [subpp1_a,subpp1_b] in partitioned_pp1s:
                                    if subpp1_a in self.pauli_decomp and subpp1_b in self.pauli_decomp:
                                        e = self.pauli_decomp[subpp1_a]*self.pauli_decomp[subpp1_b]
                                    else:
                                        e = 0
                                    if abs(e)>abs(e1):
                                        e1 = e      
                                        partition_used = [subpp1_a,subpp1_b]
                                decomp_diff[pp0] = e1 * (-1)**(p0 in ['XY','YX'])
                                
                                if verbose:
                                    if abs(self.pauli_decomp[pp0])>0.01:
                                        print('Effectively swap',pp0,'with',pp1,'using the value',round(e1,2),'inferred from',partition_used[0],'and',partition_used[1])
                
                for pp in decomp_diff:
                    self.pauli_decomp[pp] = decomp_diff[pp]
            
            if verbose:
                print('Resulting state:')
                for pp in self.pauli_decomp:
                    if abs(self.pauli_decomp[pp]) > 0.01:
                        print(pp, self.pauli_decomp[pp])
                        
    def get_counts(self,shots=1024,samples=8192):

        def log(number):
            if number==0:
                return float('-inf')
            else:
                return math.log(number)

        samples = max(samples, 2*shots)
        cycle = int((samples/2)/shots) 
        n = self.n

        # prob[j] prob of qubit j being in state 0
        prob = [0 for j in range(n)]
        Z = [0 for j in range(n)]
        ZZ = [{} for j in range(n)]
        for string in self.pauli_decomp:
            support = [j for j,char in enumerate(string) if char=='Z']
            if 'X' not in string and 'Y' not in string:
                if len(support)==1:
                    Z[support[0]] = self.pauli_decomp[string]
                    prob[support[0]] = (1+self.pauli_decomp[string])/2
                elif len(support)==2:
                    for [j,k] in [support,support[::-1]]:
                        ZZ[j][k] = self.pauli_decomp[string]

        # create an initial bit string
        bits = [random.choices(['0','1'],weights=[prob[j],1-prob[j]])[0] for j in range(n)]

        counts = {}
        shots_taken = 0
        sample = 0
        while shots_taken<shots:

            j = random.choice(range(n))

            current = bits[j]
            proposed = str((int(bits[j])+1)%2)

            # P[b] is the prob that qubit j is in state b, and its neighbours are in whatselfer state they are in
            P = {'0':log(prob[j]), '1':log(1-prob[j])}
            for k in ZZ[j]:
                if bits[k]=='0':
                    P['0'] += log( (1+Z[j]+Z[k]+ZZ[j][k])/4 ) - log(prob[j])
                    P['1'] += log( (1+Z[j]-Z[k]-ZZ[j][k])/4 ) - log(1-prob[j])
                else:
                    P['0'] += log( (1+Z[j]-Z[k]-ZZ[j][k])/4 ) - log(prob[j])
                    P['1'] += log( (1-Z[j]-Z[k]+ZZ[j][k])/4 ) - log(1-prob[j])
            for bit in P:
                P[bit] = math.exp(P[bit])

            # We want to calculate the ratio of the b=0 and b=1 probabilities
            # Prob(b on j| current state on neighours)
            # Using the fact that
            # Prob(b on j| current state on neighours) = P[b] / Prob(current state on neighours))
            # this is just the ratio of P[0] and P[1]
            if P[current]!=0:
                accept_prob = P[proposed]/P[current]
            else:
                accept_prob = 1

            if random.random()<accept_prob:
                bits[j] = proposed

            if sample>=samples/2 and sample%cycle==0:
                output = ''.join(bits[::-1])
                if output in counts:
                    counts[output] += 1
                else:
                    counts[output] = 1
                shots_taken += 1

            sample += 1

        return counts