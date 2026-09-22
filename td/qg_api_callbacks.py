'''
Web Client DAT callbacks -- the slow lane.

This talks to graph-api (`/v1/generation/graph-v1/process`), which is a
four-step job pipeline: submit, poll, collect, format. Even on `mode="emu"`
that is a job round trip, and on `mode="qpu"` the IBM queue can be hours. It
is not a per-frame source and must never be wired as one.

Use it for what it is good at: occasionally fetching a *real* prepared state
-- one that used set_bloch / set_relationship, or ran on hardware -- and
parking it in a Table DAT as a preset. The per-frame motion keeps coming from
the local engine in qg_td.py.

Wiring:
    quantum_api   (Web Client DAT, these callbacks)
    quantum_state (Table DAT)        <- results land here
    a Timer CHOP or a button calls  mod('quantum_api_callbacks').submit(me)

Custom parameters on the Web Client DAT:
    Baseurl     str     https://api.mothquantum.com/v1
    Apikey      str     (your key)
    Numqubits   int     4
    Shots       int     1024
    Mode        menu    emu | qpu
    Pollsecs    float   2.0
'''

import json


STATE = {'phase': 'idle', 'job_id': None, 'next_poll': 0.0}


# -- outbound ---------------------------------------------------------------

def submit(dat, operations=None, coupling_map=None, seed=None):
    '''
    Fires one job. Returns False (and does nothing) if one is already in
    flight -- the API has no notion of superseding a request, so queueing more
    of them just spends credits on results you will throw away.
    '''
    if STATE['phase'] != 'idle':
        return False

    body = {
        'num_qubits': int(dat.par.Numqubits),
        'shots': int(dat.par.Shots),
        'mode': str(dat.par.Mode),
    }
    if coupling_map:
        body['coupling_map'] = [list(edge) for edge in coupling_map]
    if operations:
        body['operations'] = operations
    if seed is not None:
        body['seed'] = int(seed)

    STATE['phase'] = 'submitting'
    dat.request(f'{dat.par.Baseurl}/generation/graph-v1/process', 'POST',
                header=_headers(dat), data=json.dumps(body))
    return True


def reset(dat=None):
    STATE.update(phase='idle', job_id=None, next_poll=0.0)


def _headers(dat):
    return {'Authorization': f'Bearer {dat.par.Apikey}',
            'Content-Type': 'application/json'}


# -- callbacks --------------------------------------------------------------

def onResponse(webClientDAT, statusCode, headerDict, data, id):
    code = statusCode.get('code') if isinstance(statusCode, dict) else statusCode
    if int(code) >= 400:
        debug('quantum api', code, data[:400] if data else '')
        reset()
        return

    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        debug('quantum api: response was not json')
        reset()
        return

    phase = STATE['phase']

    if phase == 'submitting':
        STATE['job_id'] = payload.get('job_id')
        STATE['phase'] = 'polling' if STATE['job_id'] else 'idle'
        STATE['next_poll'] = absTime.seconds + float(webClientDAT.par.Pollsecs)

    elif phase == 'polling':
        status = payload.get('status')
        if status == 'completed':
            STATE['phase'] = 'collecting'
            webClientDAT.request(
                f"{webClientDAT.par.Baseurl}/result/{STATE['job_id']}", 'GET',
                header=_headers(webClientDAT))
        elif status == 'failed':
            debug('quantum api: job failed', STATE['job_id'])
            reset()
        else:
            STATE['next_poll'] = absTime.seconds + float(webClientDAT.par.Pollsecs)

    elif phase == 'collecting':
        output = (payload.get('result') or {}).get('output') or {}
        write_state(webClientDAT, output)
        reset()
    return


def onPoll(webClientDAT):
    '''Call this from an Execute DAT's onFrameStart, or a 1 Hz Timer CHOP.'''
    if STATE['phase'] == 'polling' and absTime.seconds >= STATE['next_poll']:
        STATE['next_poll'] = absTime.seconds + float(webClientDAT.par.Pollsecs)
        webClientDAT.request(
            f"{webClientDAT.par.Baseurl}/status/{STATE['job_id']}", 'GET',
            header=_headers(webClientDAT))
    return


# -- landing the result -----------------------------------------------------

def write_state(dat, output, table='quantum_state'):
    '''
    Flattens the engine's `tomography` block into a two-column Table DAT, using
    the same channel names the local engine produces -- so a Table-to-CHOP on
    this table is interchangeable with the `quantum` Script CHOP downstream.
    '''
    target = dat.parent().op(table)
    if target is None:
        debug(f'quantum api: no table DAT named {table}')
        return

    tomography = output.get('tomography') or {}
    rows = []

    for qubit, bloch in (tomography.get('bloch') or {}).items():
        x, y, z = bloch.get('X', 0.0), bloch.get('Y', 0.0), bloch.get('Z', 0.0)
        rows += [(f'q{qubit}_x', x), (f'q{qubit}_y', y), (f'q{qubit}_z', z),
                 (f'q{qubit}_purity', (x * x + y * y + z * z) ** 0.5)]

    blochs = tomography.get('bloch') or {}
    for edge, rel in (tomography.get('relationships') or {}).items():
        a, b = edge.split(',')
        rows += [(f'e{a}_{b}_zz', rel.get('ZZ', 0.0)),
                 (f'e{a}_{b}_xx', rel.get('XX', 0.0)),
                 (f'e{a}_{b}_corr', _correlation(rel, blochs.get(a), blochs.get(b)))]

    rows += [('dominant_bitstring', output.get('dominant_bitstring', '')),
             ('edge_agreement_score', output.get('edge_agreement_score', 0.0)),
             ('backend', output.get('backend', '')),
             ('mode', output.get('mode', ''))]

    target.clear()
    target.appendRow(['name', 'value'])
    for name, value in rows:
        target.appendRow([name, value])


def _correlation(rel, bloch0, bloch1):
    '''Matches MicroQuantumGraph.get_correlation so both lanes agree.'''
    if not bloch0 or not bloch1:
        return 0.0
    total = 0.0
    for pauli, value in rel.items():
        connected = value - bloch0.get(pauli[0], 0.0) * bloch1.get(pauli[1], 0.0)
        total += connected ** 2
    return min(1.0, (total / 3.0) ** 0.5)
