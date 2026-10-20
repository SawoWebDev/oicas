from alembic import context

from oicas import models  # noqa: F401  (registers tables)
from oicas.config import get_settings
from oicas.db import Base, make_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().active_database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(get_settings().active_database_url)  # live → primary, demo → secondary
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
