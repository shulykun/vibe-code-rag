curl https://gigachat.devices.sberbank.ru/api/v1/embeddings \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <токен доступа>' \
  --data '{
    "model": "Embeddings",
    "input": [
        "Расскажи о современных технологиях",
        "Какие новинки в мире IT?"
    ]
  }'