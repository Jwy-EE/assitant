"""Test that app loads with turn.py integration"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force no GPU TTS for test
import os
os.environ["ASSISTANT_TTS_PROVIDER"] = "browser"

from src.assistant_app.app import app

print(f"App loaded OK. Routes: {len(app.routes)}")

# Check that /api/turn/decide is registered
turn_routes = [r.path for r in app.routes if "turn" in getattr(r, "path", "")]
print(f"Turn routes found: {turn_routes}")
assert any("turn" in r for r in turn_routes), "/api/turn/decide not found!"
print("✅ turn endpoint registered successfully!")