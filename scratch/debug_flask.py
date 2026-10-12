import pathlib, sys
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
from app import app
app.testing = True
app.config['PROPAGATE_EXCEPTIONS'] = True
client = app.test_client()
# GET request
resp_get = client.get('/analyze')
print('GET /analyze status:', resp_get.status_code)
print('GET response data (first 200 bytes):', resp_get.data[:200])
# POST request with proper form field name
resp_post = client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
print('POST /analyze status:', resp_post.status_code)
print('POST response data (first 200 bytes):', resp_post.data[:200])
