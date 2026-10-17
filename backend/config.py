"""CONEL database settings. Deployment variables take precedence."""
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database: Path | str

    @classmethod
    def load(cls):
        load_dotenv(ROOT / '.env', override=False)
        from backend.stack import directory
        for name, value in dotenv_values(directory() / '.env').items():
            if value is not None and not os.environ.get(name):
                os.environ[name] = value
        if not os.environ.get('CREATEOS_API_KEY') and os.environ.get('CREATEOS_SANDBOX_API_KEY'):
            os.environ['CREATEOS_API_KEY'] = os.environ['CREATEOS_SANDBOX_API_KEY']
        return cls(os.getenv('CONEL_DATABASE_URL') or os.getenv('DATABASE_URL') or Path(os.getenv('CONEL_DATABASE', str(ROOT / 'var' / 'conel.sqlite3'))).resolve())
