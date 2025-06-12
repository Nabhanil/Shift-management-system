# database/db.py
from sqlmodel import create_engine, SQLModel, Session
from dotenv import load_dotenv
import os
from models.postgres_models import Employee, ShiftAssignment

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
# engine = create_engine(DATABASE_URL, echo=True)

def create_db_and_tables():
    print("🔌 Connecting to database...")
    try:
        SQLModel.metadata.create_all(engine)
        # print("✅ Database connected and tables created successfully.")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")

def get_session():
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
