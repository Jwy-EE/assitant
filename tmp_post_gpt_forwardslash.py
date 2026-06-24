import httpx
payload = {
    'text': '私は牧瀬紅莉栖。ちゃんと聞こえているなら、次の調整に進めるわ。',
    'text_lang': 'ja',
    'ref_audio_path': 'D:/Ai_project/programme/engnieer/assitant/Amadeus-main/Voices/OneShot/CRS_JP.wav',
    'prompt_text': '極端な管理社会全体主義まゆりがバナナを食べたいと思っても、今日がバナナを食べていい日でなければ食べることは許さ。',
    'prompt_lang': 'ja',
    'text_split_method': 'cut5',
    'batch_size': 1,
    'speed_factor': 1.0,
    'top_k': 15,
    'top_p': 1.0,
    'temperature': 1.0,
    'repetition_penalty': 1.35,
    'media_type': 'wav',
    'streaming_mode': False,
}
with httpx.Client(timeout=300.0) as client:
    r = client.post('http://127.0.0.1:9880/tts', json=payload)
    print(r.status_code)
    print(r.headers.get('content-type'))
    print(len(r.content) if r.status_code == 200 else r.text[:300])
