'''
Script CHOP callbacks -- paste into the DAT of a Script CHOP named `quantum`.

Wiring:
    merge_analysis (CHOP)  ->  quantum (Script CHOP)

`merge_analysis` is a Merge CHOP of the four audioAnalysis outputs
(select2, select3, select4, select5 in the show file), so its channels are
    low  mid  high  low1 mid1 high1  low2 mid2 high2  low3 mid3 high3

Custom parameters to add to the Script CHOP (Component Editor):
    Numqubits   int     4
    Topology    menu    ring | chain | full
    Smoothing   float   0 .. 0.95
    Active      toggle  on

Output channels, per qubit q and per edge (a,b):
    q{q}_x q{q}_y q{q}_z q{q}_purity
    e{a}_{b}_corr  e{a}_{b}_zz  e{a}_{b}_xx

`e*_corr` is the one to reach for first: 0 when two mics are independent,
1 when their qubits are maximally correlated. It is the only channel here that
cannot be reconstructed from the mic levels on their own -- everything else is
a smooth function of one mic, which a Math CHOP could already have given you.
'''

import qg_td


def topology(name, n):
    if name == 'chain':
        return [[i, i + 1] for i in range(n - 1)]
    if name == 'full':
        return [[a, b] for a in range(n) for b in range(a + 1, n)]
    return qg_td.ring(n)


def engine(scriptOp):
    '''One engine per operator, rebuilt only when the graph shape changes.'''
    n = int(scriptOp.par.Numqubits)
    shape = topology(str(scriptOp.par.Topology), n)
    cached = getattr(scriptOp, '_qg', None)
    if cached is None or cached.num_qubits != n or cached.coupling_map != shape:
        cached = qg_td.QuantumAudioGraph(num_qubits=n, coupling_map=shape)
        scriptOp._qg = cached
    cached.smoothing = float(scriptOp.par.Smoothing)
    return cached


def onSetupParameters(scriptOp):
    page = scriptOp.appendCustomPage('Quantum')
    page.appendInt('Numqubits', label='Qubits')[0].default = 4
    page.appendMenu('Topology', label='Topology')[0].menuNames = ['ring', 'chain', 'full']
    page.appendFloat('Smoothing', label='Smoothing')[0].normMax = 0.95
    page.appendToggle('Active', label='Active')[0].default = True
    return


def onCook(scriptOp):
    graph = engine(scriptOp)

    if not scriptOp.par.Active:
        scriptOp.clear()
        return

    source = scriptOp.inputs[0] if scriptOp.inputs else None
    mics = max(1, len(source.chans('mid*')) if source else 1)
    values = graph.step(qg_td.features_from_chop(source, num_mics=mics))

    scriptOp.clear()
    for name in graph.channel_names:
        scriptOp.appendChan(name)[0] = values.get(name, 0.0)

    if graph.last_error:
        # Held the previous frame's values rather than dropping the render.
        debug('quantum CHOP held last frame:', graph.last_error)
    return
