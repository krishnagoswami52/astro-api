from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError
import swisseph as swe
from openai import OpenAI
from datetime import datetime
from typing import List, Dict
import logging

# Setup logging
tlogging = logging.getLogger("astro_match")
tlogging.setLevel(logging.INFO)

# ---------------- Configuration & Clients ----------------
XAI_API_KEY = "xai-ML7pxhaXyH9Fm2Jyhd6mmwXQS2xyR7g0AkFSxHMeut23Z3QTxoSTZ5499bd5Hv06gkVSWSj8ICJ5P3CF"
client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
geolocator = Nominatim(user_agent="astro_web", timeout=10)

# ---------------- Zodiac Metadata ----------------
HOUSES = [
    "1st House", "2nd House", "3rd House", "4th House", "5th House", "6th House",
    "7th House", "8th House", "9th House", "10th House", "11th House", "12th House"
]
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]
PLANETS = {
    swe.SUN: "Sun", swe.MOON: "Moon", swe.MERCURY: "Mercury", swe.VENUS: "Venus",
    swe.MARS: "Mars", swe.JUPITER: "Jupiter", swe.SATURN: "Saturn",
    swe.URANUS: "Uranus", swe.NEPTUNE: "Neptune", swe.PLUTO: "Pluto"
}

# Major aspect definitions: angle -> (score, orb)
ASPECTS = {
    0:   (5, 8),   # Conjunction
    60:  (3, 6),   # Sextile
    90:  (2, 8),   # Square
    120: (4, 8),   # Trine
    180: (1, 8)    # Opposition
}

# Allowed question keywords and banned profanity
ALLOWED_KEYWORDS = {
    "career", "relationship", "life", "future", "health", "finance",
    "love", "marriage", "compatibility", "job", "work", "success",
    "money", "wealth", "education", "travel", "family", "pregnancy",
    "children", "spouse", "dating", "breakup", "studies", "exam",
    "destiny", "luck", "fortune", "zodiac", "star", "moon", "sun",
    "mars", "jupiter"
}
BANNED_WORDS = {"chutiye", "fuck", "shit", "bitch", "asshole", "madarchod, mc, bc, bhosdike, gandu, mat, bana"}

# ---------------- Helper: Planetary Positions ----------------
def calculate_planetary_positions(date: str, time: str, latitude: float, longitude: float) -> List[Dict]:
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0)
    positions = []
    for planet, name in PLANETS.items():
        try:
            pos, _ = swe.calc_ut(jd, planet)
        except Exception as e:
            tlogging.error(f"Ephemeris error for {name}: {e}")
            raise HTTPException(status_code=502, detail="Error computing planetary positions")
        deg = pos[0] % 360
        idx = int(deg // 30)
        positions.append({
            "planet": name,
            "degree": round(deg, 2),
            "sign": SIGNS[idx],
            "house": HOUSES[idx]
        })
    return positions

# ---------------- Aspect Scoring ----------------
def compute_aspect_score(b_deg: float, g_deg: float) -> int:
    diff = abs(b_deg - g_deg) % 360
    angle = min(diff, 360 - diff)
    for asp, (score, orb) in ASPECTS.items():
        if abs(angle - asp) <= orb:
            return score
    return 0

# ---------------- Request Models ----------------
class AstroRequest(BaseModel):
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    place: str
    question: str

    @validator('date')
    def valid_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format")

    @validator('time')
    def valid_time(cls, v):
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            raise ValueError("time must be in HH:MM format")

class MatchRequest(BaseModel):
    boy_date: str
    boy_time: str
    boy_place: str
    girl_date: str
    girl_time: str
    girl_place: str

    @validator('boy_date', 'girl_date')
    def valid_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format")

    @validator('boy_time', 'girl_time')
    def valid_time(cls, v):
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            raise ValueError("time must be in HH:MM format")

# ---------------- FastAPI Application ----------------
app = FastAPI()

@app.post("/astro")
def astro(req: AstroRequest):
    # Profanity filter
    q_lower = req.question.lower()
    if any(b in q_lower for b in BANNED_WORDS):
        raise HTTPException(status_code=400, detail="Please avoid profanity in your question.")
    # Relevance check
    if not any(k in q_lower for k in ALLOWED_KEYWORDS):
        raise HTTPException(status_code=400, detail="Ask about career, love, health, or other astrology topics.")

    try:
        location = geolocator.geocode(req.place)
    except GeocoderServiceError:
        raise HTTPException(status_code=503, detail="Geocoding service unavailable")
    if not location:
        raise HTTPException(status_code=400, detail="Place not found")

    positions = calculate_planetary_positions(req.date, req.time, location.latitude, location.longitude)
    planetary_context = "\n".join([
        f"{p['planet']} in {p['sign']} ({p['degree']}°) in the {p['house']}"
        for p in positions
    ])

    prompt = f"""
A user asked: "{req.question}"\n
Chart:\n{planetary_context}
Provide a concise, actionable reading focused on career, relationship, or life guidance (max 500 chars)."""

    try:
        completion = client.chat.completions.create(
            model="grok-3-mini-beta",
            messages=[
                {"role": "system", "content": "You are an expert astrologer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=900
        )
    except Exception as e:
        tlogging.error(f"OpenAI API error: {e}")
        raise HTTPException(status_code=502, detail="Astrology AI service failed")

    answer = completion.choices[0].message.content.strip()
    return {"chart": positions, "answer": answer}

@app.post("/match")
def match(req: MatchRequest):
    try:
        boy_loc = geolocator.geocode(req.boy_place)
        girl_loc = geolocator.geocode(req.girl_place)
    except GeocoderServiceError:
        raise HTTPException(status_code=503, detail="Geocoding service unavailable")
    if not boy_loc or not girl_loc:
        raise HTTPException(status_code=400, detail="Boy or girl place not found")

    boy_pos = calculate_planetary_positions(req.boy_date, req.boy_time, boy_loc.latitude, boy_loc.longitude)
    girl_pos = calculate_planetary_positions(req.girl_date, req.girl_time, girl_loc.latitude, girl_loc.longitude)

    # Raw scoring
    raw_score = 0
    breakdown = []
    max_per_planet = 2 + 1 + max(score for score, _ in ASPECTS.values())
    for b, g in zip(boy_pos, girl_pos):
        s = 0
        if b['sign'] == g['sign']:
            s += 2
            breakdown.append(f"{b['planet']} same sign: +2")
        if b['house'] == g['house']:
            s += 1
            breakdown.append(f"{b['planet']} same house: +1")
        asp_s = compute_aspect_score(b['degree'], g['degree'])
        if asp_s:
            s += asp_s
            breakdown.append(f"{b['planet']} aspect score: +{asp_s}")
        raw_score += s

    # Scale to 36-point system
    max_score = len(boy_pos) * max_per_planet
    scaled_score = round(raw_score / max_score * 36)

    # Levels on 36-point scale
    if scaled_score >= 30:
        level = "Perfect Match"
    elif scaled_score >= 18:
        level = "Good Match"
    elif scaled_score >= 9:
        level = "Moderate Match"
    else:
        level = "Low Match"

    return {"score": scaled_score, "level": level, "breakdown": breakdown}

# ---------------- Run locally ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
