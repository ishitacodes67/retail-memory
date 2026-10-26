# run.py
import os
import subprocess
import sys
import time


def start_fastapi():
    """Start FastAPI internally on port 8000."""
    subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "api.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
    ])

def start_streamlit():
    """Start Streamlit on the port Render provides (or 7860 locally)."""
    port = int(os.environ.get("PORT", 7860))
    
    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(port),
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ])

if __name__ == "__main__":
    start_fastapi()
    time.sleep(3)  # Give FastAPI a moment to boot
    start_streamlit()