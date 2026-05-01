try:
    from app.main import app
except Exception:
    # Re-raise with original traceback to surface import errors to Uvicorn
    raise

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
