from fastapi import FastAPI

app = FastAPI(title="MiniSlack Stub")

messages: dict[str, list[dict]] = {"general": [], "random": []}


@app.get("/channels")
async def get_channels():
    return list(messages.keys())


@app.get("/messages")
async def get_messages(channel: str = "general"):
    return messages.get(channel, [])


@app.post("/messages")
async def send_message(body: dict):
    channel = body.get("channel", "general")
    text = body.get("text", "")
    msg = {"channel": channel, "text": text, "id": len(messages.get(channel, [])) + 1}
    messages.setdefault(channel, []).append(msg)
    return {"ok": True, **msg}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9001)
