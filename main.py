from fastapi import FastAPI
from pydantic import BaseModel
from geopy.geocoders import Nominatim
import swisseph as swe
from openai import OpenAI

# ---------------- Configuration & Clients ----------------
XAI_API_KEY = "xai-ML7pxhaXyH9Fm2Jyhd6mmwXQS2xyR7g0AkFSxHMeut23Z3QTxoSTZ5499bd5Hv06gkVSWSj8ICJ5P3CF"
client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
geolocator = Nominatim(user_agent="astro_web")

# ---------------- Zodiac Metadata ----------------
HOUSES = [
    "1st House", "2nd House", "3rd House", "4th House", "5th House", "6th House",
    "7th House", "8th House", "9th House", "10th House", "11th House", "12th House"
]
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

# ---------------- Helper: Planetary Positions ----------------
def calculate_planetary_positions(date: str, time: str, latitude: float, longitude: float):
    year, month, day = map(int, date.split('-'))
    hour, minute = map(int, time.split(':'))
    decimal_time = hour + minute / 60.0
    jd = swe.julday(year, month, day, decimal_time)

    planets = [
        swe.SUN, swe.MOON, swe.MERCURY, swe.VENUS, swe.MARS,
        swe.JUPITER, swe.SATURN, swe.URANUS, swe.NEPTUNE, swe.PLUTO
    ]
    planet_names = [
        "Sun", "Moon", "Mercury", "Venus", "Mars",
        "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"
    ]

    positions = []
    for idx, planet in enumerate(planets):
        pos, _ = swe.calc_ut(jd, planet)
        house = int((pos[0] // 30) + 1)
        sign = SIGNS[int(pos[0] // 30)]
        positions.append({
            "planet": planet_names[idx],
            "degree": pos[0],
            "house": HOUSES[house - 1],
            "sign": sign
        })
    return positions

# ---------------- Request Models ----------------
class AstroRequest(BaseModel):
    date: str       # "YYYY-MM-DD"
    time: str       # "HH:MM"
    place: str      # e.g. "Mumbai"
    question: str   # User's question about their chart

class MatchRequest(BaseModel):
    boy_date: str
    boy_time: str
    boy_place: str
    girl_date: str
    girl_time: str
    girl_place: str

# ---------------- FastAPI Application ----------------
app = FastAPI()

@app.post("/astro")
def astro(req: AstroRequest):
    # Geocode user’s place
    location = geolocator.geocode(req.place)
    if not location:
        return {"error": "Place not found"}

    # Calculate planetary positions
    positions = calculate_planetary_positions(
        req.date, req.time, location.latitude, location.longitude
    )

    # Build prompt for Grok
    planetary_context = "\n".join([
        f"{p['planet']} is in {p['sign']} ({p['degree']}°) in the {p['house']}"
        for p in positions
    ])

    prompt = f"""
A user has asked the following question about their astrological chart: "{req.question}"

Astrological chart details:
{planetary_context}

Provide a concise answer in under 500 characters focused on areas like career, relationships, or life guidance.
Avoid including technical planetary positions in the response.
"""

    completion = client.chat.completions.create(
        model="grok-3-mini-beta",
        messages=[
            {"role": "system", "content": "You are an expert astrologer."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=800
    )
    answer = completion.choices[0].message.content.strip()

    return {"chart": positions, "answer": answer}

@app.post("/match")
def match(req: MatchRequest):
    # Geocode both places
    boy_loc = geolocator.geocode(req.boy_place)
    girl_loc = geolocator.geocode(req.girl_place)
    if not boy_loc or not girl_loc:
        return {"error": "Boy or girl place not found"}

    # Calculate both sets of positions
    boy_positions  = calculate_planetary_positions(
        req.boy_date, req.boy_time, boy_loc.latitude, boy_loc.longitude
    )
    girl_positions = calculate_planetary_positions(
        req.girl_date, req.girl_time, girl_loc.latitude, girl_loc.longitude
    )

    # Simple 36-point scoring
    score = 0
    for b, g in zip(boy_positions, girl_positions):
        if b['sign'] == g['sign']:
            score += 3
        elif b['house'] == g['house']:
            score += 2

    if   score >= 30:
        level = "Perfect Match"
    elif score >= 20:
        level = "Good Match"
    elif score >= 10:
        level = "Moderate Match"
    else:
        level = "Low Match"

    return {"score": score, "level": level}

# ---------------- Run locally ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)