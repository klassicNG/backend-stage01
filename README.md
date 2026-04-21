# Backend Wizards — Stage 2 Assessment

## Natural Language Query Parsing Approach
The `/api/profiles/search` endpoint utilizes a rule-based Natural Language Processing (NLP) engine powered by Regular Expressions (Regex) and the `pycountry` library. No AI or LLMs are used, ensuring deterministic and fast execution.

### Logic Flow & Keyword Mapping
When a query string `q` is passed, the parser converts it to lowercase and tests it against predefined rules:

1. **Gender Mapping:** - Scans for female identifiers (`female`, `females`, `women`, `woman`, `girl`) -> `gender=female`.
   - Scans for male identifiers (`male`, `males`, `men`, `man`, `boy`) -> `gender=male`.
   - *Conflict Logic:* If the query contains BOTH male and female keywords (e.g., "male and female teenagers"), the engine ignores the gender filter entirely.
2. **Age Group Keywords:**
   - `"young"` -> maps strictly to `min_age=16` and `max_age=24`.
   - `"teenager/teenagers"` -> `age_group=teenager`.
   - `"adult/adults"` -> `age_group=adult`.
   - `"senior/seniors"` -> `age_group=senior`.
   - `"child/children"` -> `age_group=child`.
3. **Explicit Age Bounds:**
   - Detects boundary words followed by a number (e.g., `above 30`, `over 18`, `> 25`) -> applies `min_age`.
   - Detects upper boundaries (e.g., `below 40`, `under 12`, `< 16`) -> applies `max_age`.
4. **Country Mapping:**
   - Iterates through the ISO-3166 country list via `pycountry`.
   - If a country's standard name or official name appears in the query (e.g., "angola", "nigeria"), it dynamically extracts the exact 2-letter ISO code (`country_id=AO`, `country_id=NG`).

### Limitations & Edge Cases Handled
- **Complex Logic Operators:** The parser assumes `AND` logic for all extracted constraints. It cannot process `OR` logic natively (e.g., "people from nigeria OR kenya").
- **Uninterpretable Queries:** If no valid filters are extracted from the text, the parser safely aborts and returns an explicit `{"status": "error", "message": "Unable to interpret query"}`.
- **Ambiguous Countries:** The country scan requires an exact word match to prevent partial matching (e.g., "Chad" will only map if it appears as an isolated noun).
