"""Root pytest conftest — load .env before all tests."""
import pathlib
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)
