"""CONEL database administration: python -m backend migrate."""
import argparse
import json
import os
from backend.config import Settings
from backend.store import Store


def main():
    parser = argparse.ArgumentParser(description='CONEL database administration')
    parser.add_argument('command', choices=['migrate', 'check'])
    args = parser.parse_args()
    settings = Settings.load()
    target = os.getenv('CONEL_MIGRATION_DATABASE_URL') if args.command == 'migrate' else None
    store = Store(target or settings.database)
    store.initialize(migrate=args.command == 'migrate')
    print(json.dumps({'status': 'ready', 'schema_version': 1,
                      'storage': 'postgresql' if store.database.postgres else 'sqlite'}))


if __name__ == '__main__':
    main()
