import os
import re
from fastapi import FastAPI, HTTPException, Request, Depends, Query, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, asc, desc
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
from uuid_extensions import uuid7
import pycountry

# --- 1. DATABASE SETUP ---
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    gender = Column(String(50))
    gender_probability = Column(Float)
    age = Column(Integer)
    age_group = Column(String(50))
    country_id = Column(String(2))
    country_name = Column(String(255))
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
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 3. CUSTOM ERROR HANDLING ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid query parameters"}
    )

# --- 4. NLP PARSING ENGINE ---
def parse_nl_query(q: str):
    q = q.lower()
    filters = {}

    # 1. Gender 
    has_female = bool(re.search(r'\b(female|females|women|woman|girl|girls)\b', q))
    has_male = bool(re.search(r'\b(male|males|men|man|boy|boys)\b', q))
    
    # Only filter if one is exclusively mentioned. "Male and female" cancels out.
    if has_female and not has_male:
        filters["gender"] = "female"
    elif has_male and not has_female:
        filters["gender"] = "male"

    # 2. Age Descriptors & Groups
    if re.search(r'\byoung\b', q):
        filters["min_age"] = 16
        filters["max_age"] = 24
    if re.search(r'\bteenagers?\b', q):
        filters["age_group"] = "teenager"
    if re.search(r'\badults?\b', q):
        filters["age_group"] = "adult"
    if re.search(r'\bseniors?\b', q):
        filters["age_group"] = "senior"
    if re.search(r'\bchild(ren)?\b', q):
        filters["age_group"] = "child"

    # 3. Explicit Age Ranges
    above_match = re.search(r'(above|over|>)\s*(\d+)', q)
    if above_match:
        filters["min_age"] = int(above_match.group(2))

    below_match = re.search(r'(below|under|<)\s*(\d+)', q)
    if below_match:
        filters["max_age"] = int(below_match.group(2))

    # 4. Country Extraction
    for country in pycountry.countries:
        # Match standard name or official name
        if re.search(r'\b' + re.escape(country.name.lower()) + r'\b', q) or \
           (hasattr(country, 'official_name') and re.search(r'\b' + re.escape(country.official_name.lower()) + r'\b', q)):
            filters["country_id"] = country.alpha_2
            break

    if not filters:
        return None
    return filters

# --- 5. ENDPOINTS ---

def format_profile(p):
    return {
        "id": p.id,
        "name": p.name,
        "gender": p.gender,
        "gender_probability": p.gender_probability,
        "age": p.age,
        "age_group": p.age_group,
        "country_id": p.country_id,
        "country_name": p.country_name,
        "country_probability": p.country_probability,
        "created_at": p.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if p.created_at else None
    }

def apply_filters(query, params):
    if params.get("gender"):
        query = query.filter(Profile.gender.ilike(params["gender"]))
    if params.get("age_group"):
        query = query.filter(Profile.age_group.ilike(params["age_group"]))
    if params.get("country_id"):
        query = query.filter(Profile.country_id.ilike(params["country_id"]))
    if params.get("min_age") is not None:
        query = query.filter(Profile.age >= params["min_age"])
    if params.get("max_age") is not None:
        query = query.filter(Profile.age <= params["max_age"])
    if params.get("min_gender_probability") is not None:
        query = query.filter(Profile.gender_probability >= params["min_gender_probability"])
    if params.get("min_country_probability") is not None:
        query = query.filter(Profile.country_probability >= params["min_country_probability"])
    return query

@app.get("/api/profiles")
async def get_all_profiles(
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    country_id: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = "asc",
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    q = db.query(Profile)
    
    # 1. Apply Filters
    filter_params = {
        "gender": gender, "age_group": age_group, "country_id": country_id,
        "min_age": min_age, "max_age": max_age, 
        "min_gender_probability": min_gender_probability, "min_country_probability": min_country_probability
    }
    q = apply_filters(q, filter_params)

    # 2. Sorting
    if sort_by in ["age", "created_at", "gender_probability"]:
        col = getattr(Profile, sort_by)
        q = q.order_by(desc(col) if order.lower() == "desc" else asc(col))

    # 3. Pagination & Count
    total = q.count()
    profiles = q.offset((page - 1) * limit).limit(limit).all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [format_profile(p) for p in profiles]
    }

@app.get("/api/profiles/search")
async def search_profiles(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    if not q or not q.strip():
        return JSONResponse(status_code=400, content={"status": "error", "message": "Missing or empty parameter"})

    filters = parse_nl_query(q)
    if not filters:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Unable to interpret query"})

    query = db.query(Profile)
    query = apply_filters(query, filters)
    
    total = query.count()
    profiles = query.offset((page - 1) * limit).limit(limit).all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [format_profile(p) for p in profiles]
    }
