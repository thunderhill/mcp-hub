from fastapi import FastAPI

app = FastAPI(title="Enterprise RAG Stub")


@app.post("/query")
async def query(body: dict):
    question = body.get("question", "")
    top_k = body.get("top_k", 5)
    return {
        "question": question,
        "results": [
            {"text": f"Stub answer for: {question}", "score": 0.95, "source": "doc_001.pdf"},
            {"text": "Additional context from knowledge base", "score": 0.82, "source": "doc_042.pdf"},
        ][:top_k],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9003)
