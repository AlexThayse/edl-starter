import pytest
import tempfile
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Imports de votre application
from src.app import app
from src.database import Base, get_db
from src.models import TaskModel

# 1. Configuration de la base de données de test (SQLite temporaire)
# Utilise un fichier temporaire unique pour chaque lancement de tests
TEST_DB_FILE = tempfile.mktemp(suffix=".db")
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

# Engine spécifique pour les tests
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Important pour SQLite en mémoire/test
)

# Factory de session de test
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def setup_test_database():
    """Crée les tables une seule fois pour toute la session de test."""
    Base.metadata.create_all(bind=test_engine)
    yield
    # Nettoyage final (optionnel car fichier temp)
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except PermissionError:
            pass


@pytest.fixture(autouse=True)
def clear_test_data(setup_test_database):
    """Nettoie les données entre chaque test pour garantir l'isolation."""
    db = TestSessionLocal()
    try:
        db.query(TaskModel).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    """Crée un client de test qui utilise la base de test au lieu de la vraie DB."""

    # Fonction locale pour remplacer get_db
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Remplacement de la dépendance FastAPI
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    # Nettoyage de l'override après le test
    app.dependency_overrides.clear()