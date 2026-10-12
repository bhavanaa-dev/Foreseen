import sys
import pathlib
sys.path.append('C:/Users/HP/Documents/Foreseen/backend')
from app import app

def main():
    with app.test_client() as client:
        resp = client.post('/analyze', data={'query': 'MacBook Air M1 8GB 256GB'})
        print('POST status:', resp.status_code)
        print('Response snippet:', resp.data[:500])
        resp2 = client.get('/analyze')
        print('GET status:', resp2.status_code)
        print('GET snippet:', resp2.data[:200])

if __name__ == '__main__':
    main()
