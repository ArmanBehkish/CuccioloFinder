from fastapi import FastAPI

app = FastAPI(title="CuccioloFinder API")


@app.get("/api/test")
def test():
    return {"status": "ok"}

