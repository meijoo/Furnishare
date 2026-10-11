import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
load_dotenv(REPO_DIR / '.env')

DATA_DIR = BACKEND_DIR / 'data'
STATIC_DIR = BACKEND_DIR / 'static'
ASSETS_DIR = STATIC_DIR / 'assets'
UPLOADS_DIR = STATIC_DIR / 'uploads'
for d in (DATA_DIR, ASSETS_DIR, UPLOADS_DIR, STATIC_DIR / 'product_images'):
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv('RTR_DB_PATH', DATA_DIR / 'app.db'))
SEED_DEMO = os.getenv('RTR_SEED_DEMO', '1').strip().lower() in ('1', 'true', 'yes')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', '').strip() or 'gemini-flash-latest'
# Floor-plan reads are a short JSON extract; override to a lite model if you want them cheaper/faster.
GEMINI_FLOORPLAN_MODEL = os.getenv('GEMINI_FLOORPLAN_MODEL', '').strip() or GEMINI_MODEL
# Portable AI Studio key first so teammates can share .env. Vertex ADC is laptop-local.
VERTEX_API_KEY = os.getenv('VERTEX_API_KEY', '').strip()
GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT', '').strip()
GOOGLE_CLOUD_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', '').strip() or 'us-central1'
USE_VERTEX = os.getenv('GOOGLE_GENAI_USE_VERTEXAI', '').strip().lower() in ('1', 'true', 'yes') \
    or bool(VERTEX_API_KEY)
if GEMINI_API_KEY:
    GEMINI_BACKEND = 'ai_studio'
elif VERTEX_API_KEY:
    GEMINI_BACKEND = 'vertex'
elif USE_VERTEX and GOOGLE_CLOUD_PROJECT:
    GEMINI_BACKEND = 'vertex'
else:
    GEMINI_BACKEND = None

NESSIE_API_KEY = os.getenv('NESSIE_API_KEY', '').strip()
NESSIE_BASE_URL = os.getenv('NESSIE_BASE_URL', 'https://api.nessieisreal.com').rstrip('/')
# 'live' requires NESSIE_API_KEY; 'mock' is an in-process simulator that is labeled as such everywhere.
NESSIE_MODE = os.getenv('NESSIE_MODE', 'live' if NESSIE_API_KEY else 'mock')

RANKER_URL = os.getenv('RANKER_URL', 'http://127.0.0.1:8100').rstrip('/')
SHOPPING_API_KEY = os.getenv('SHOPPING_API_KEY', '').strip()
BUILD_ASSETS = os.getenv('RTR_BUILD_ASSETS', '1') == '1'
CURRENCY = 'USD'
