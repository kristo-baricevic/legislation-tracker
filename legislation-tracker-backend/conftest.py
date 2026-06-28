import os


os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("USE_LOCAL_DOCUMENT_STORAGE", "True")

