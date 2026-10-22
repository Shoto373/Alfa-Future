"""Shared environment for Alembic CLI and application startup."""
from alembic import context
from sqlalchemy import func, select
from sqlalchemy.schema import CreateSchema

from app import database
from app.models import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Retained only as an archive of the prototype's migration marker.
    return not (type_ == "table" and name in {"schema_migrations", "alembic_version"})


def run(connection):
    context.configure(connection=connection, target_metadata=target_metadata,
                      version_table_schema=database.schema(), include_object=include_object,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database.engine().url, target_metadata=target_metadata,
                      version_table_schema=database.schema(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    with database.engine().begin() as connection:
        connection.execute(select(func.pg_advisory_xact_lock(72810401)))
        connection.execute(CreateSchema(database.schema(), if_not_exists=True))
        run(connection)
