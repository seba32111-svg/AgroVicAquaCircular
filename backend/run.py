from dotenv import load_dotenv

load_dotenv()

from backend.app import app  # noqa: E402  (la app lee MONGO_URI al importarse)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config.get("PORT", 5000), debug=False)
