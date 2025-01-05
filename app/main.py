from fastapi import FastAPI
from transformers import pipeline
import torch

app = FastAPI()


# Load model during startup
@app.on_event("startup")
async def startup_event():
    global model
    device = 0 if torch.cuda.is_available() else -1
    model = pipeline("sentiment-analysis", device=device)


@app.get("/predict")
async def predict(text: str):
    result = model(text)
    return {"result": result}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/predict")
async def predict(text: str):
    try:
        result = model(text)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
