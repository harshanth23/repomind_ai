import os
import sys
import threading
import uvicorn
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

sys.path.insert(0, os.path.dirname(__file__))

from database.db import DatabaseManager


def run_server():
    """Start the FastAPI local server."""
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('SERVER_PORT', 8000))
    print(f"[RepoMind AI] Starting FastAPI server at http://{host}:{port}")
    uvicorn.run('server.local_listener:app', host=host, port=port, reload=False)


def run_telegram():
    """Start the Telegram bot."""
    from server.telegram_bot import run_bot
    run_bot()


def main():
    print("="*50)
    print(" RepoMind AI – Autonomous Project Analyzer")
    print("="*50)

    # Initialize DB
    db = DatabaseManager()
    print("[DB] Database initialized.")

    # Start FastAPI server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    import time
    time.sleep(1.5)  # Brief pause to let server start

    # Run Telegram bot (blocking, main thread)
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    if telegram_token and telegram_token != 'your_telegram_bot_token_here':
        print("[Telegram] Starting Telegram bot...")
        run_telegram()
    else:
        print("[Telegram] TELEGRAM_BOT_TOKEN not set. Running server only.")
        print(f"[RepoMind AI] FastAPI docs: http://localhost:{os.getenv('SERVER_PORT', 8000)}/docs")
        server_thread.join()  # Keep alive


if __name__ == '__main__':
    main()

