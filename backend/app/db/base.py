"""Import surface for metadata creation. Importing this module pulls in the
declarative Base with every model registered on its metadata, so
``Base.metadata.create_all()`` sees all 22 tables.
"""

from app.models import Base  # noqa: F401  (re-exported for create_all)
import app.models  # noqa: F401  (ensures every model module is imported)
