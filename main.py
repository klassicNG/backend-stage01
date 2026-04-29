from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi.responses import RedirectResponse
import httpx
from uuid6 import uuid7  # The TRD strictly requires UUID v7 for users
from datetime import datetime, timezone
import jwt
from datetime import datetime, timedelta, timezone
import httpx
from uuid_extensions import uuid7 # or however you import your UUID7 generator
import math
from sqlalchemy import Boolean
import time
import logging
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
from dotenv import load_dotenv

load_dotenv()  # This actively searches for the .env file and loads the variables

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

class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, index=True)
    github_id = Column(String(255), unique=True, index=True)
    username = Column(String(255))
    email = Column(String(255))
    avatar_url = Column(String(255))
    role = Column(String(50), default="analyst") # admin or analyst
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))

# --- AUTHENTICATION UTILITIES ---
JWT_SECRET = os.getenv("JWT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
ALGORITHM = "HS256"

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=3)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        # Crack open the token to read the payload
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Verify the user actually exists in the database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user



Base.metadata.create_all(bind=engine)



# --- 2. FASTAPI APP & CORS ---
app = FastAPI()

@app.get("/auth/github")
async def github_login():
    # Redirect the user to GitHub to grant permission
    github_auth_url = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&scope=read:user user:email"
    return RedirectResponse(github_auth_url)


@app.get("/auth/github/callback")
async def github_callback(code: str, db: Session = Depends(get_db)):
    # 1. Exchange the code for a GitHub access token
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code
            }
        )
        token_data = token_res.json()
        github_access_token = token_data.get("access_token")

        if not github_access_token:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Failed to authenticate with GitHub"})

        # 2. Use the token to fetch the user's GitHub profile
        user_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_access_token}"}
        )
        github_user = user_res.json()

        # 3. Check if we already have this user in our database
        github_id = str(github_user["id"])
        db_user = db.query(User).filter(User.github_id == github_id).first()

        if not db_user:
            # First time login - create new user
            db_user = User(
                id=str(uuid7()),
                github_id=github_id,
                username=github_user.get("login"),
                email=github_user.get("email"),
                avatar_url=github_user.get("avatar_url"),
                role="analyst", # Default role as per TRD
                created_at=datetime.now(timezone.utc),
                last_login_at=datetime.now(timezone.utc)
            )
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
        else:
            # Returning user - update last login
            db_user.last_login_at = datetime.now(timezone.utc)
            db.commit()

        # 4. Generate our own system tokens
        token_payload = {"sub": db_user.id, "role": db_user.role}
        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        return {
            "status": "success",
            "access_token": access_token,
            "refresh_token": refresh_token
        }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Set up standard logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insighta_logger")

@app.middleware("http")
async def system_middleware(request: Request, call_next):
    start_time = time.time()

    # 1. API Versioning Check (Only enforce on /api/ routes)
    if request.url.path.startswith("/api/"):
        if request.headers.get("X-API-Version") != "1":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "API version header required"}
            )

    # 2. Process Request
    response = await call_next(request)

    # 3. Request Logging
    process_time = time.time() - start_time
    logger.info(f"Method: {request.method} | Endpoint: {request.url.path} | Status: {response.status_code} | Time: {process_time:.4f}s")

    return response


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

@app.get("/api/users/me")
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return {
        "status": "success",
        "data": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "role": current_user.role
        }
    }

@app.get("/api/profiles")
async def get_all_profiles(
    request: Request, # <-- Added this
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

    # --- THE NEW PAGINATION SHAPE ---
    total_pages = math.ceil(total / limit) if total > 0 else 1
    base_path = request.url.path

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": {
            "self": f"{base_path}?page={page}&limit={limit}",
            "next": f"{base_path}?page={page+1}&limit={limit}" if page < total_pages else None,
            "prev": f"{base_path}?page={page-1}&limit={limit}" if page > 1 else None
        },
        "data": [format_profile(p) for p in profiles]
    }    

@app.get("/api/profiles/search")
async def search_profiles(
    request: Request, # <-- Added this
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

    # --- THE NEW PAGINATION SHAPE ---
    total_pages = math.ceil(total / limit) if total > 0 else 1
    base_path = request.url.path

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": {
            "self": f"{base_path}?page={page}&limit={limit}",
            "next": f"{base_path}?page={page+1}&limit={limit}" if page < total_pages else None,
            "prev": f"{base_path}?page={page-1}&limit={limit}" if page > 1 else None
        },
        "data": [format_profile(p) for p in profiles]
    }