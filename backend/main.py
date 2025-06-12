import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from database.db import create_db_and_tables
from routes.shift import shift_router
from routes.auth import auth_router
from routes.query import query_router
from routes.report import report_router
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        print("🔌 Connecting to database...")
        create_db_and_tables()
        print("✅ Database connected and tables created successfully.")
    except Exception as e:
        print(f"❌ Failed to connect to the database: {e}")
    yield
    print("👋 App shutdown... Goodbye!")

app = FastAPI(lifespan=lifespan)

security_scheme = HTTPBearer()

UPLOAD_DIR = "uploads"
PHOTOS_DIR = os.path.join(UPLOAD_DIR, "attendance_photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Allow all origins during development ONLY
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



app.include_router(shift_router)
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(report_router)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Shift Management API",
        version="1.0.0",
        description="API docs with Bearer token support",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            if method in ["get", "post", "put", "delete", "patch"]:
                openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

if __name__ == "__main__":
    print("🚀 Starting FastAPI server...")
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
