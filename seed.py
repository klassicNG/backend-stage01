import os
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from main import Base, Profile
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    exit(1)

# Ensure compatibility with SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# URL to the JSON file provided in the Stage 2 instructions
JSON_URL = "YOUR_PROVIDED_JSON_LINK_HERE" 

def run_seed():
    print("Downloading seed data...")
    response = requests.get(JSON_URL)
    if response.status_code != 200:
        print("Failed to download seed data.")
        return
    
    profiles_data = response.json()

    print("Rebuilding database schema...")
    Base.metadata.drop_all(bind=engine) # Drops the old Stage 1 table
    Base.metadata.create_all(bind=engine) # Creates the new Stage 2 table

    db = SessionLocal()
    print(f"Seeding {len(profiles_data)} profiles...")

    for item in profiles_data:
        # Create an upsert statement (Idempotent)
        stmt = insert(Profile).values(
            id=item["id"],
            name=item["name"],
            gender=item.get("gender"),
            gender_probability=item.get("gender_probability"),
            age=item.get("age"),
            age_group=item.get("age_group"),
            country_id=item.get("country_id"),
            country_name=item.get("country_name"),
            country_probability=item.get("country_probability"),
            created_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) if item.get("created_at") else datetime.now(timezone.utc)
        )
        
        # On conflict (name already exists), do nothing
        stmt = stmt.on_conflict_do_nothing(index_elements=['name'])
        db.execute(stmt)

    db.commit()
    db.close()
    print("Seeding complete!")

if __name__ == "__main__":
    run_seed()
