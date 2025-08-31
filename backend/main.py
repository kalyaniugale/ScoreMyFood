from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
import io, traceback, re
import numpy as np
import easyocr

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Config ----------
ALLERGENS = [
    "milk","soy","soya","wheat","gluten","egg","peanut","peanuts","tree nuts","almond","cashew",
    "sesame","mustard","fish","shellfish","crustacean","shrimp","prawn","celery","lupin",
    "sulphite","sulfite"
]
ADDITIVE_NAMES = {
    "621":"Monosodium glutamate (MSG)",
    "622":"Monopotassium glutamate",
    "623":"Calcium diglutamate",
    "624":"Monoammonium glutamate",
    "625":"Magnesium diglutamate",
    "627":"Disodium guanylate",
    "631":"Disodium inosinate",
    "296":"Malic acid",
    "330":"Citric acid",
    "331":"Sodium citrates",
    "471":"Mono-/diglycerides of fatty acids",
    "327":"Calcium lactate",
    "170":"Calcium carbonate",
}
MSG_LIKE = {"621","622","623","624","625","627","631"}

# ---------- Helpers ----------
def _norm(s: str) -> str:
    s = s.replace("\n", " ")
    s = re.sub(r"[\u2010-\u2015]", "-", s)  # fancy dashes -> '-'
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _find_section(text: str, start_keys, end_keys):
    t = _norm(text)
    start_re = re.compile(r"(?i)" + r"|".join([k.replace(" ", r"\s*") for k in start_keys]))
    m = start_re.search(t)
    if not m:
        return ""
    start = m.end()
    end = len(t)
    for k in end_keys:
        mm = re.search(r"(?i)" + k.replace(" ", r"\s*"), t[start:])
        if mm:
            end = start + mm.start()
            break
    return t[start:end].strip(" :.-")

def _split_top_level_commas(s: str):
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch == "(": depth += 1
        elif ch == ")": depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part: parts.append(part)
            buf = []
        else:
            buf.append(ch)
    last = "".join(buf).strip()
    if last: parts.append(last)
    return parts

def parse_ingredients(full_text: str):
    # 1) grab INGREDIENTS block
    ingredients_block = _find_section(
        full_text,
        start_keys=["ingredients", "ingredient", "ingedients", "ingr edients", "in gredients"],
        end_keys=["allergen", "allergy", "nutrition", "nutritional", "nutri tion", "storage"]
    )

    items = []
    if ingredients_block:
        for tok in _split_top_level_commas(ingredients_block):
            tok = tok.strip(" .;")
            # percent (outer)
            m = re.search(r"(?i)\b(\d{1,3}(?:\.\d+)?)\s*%", tok)
            pct = float(m.group(1)) if m else None
            name = re.sub(r"\((\d{1,3}(?:\.\d+)?)\s*%\)", "", tok).strip()
            name = name.strip(" ()")
            if name:
                items.append({"name": name, "percent": pct})

    # 2) allergens (from 'ALLERGEN ...: Contains ...' or 'Contains ...' sentences)
    low = full_text.lower()
    allergens = set()
    m_all = re.search(r"(?i)allergen[^:]*:\s*([^.\n]+)", full_text)
    if m_all:
        chunk = m_all.group(1).lower()
        for w in re.split(r"[,\s;/]+", chunk):
            w = w.strip().rstrip(".")
            if w in ALLERGENS: allergens.add(w)
    for a in ALLERGENS:
        if re.search(r"\bcontains\b[^.]*\b" + re.escape(a) + r"s?\b", low):
            allergens.add(a)

    # 3) additive codes (E/INS or bare 3-digit)
    codes = re.findall(r"\b(?:e|ins)?\s*(\d{3})(?:\s*\([^)]+\))?", low)
    additives = [{"code": c, "name": ADDITIVE_NAMES.get(c)} for c in dict.fromkeys(codes)]  # dedupe, keep order

    # 4) quick flags for scoring
    flags = {
        "palmOil": bool(re.search(r"\bpalm(olein| oil)?\b", low)),
        "addedSugar": "sugar" in low or "corn syrup" in low or "glucose" in low,
        "addedSalt": "salt" in low,
        "msgLikeEnhancer": any(c in MSG_LIKE for c in codes),
        "artificialFlavour": bool(re.search(r"nature identical|artificial flavour|flavouring substances", low)),
    }

    return {
        "ingredients": items,
        "allergens": sorted(allergens),
        "additives": additives,
        "flags": flags,
    }

# ---------- OCR ----------
reader = easyocr.Reader(["en"], gpu=False)

@app.get("/")
def root():
    return {"ok": True, "msg": "OCR server running"}

def _ocr_bytes(image_bytes: bytes):
    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    res = reader.readtext(arr)
    lines = [{"text": t, "confidence": float(c)} for (_, t, c) in res]
    full = "\n".join(x["text"] for x in lines)
    return lines, full

@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        lines, full_text = _ocr_bytes(image_bytes)
        structured = parse_ingredients(full_text)
        return {"lines": lines, "fullText": full_text, "structured": structured}
    except UnidentifiedImageError:
        return JSONResponse(status_code=400, content={"error": "Not a valid image file"})
    except Exception as e:
        print("OCR error:", e); traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/ocr-bytes")
async def ocr_bytes(request: Request):
    try:
        image_bytes = await request.body()
        lines, full_text = _ocr_bytes(image_bytes)
        structured = parse_ingredients(full_text)
        return {"lines": lines, "fullText": full_text, "structured": structured}
    except UnidentifiedImageError:
        return JSONResponse(status_code=400, content={"error": "Not a valid image file"})
    except Exception as e:
        print("OCR error:", e); traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})
