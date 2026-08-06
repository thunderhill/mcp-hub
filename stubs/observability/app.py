from fastapi import FastAPI

app = FastAPI(title="Observability Stub")


@app.get("/services")
async def get_services():
    return ["api", "worker", "database"]


@app.get("/metrics")
async def get_metrics(service: str = "api", window: str = "5m"):
    return {
        "service": service,
        "window": window,
        "cpu_percent": 42.5,
        "memory_percent": 68.0,
        "request_rate": 120,
        "error_rate": 0.02,
    }


@app.get("/alerts")
async def get_alerts():
    return [
        {"alert": "high_memory", "service": "worker", "severity": "warning", "message": "Memory usage above 80%"},
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9002)
