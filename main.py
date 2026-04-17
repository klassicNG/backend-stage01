from fastapi import FastAPI, HTTPException, Request, Depends, Query, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from pydantic import BaseModel
import httpx
import asyncio
import os
from uuid_extensions import uuid7 # using the uuid7 package

# --- 1. DATABASE SETUP ---
# Swap this with your actual PostgreSQL URL (e.g., postgresql://user:pass@host/db)
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    gender = Column(String(50))
    gender_probability = Column(Float)
    sample_size = Column(Integer)
    age = Column(Integer)
    age_group = Column(String(50))
    country_id = Column(String(10))
    country_probability = Column(Float)
    created_at = Column(DateTime(timezone=True))

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 2. FASTAPI APP & CORS ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Required for grading script
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 3. CUSTOM ERROR HANDLING ---
# Overrides standard FastAPI 422 to match the required schema
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid type or missing fields"}
    )

class ProfileCreate(BaseModel):
    name: str

# --- 4. ENDPOINTS ---

@app.post("/api/profiles", status_code=201)
async def create_profile(payload: ProfileCreate, db: Session = Depends(get_db)):
    name = payload.name.strip().lower()
    
    if not name:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Missing or empty name"})

    # Idempotency Check
    existing_profile = db.query(Profile).filter(Profile.name == name).first()
    if existing_profile:
        return JSONResponse(
            status_code=200, 
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": {col.name: getattr(existing_profile, col.name) for col in existing_profile.__table__.columns}
            }
        )

    # Fetch APIs concurrently
    async with httpx.AsyncClient() as client:
        req_gender = client.get(f"https://api.genderize.io?name={name}")
        req_age = client.get(f"https://api.agify.io?name={name}")
        req_nat = client.get(f"https://api.nationalize.io?name={name}")
        
        res_gender, res_age, res_nat = await asyncio.gather(req_gender, req_age, req_nat)

    gender_data = res_gender.json()
    age_data = res_age.json()
    nat_data = res_nat.json()

    # Edge Cases (502)
    if gender_data.get("gender") is None or gender_data.get("count", 0) == 0:
        return JSONResponse(status_code=502, content={"status": "error", "message": "Genderize returned an invalid response"})
    
    if age_data.get("age") is None:
        return JSONResponse(status_code=502, content={"status": "error", "message": "Agify returned an invalid response"})
        
    if not nat_data.get("country"):
        return JSONResponse(status_code=502, content={"status": "error", "message": "Nationalize returned an invalid response"})

    # Classification Logic
    age = age_data["age"]
    if age <= 12:
        age_group = "child"
    elif age <= 19:
        age_group = "teenager"
    elif age <= 59:
        age_group = "adult"
    else:
        age_group = "senior"

    highest_prob_country = max(nat_data["country"], key=lambda x: x["probability"])

    # Create new record
    new_profile = Profile(
        id=str(uuid7()),
        name=name,
        gender=gender_data["gender"],
        gender_probability=gender_data["probability"],
        sample_size=gender_data["count"],
        age=age,
        age_group=age_group,
        country_id=highest_prob_country["country_id"],
        country_probability=highest_prob_country["probability"],
        created_at=datetime.now(timezone.utc)
    )

    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    # Format datetime exactly as requested: "2026-04-01T12:00:00Z"
    response_data = {col.name: getattr(new_profile, col.name) for col in new_profile.__table__.columns}
    response_data["created_at"] = response_data["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ")

    return {"status": "success", "data": response_data}

@app.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Profile not found"})
    
    data = {col.name: getattr(profile, col.name) for col in profile.__table__.columns}
    data["created_at"] = data["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"status": "success", "data": data}

@app.get("/api/profiles")
async def get_all_profiles(
    gender: str = Query(None), 
    country_id: str = Query(None), 
    age_group: str = Query(None), 
    db: Session = Depends(get_db)
):
    query = db.query(Profile)
    
    # Case-insensitive filtering
    if gender:
        query = query.filter(Profile.gender.ilike(gender))
    if country_id:
        query = query.filter(Profile.country_id.ilike(country_id))
    if age_group:
        query = query.filter(Profile.age_group.ilike(age_group))

    profiles = query.all()
    
    data_list = []
    for p in profiles:
        data_list.append({
            "id": p.id,
            "name": p.name,
            "gender": p.gender,
            "age": p.age,
            "age_group": p.age_group,
            "country_id": p.country_id
        })

    return {
        "status": "success",
        "count": len(data_list),
        "data": data_list
    }

@app.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Profile not found"})
    
    db.delete(profile)
    db.commit()
    return # Returns 204 No Content automatically via status_code decorator
