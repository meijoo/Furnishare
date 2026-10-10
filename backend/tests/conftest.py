import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix='rtr-test-')
os.environ.update({
    'RTR_DB_PATH': str(Path(_tmp) / 'test.db'),
    'RTR_CATALOG': str(Path(_tmp) / 'no-verified-catalog.json'),
    'RTR_BUILD_ASSETS': '0',
    'NESSIE_MODE': 'mock',
    'RTR_CATALOG_EXTRA': str(Path(_tmp) / 'no-extra-catalog.json'),
    'GEMINI_API_KEY': '',
    'GOOGLE_GENAI_USE_VERTEXAI': '',
    'VERTEX_API_KEY': '',
    'GOOGLE_CLOUD_PROJECT': '',
    'SHOPPING_API_KEY': '',
    'RANKER_URL': 'http://127.0.0.1:9',
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
