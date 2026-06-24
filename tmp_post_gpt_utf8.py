import httpx
payload = {
    'text': '私は牧瀬紅莉栖。ちゃんと聞こえているなら、次の調整に進めるわ。',
    'text_lang': 'ja',
    'ref_audio_path': r'D:\Ai_project\programme\engnieer\assitant\Amadeus-main\Voices\OneShot\CRS_JP.wav',
    'prompt_text': '極端な管理社会全体主義まゆりがバナナを食べたいと思っても、今日がバナナを食べていい日でなければ食べることは許さ。',
    'prompt_lang': 'ja',
    'text_split_method': 'cut5',
    'batch_size': 1,
    'batch_threshold': 0.75,
    'split_bucket': True,
    'speed_factor': 1.0,
    'fragment_interval': 0.3,
    'seed': -1,
    'media_type': 'wav',
    'streaming_mode': False,
    'parallel_infer': True,
    'repetition_penalty': 1.35,
    'sample_steps': 32,
    'super_sampling': False,
}
with httpx.Client(timeout=300.0) as client:
    r = client.post('http://127.0.0.1:9880/tts', json=payload)
    print(r.status_code)
    print(r.headers.get('content-type'))
    print(r.text[:300] if 'application/json' in r.headers.get('content-type','') else len(r.content))
