"""Single-process hosted API entrypoint; credentials are injected by the host."""
import os

from backend.config import Settings
from backend.store import Store


def validate_hosted_settings():
    settings = Settings.load()
    database = str(settings.database)
    if not database.startswith(('postgresql://', 'postgres://')):
        raise ValueError('Hosted CONEL requires a persistent PostgreSQL database')
    if os.getenv('CONEL_PUBLIC_MODE') != '1':
        raise ValueError('Hosted CONEL requires CONEL_PUBLIC_MODE=1')
    if not os.getenv('CONEL_PROXY_SECRET'):
        raise ValueError('Hosted CONEL requires CONEL_PROXY_SECRET')
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    # Validate HTTPS/auth policy before opening a database connection or listener.
    from backend.github_auth import GitHubAuth
    from backend.public_boundary import PublicPolicy
    PublicPolicy.load(GitHubAuth(Store(settings.database)))
    return settings, port


def main():
    import uvicorn
    settings, port = validate_hosted_settings()
    # Migrations belong to the host's explicit pre-deploy/release step.
    Store(settings.database).initialize()
    uvicorn.run('backend.api:app', host='0.0.0.0', port=port,
                workers=1, proxy_headers=False, timeout_graceful_shutdown=660)


if __name__ == '__main__':
    main()
