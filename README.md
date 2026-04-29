# Insighta Labs+ Backend Intelligence System

This is the core backend infrastructure for the Insighta Labs+ platform, built with FastAPI and PostgreSQL. It serves as the central intelligence hub, handling secure data processing, deterministic natural language search, and unified access control across multiple client interfaces (CLI and Web Portal).

## System Architecture

The system is built on a three-tier decoupled architecture:

1.  **Core API:** A Python/FastAPI backend deployed on Railway.
2.  **Database:** A managed PostgreSQL instance storing profile data and user role mappings.
3.  **Clients:** Separate frontend interfaces (Node.js CLI and Next.js Web Portal) consuming the unified REST API.

## Authentication & Security

The system utilizes a secure GitHub OAuth 2.0 flow combined with stateless JWTs:

- **OAuth Flow:** Clients initiate the authorization sequence via `/auth/github`. The backend registers the user, mints cryptographic JSON Web Tokens (JWTs), and redirects the client back to their native callback URL with the tokens.
- **Token Handling:** Access tokens are short-lived and signed with the `HS256` algorithm. The user's `sub` (UUID) and `role` are embedded directly into the token payload.
- **Role-Based Access Control (RBAC):** Enforcement happens at the endpoint level using FastAPI dependencies. A custom `RoleChecker` decodes the JWT and extracts the `role` claim. If the embedded role does not match the required clearance, the request is immediately rejected with a `403 Forbidden` response.

## Natural Language Query Parsing Approach

The `/api/profiles/search` endpoint utilizes a rule-based Natural Language Processing (NLP) engine powered by Regular Expressions (Regex) and the `pycountry` library. No AI or LLMs are used, ensuring deterministic and extremely fast execution.

### Logic Flow & Keyword Mapping

When a query string `q` is passed, the parser converts it to lowercase and tests it against predefined rules:

1. **Gender Mapping:** - Scans for female identifiers (`female`, `females`, `women`, `woman`, `girl`) -> applies `gender=female`.
   - Scans for male identifiers (`male`, `males`, `men`, `man`, `boy`) -> applies `gender=male`.
   - _Conflict Logic:_ If the query contains BOTH male and female keywords (e.g., "male and female teenagers"), the engine safely ignores the gender filter entirely.

2. **Age Group Keywords:**
   - `"young"` -> maps strictly to `min_age=16` and `max_age=24`.
   - `"teenager/teenagers"` -> maps to `age_group=teenager`.
   - `"adult/adults"` -> maps to `age_group=adult`.
   - `"senior/seniors"` -> maps to `age_group=senior`.
   - `"child/children"` -> maps to `age_group=child`.

3. **Explicit Age Bounds:**
   - Detects boundary words followed by a number (e.g., `above 30`, `over 18`, `> 25`) -> applies `min_age`.
   - Detects upper boundaries (e.g., `below 40`, `under 12`, `< 16`) -> applies `max_age`.

4. **Country Mapping:**
   - Iterates through the ISO-3166 country list via `pycountry`.
   - If a country's standard or official name appears in the query (e.g., "angola", "nigeria"), it dynamically extracts the exact 2-letter ISO code (e.g., `country_id=AO`, `country_id=NG`).

### Limitations & Edge Cases Handled

- **Complex Logic Operators:** The parser assumes `AND` logic for all extracted constraints. It cannot process `OR` logic natively (e.g., "people from nigeria OR kenya").
- **Uninterpretable Queries:** If no valid filters are extracted from the text, the parser safely aborts and returns an explicit `{"status": "error", "message": "Unable to interpret query"}`.
- **Ambiguous Countries:** The country scan requires an exact word match to prevent partial matching (e.g., "Chad" will only map if it appears as an isolated noun).

---

## Environment Setup

Create a `.env` file in the root directory with the following variables:

```env
DATABASE_URL=postgresql://user:pass@host:port/db
JWT_SECRET=your_cryptographic_secret
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
```
