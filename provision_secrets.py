#!/usr/bin/env python3
import os, json, base64, urllib.request, urllib.error, subprocess
from nacl import encoding, public

GH_TOKEN = os.environ.get('GITHUB_TOKEN', '')
if not GH_TOKEN:
    r = subprocess.run(['bash','-c','source /opt/polyglot/.env 2>/dev/null && echo $GITHUB_TOKEN'], capture_output=True, text=True)
    GH_TOKEN = r.stdout.strip()

print(f'Token: {"YES len="+str(len(GH_TOKEN)) if GH_TOKEN else "NO"}')
if not GH_TOKEN:
    exit(1)

REPO = 'theonlygeranium/Project-Tango'
H = {'Authorization': f'Bearer {GH_TOKEN}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'}

def gh(url, method='GET', data=None):
    req = urllib.request.Request(url, headers=H, method=method)
    if data: req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req) as r: return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e: return json.loads(e.read()), e.code

pk, s = gh(f'https://api.github.com/repos/{REPO}/actions/secrets/public-key')
print(f'PubKey status: {s}')
if s != 200: print(pk); exit(1)

def enc(pk_b64, val):
    k = public.PublicKey(pk_b64.encode(), encoding.Base64Encoder())
    return base64.b64encode(public.SealedBox(k).encrypt(val.encode())).decode()

with open('/home/z121532/.ssh/project_tango_deploy_ed25519') as f:
    ssh_key = f.read().strip()

secrets = {
    'SCHUBERT_SSH_KEY': ssh_key,
    'TAILSCALE_AUTHKEY': 'tskey-auth-kmQAs12R7A21CNTRL-KvDcMbzTEyUVqqd8t9XZxUD5AGzZej99A'
}

for name, val in secrets.items():
    res, s = gh(f'https://api.github.com/repos/{REPO}/actions/secrets/{name}', 'PUT', {'encrypted_value': enc(pk['key'], val), 'key_id': pk['key_id']})
    print(f'{name}: HTTP {s} {"OK" if s in (201,204) else res}')

print('Done!')
