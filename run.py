import os

if __name__ == "__main__":
    os.system("gunicorn -w 1 -k uvicorn.workers.UvicornWorker app:main")