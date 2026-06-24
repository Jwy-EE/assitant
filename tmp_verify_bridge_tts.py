import httpx
payload = {
    'text': '愛してる。',
    'language': 'ja-JP',
    'voice': 'kurisu_ja',
    'style': 'serious',
}
with httpx.Client(timeout=300.0) as client:
    r = client.post('http://127.0.0.1:8767/tts', json=payload)
    print(r.status_code)
    print(r.headers.get('content-type'))
    print(len(r.content) if r.status_code == 200 else r.text)
