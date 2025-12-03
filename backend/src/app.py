from contextlib import asynccontextmanager
import uuid
import os
import logging
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

# Imports locaux
from .database import get_db, init_db
from .models import TaskModel, TaskStatus, TaskPriority

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("taskflow")


# =============================================================================
# MODELS (Pydantic)
# =============================================================================

class TaskCreate(BaseModel):
    """Model for creating a new task."""
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    status: TaskStatus = Field(default=TaskStatus.TODO, description="Task status")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    assignee: Optional[str] = Field(None, max_length=100, description="Assigned user")
    due_date: Optional[datetime] = Field(None, description="Due date")


class TaskUpdate(BaseModel):
    """Model for updating a task - all fields optional for partial updates."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee: Optional[str] = Field(None, max_length=100)
    due_date: Optional[datetime] = None


class Task(BaseModel):
    """Model for task response compatible with SQLAlchemy."""
    id: str  # UUID est une string
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    assignee: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True # Indispensable pour l'ORM


# =============================================================================
# LIFESPAN & FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager : initialise la DB au démarrage."""
    logger.info("TaskFlow backend starting up...")
    init_db()  # Crée les tables dans la base de données
    logger.info("Database initialized")
    yield
    logger.info("TaskFlow backend shutting down...")

app = FastAPI(
    title="TaskFlow API",
    description="Simple task management API",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# Configuration CORS
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "message": "Welcome to TaskFlow API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check with database status."""
    try:
        # Vérifie la connexion avec une requête SQL simple
        db.execute(text("SELECT 1"))
        tasks_count = db.query(TaskModel).count()
        return {
            "status": "healthy",
            "database": "connected",
            "tasks_count": tasks_count
        }
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/tasks", response_model=List[Task])
async def get_tasks(
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        assignee: Optional[str] = None,
        db: Session = Depends(get_db)
):
    """Get all tasks with optional filtering."""
    query = db.query(TaskModel)

    if status:
        query = query.filter(TaskModel.status == status)
    if priority:
        query = query.filter(TaskModel.priority == priority)
    if assignee:
        query = query.filter(TaskModel.assignee == assignee)

    return query.all()


@app.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get a single task by ID."""
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@app.post("/tasks", response_model=Task, status_code=201)
async def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    """Create a new task."""
    # Validation
    if not task_data.title or not task_data.title.strip():
        raise HTTPException(status_code=422, detail="Title cannot be empty")

    # Création de l'objet ORM avec UUID
    db_task = TaskModel(
        id=str(uuid.uuid4()),
        **task_data.model_dump()
    )

    db.add(db_task)
    db.commit()      # Sauvegarde en base
    db.refresh(db_task) # Recharge pour avoir les dates (created_at)

    logger.info(f"Task created successfully: {db_task.id}")
    return db_task


@app.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: str, updates: TaskUpdate, db: Session = Depends(get_db)):
    """Update an existing task."""
    # 1. Récupérer la tâche
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # 2. Mettre à jour les champs dynamiquement
    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)

    # 3. Sauvegarder
    db.commit()
    db.refresh(task) # Recharge pour avoir updated_at à jour
    return task


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, db: Session = Depends(get_db)):
    """Delete a task by ID."""
    # 1. Récupérer la tâche
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # 2. Supprimer
    db.delete(task)
    db.commit()
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)