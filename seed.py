import os
import json
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

def run_seed():
    print("Loading local seed data...")
    try:
        with open("seed_profiles.json", "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
            # --- THE FIX: Unwrap the JSON object to find the array ---
            if isinstance(raw_data, dict):
                # Try common keys where the list might be hidden
                profiles_data = raw_data.get("data") or raw_data.get("profiles") or raw_data.get("results")
                
                # If those exact keys aren't there, just grab the first list it finds
                if not profiles_data:
                    for val in raw_data.values():
                        if isinstance(val, list):
                            profiles_data = val
                            break
            else:
                # If it's already a list, just use it
                profiles_data = raw_data
                
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
