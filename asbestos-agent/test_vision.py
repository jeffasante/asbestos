import httpx
import asyncio

async def test():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "Describe the contents of this image briefly."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVQIW2NkYGD4z8DAwMgAI0AMDA4wB9x7p+IAAAAASUVORK5CYII="}}
        ]}
    ]
    resp = httpx.post("http://127.0.0.1:8080/v1/chat/completions", json={
        "model": "local",
        "messages": messages,
        "max_tokens": 50
    })
    print(resp.status_code, resp.text)

asyncio.run(test())
