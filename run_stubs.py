"""
Launches all three service stubs locally in parallel.
Run this before starting mcp-hub so the upstreams are available.

Usage: uv run python run_stubs.py
"""
from __future__ import annotations

import multiprocessing
import uvicorn


def run_minislack():
    from stubs.minislack.app import app
    uvicorn.run(app, host="127.0.0.1", port=9001, log_level="info")


def run_observability():
    from stubs.observability.app import app
    uvicorn.run(app, host="127.0.0.1", port=9002, log_level="info")


def run_rag():
    from stubs.rag.app import app
    uvicorn.run(app, host="127.0.0.1", port=9003, log_level="info")


if __name__ == "__main__":
    procs = [
        multiprocessing.Process(target=run_minislack, name="minislack"),
        multiprocessing.Process(target=run_observability, name="observability"),
        multiprocessing.Process(target=run_rag, name="rag"),
    ]
    for p in procs:
        p.start()
        print(f"Started {p.name} (pid={p.pid})")

    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        print("\nShutting down stubs...")
        for p in procs:
            p.terminate()
