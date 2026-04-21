import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from main import Base, Profile
from datetime import datetime, timezone
from uuid_extensions import uuid7

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    exit(1)

# Ensure compatibility with SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def run_seed():
    print("Loading local seed data...")
    try:
        with open("seed_profiles.json", "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
            # --- TRAP 1 FIXED: Safely unwrap the "profiles" dictionary ---
            if isinstance(raw_data, dict) and "profiles" in raw_data:
                profiles_data = raw_data["profiles"]
            elif isinstance(raw_data, list):
                profiles_data = raw_data
            else:
                print("ERROR: Could not find the profile list in the JSON.")
                return
                
    except FileNotFoundError:
        print("ERROR: Could not find seed_profiles.json.")
        return
    except json.JSONDecodeError:
        print("ERROR: seed_profiles.json is not a valid JSON file.")
        return

    print("Rebuilding database schema...")
    Base.metadata.drop_all(bind=engine) 
    Base.metadata.create_all(bind=engine) 

    db = SessionLocal()
    print(f"Seeding {len(profiles_data)} profiles...")

    for item in profiles_data:
        # --- TRAP 2 FIXED: Generate the missing IDs and Timestamps ---
        new_id = str(uuid7())
        created_time = datetime.now(timezone.utc)

        stmt = insert(Profile).values(
            id=new_id,
            name=item["name"],
            gender=item.get("gender"),
            gender_probability=item.get("gender_probability"),
            age=item.get("age"),
            age_group=item.get("age_group"),
            country_id=item.get("country_id"),
            country_name=item.get("country_name"),
            country_probability=item.get("country_probability"),
            created_at=created_time
        )
        
        # On conflict (name already exists), do nothing
        stmt = stmt.on_conflict_do_nothing(index_elements=['name'])
        db.execute(stmt)

    db.commit()
    db.close()
    print("Seeding complete!")

if __name__ == "__main__":
    run_seed()
