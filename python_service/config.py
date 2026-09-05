import os
from pathlib import Path
from dotenv import load_dotenv

# Find .env in project root, parent directory, or current directory
for env_candidate in [
    Path(__file__).resolve().parent.parent / ".env",
    Path.cwd() / ".env",
    Path(__file__).resolve().parent / ".env",
]:
    if env_candidate.exists():
        load_dotenv(dotenv_path=env_candidate, override=True)
        break

def _resolve_database_url() -> str:
    # 1. Direct DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    
    # 2. Derive from SPRING_DATASOURCE_URL (e.g. jdbc:postgresql://localhost:5432/vyapaar_db)
    spring_url = os.getenv("SPRING_DATASOURCE_URL")
    if spring_url:
        cleaned = spring_url.replace("jdbc:", "")
        user = os.getenv("SPRING_DATASOURCE_USERNAME", "postgres")
        pwd = os.getenv("SPRING_DATASOURCE_PASSWORD", "postgres")
        if "@" not in cleaned:
            parts = cleaned.split("://")
            if len(parts) == 2:
                return f"{parts[0]}://{user}:{pwd}@{parts[1]}"
        return cleaned
    
    # 3. Default fallback to vyapaar_db
    return "postgresql://postgres:postgres@localhost:5432/vyapaar_db"

class Settings:
    APP_NAME: str = "Omni-CFO Unified AI Intelligence Service"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DATABASE_URL: str = _resolve_database_url()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

settings = Settings()
