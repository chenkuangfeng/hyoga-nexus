from fastapi import FastAPI

app = FastAPI(title="Hyoga Nexus", version="0.1.0")

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "hyoga-nexus"}

@app.get("/api/v1/capabilities")
def capabilities():
    return {
        "runtimes": [{"name": name, "status": "planned"} for name in ["Codex", "Claude Code", "DeepSeek Harness"]],
        "channels": [{"name": name, "status": "planned"} for name in ["Web", "企业微信", "微信", "QQ"]],
        "applications": [{"name": "观澜 Guanlan", "status": "planned"}],
    }
