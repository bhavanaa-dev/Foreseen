import pathlib, sys, traceback
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2] / 'backend'))
from app import app
app.testing = True
app.config['PROPAGATE_EXCEPTIONS'] = True
client = app.test_client()
try:
    resp = client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
    print('Status code:', resp.status_code)
    print('Response snippet:', resp.data[:500])
except Exception as e:
    print('Exception raised during request:')
    traceback.print_exc()
