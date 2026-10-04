"""Entry point for ``python -m fitness_app``.

Run locally (from the project root)::

    py -m fitness_app

Run inside Docker (see ``Dockerfile`` / ``docker-compose.yml``)::

    python -m fitness_app

Configuration is read from environment variables so the same code works on
the Windows dev PC and in a container:

``FITNESS_DEBUG``
    Enable Flask debug mode + auto-reloader. Defaults to enabled for local
    development; ``Dockerfile`` sets it to ``0`` so the container runs a
    single clean process.
``FITNESS_HOST``
    Interface to bind. Must stay ``0.0.0.0`` inside Docker, otherwise the
    container is unreachable from the host.
``FITNESS_PORT``
    Port to listen on (container-internal port).
"""

import os

from . import create_app

app = create_app()


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean-ish environment variable.

    Args:
        name: Environment variable name.
        default: Value used when the variable is unset or empty.

    Returns:
        True when the variable holds a truthy string ("1", "true", "yes", "on").
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    app.run(
        host=os.environ.get("FITNESS_HOST", "0.0.0.0"),
        port=int(os.environ.get("FITNESS_PORT", "5000")),
        # Debug/reloader on for local dev, off in the container (see Dockerfile).
        debug=_env_flag("FITNESS_DEBUG", default=True),
    )
