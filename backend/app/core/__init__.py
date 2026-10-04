"""Model package marker.

Importing this module registers every table on `Base.metadata`, which is what
`create_all()` and the Alembic autogenerate target rely on.
"""