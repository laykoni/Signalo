"""
Citizen Signals API with Media Upload Support (FIXED)
- Media is uploaded once to /upload-media -> returns media_ids
- /chat only receives media_ids (no base64) and attaches them on finalisation
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
import os
import json
import csv
import uuid
import base64
import shutil
from glob import glob
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

app = FastAPI()

# ✅ safer default: no credentials when allow_origins="*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if os.getenv("CORS_ALLOW_ORIGINS") else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set!")
    raise SystemExit(1)

claude = Anthropic(api_key=ANTHROPIC_API_KEY)

def load_prompt(filepath='prompt.txt'):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.startswith('"""'):
                content = content[3:]
            if content.endswith('"""'):
                content = content[:-3]
            print(f"✓ Loaded prompt from {filepath} ({len(content)} chars)")
            return content.strip()
    except FileNotFoundError:
        print(f"⚠ Prompt file not found: {filepath}, using default")
        return None

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

# ✅ temp folder for uploads before signal finalisation
TEMP_DIR = UPLOADS_DIR / "_temp"
TEMP_DIR.mkdir(exist_ok=True)

def load_organizations(csv_path='organizations.csv'):
    organizations = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get('0') or not row['0'].strip():
                    continue

                organizations.append({
                    'id': int(row['0']),
                    'name': row['org_name'].strip(),
                    'oblast': row.get('Област', '').strip() or None,
                    'obshtina': row.get('Община', '').strip() or None,
                    'grad': row.get('Град/село', '').strip() or None,
                    'rayon': row.get('Район', '').strip() or None,
                    'special_territory_type': row.get('special_territory_type', '').strip() or None,
                    'special_territory_name': row.get('special_territory_name', '').strip() or None
                })
        print(f"✓ Loaded {len(organizations)} organizations")
        return organizations
    except Exception as e:
        print(f"ERROR loading organizations: {e}")
        raise SystemExit(1)

ORGANIZATIONS = load_organizations()

def normalize_location(location: str) -> str:
    if not location:
        return ""
    return location.strip().lower()

def build_location_db_from_orgs():
    location_db = {}
    rayon_db = {}

    for org in ORGANIZATIONS:
        if org['grad']:
            city_key = normalize_location(org['grad'])
            if city_key not in location_db:
                location_db[city_key] = {
                    'oblast': org['oblast'],
                    'obshtina': org['obshtina'],
                    'grad': org['grad']
                }

        if org['rayon']:
            rayon_key = normalize_location(org['rayon'])
            if rayon_key not in rayon_db:
                rayon_db[rayon_key] = org['rayon']

    print(f"✓ Built dynamic location database: {len(location_db)} cities, {len(rayon_db)} rayons")
    return location_db, rayon_db

LOCATION_DB, RAYON_DB = build_location_db_from_orgs()

def location_matches(user_location: str, org_location: Optional[str]) -> bool:
    if org_location is None:
        return True

    if ';' in org_location or ',' in org_location:
        for sep in [';', ',']:
            if sep in org_location:
                org_locations = [normalize_location(loc) for loc in org_location.split(sep)]
                return normalize_location(user_location) in org_locations

    return normalize_location(user_location) == normalize_location(org_location)

def filter_organizations_by_location(oblast: Optional[str] = None,
                                     obshtina: Optional[str] = None,
                                     grad: Optional[str] = None,
                                     rayon: Optional[str] = None) -> List[Dict]:
    filtered = []

    for org in ORGANIZATIONS:
        if org['oblast'] is not None and oblast is not None:
            if not location_matches(oblast, org['oblast']):
                continue

        if obshtina is None:
            if org['obshtina'] is not None:
                continue
        else:
            if org['obshtina'] is not None:
                if not location_matches(obshtina, org['obshtina']):
                    continue

        if grad is None:
            if org['grad'] is not None:
                continue
        else:
            if org['grad'] is not None:
                if not location_matches(grad, org['grad']):
                    continue

        if rayon is None:
            if org['rayon'] is not None:
                continue
        else:
            if org['rayon'] is not None:
                if not location_matches(rayon, org['rayon']):
                    continue

        filtered.append(org)

    print(f"✓ Filtered to {len(filtered)} organizations for: {oblast}/{obshtina}/{grad}/{rayon}")
    return filtered

def extract_location_from_messages(messages: List[Dict]) -> Optional[Dict[str, str]]:
    for msg in reversed(messages[-6:]):
        content = msg['content'].lower()
        for city_key, loc_data in LOCATION_DB.items():
            if city_key in content:
                result = loc_data.copy()
                for rayon_key, rayon_value in RAYON_DB.items():
                    if rayon_key in content:
                        result['rayon'] = rayon_value
                        print(f"✓ Extracted location: {result}")
                        return result
                print(f"✓ Extracted location (no rayon): {result}")
                return result
    return None

def create_org_list_text(organizations: List[Dict]) -> str:
    return "\n".join([f"{org['id']}. {org['name']}" for org in organizations])

BASE_SYSTEM_PROMPT = load_prompt('prompt.txt')
if not BASE_SYSTEM_PROMPT:
    BASE_SYSTEM_PROMPT = """Ти си асистент за подаване на граждански сигнали към българските държавни институции.
    
ТВОЯТА ЦЕЛ: Да събереш информация за сигнала и да го изпратиш до правилната институция.

Питай за: КЪДЕ (местоположение), КАКВО (проблем), КОГА (време).
След като имаш достатъчно информация, попитай "Да изпратя ли сигнала?" и генерирай JSON."""
    print("⚠ Using fallback prompt")

def build_system_prompt_with_orgs(organizations: List[Dict], media_count: int = 0) -> str:
    org_list = create_org_list_text(organizations)

    media_note = ""
    if media_count > 0:
        media_note = f"\n\n📎 ЗАБЕЛЕЖКА: Потребителят е прикачил {media_count} файл{'а' if media_count > 1 else ''} (снимки/видеа) към този сигнал. Тези файлове ще бъдат изпратени заедно със сигнала."

    return f"""{BASE_SYSTEM_PROMPT}{media_note}

СПИСЪК НА ИНСТИТУЦИИ ЗА ТОВА МЕСТОПОЛОЖЕНИЕ (ИЗБИРАЙ САМО ОТ ТЕЗИ):
{org_list}

КРИТИЧНО ВАЖНИ ПРАВИЛА ЗА ИЗБОР НА ИНСТИТУЦИЯ:
- ТРЯБВА да избереш САМО организация от горния списък
- Върни ТОЧНО agency_id (числото) и agency (името) както са изписани в списъка
- КОПИРАЙ ТОЧНО името и ID-то от списъка - не измисляй!
"""

def extract_json_from_text(text: str) -> Optional[dict]:
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > start:
            json_str = text[start:end]
            return json.loads(json_str)
    except:
        pass
    return None

def validate_agency_id(agency_id, filtered_orgs):
    if agency_id is None:
        return False
    return any(org['id'] == agency_id for org in filtered_orgs)

# -------------------------
# Media: upload once -> IDs
# -------------------------

class MediaItem(BaseModel):
    type: str  # 'image' or 'video'
    filename: str
    mime_type: str
    data: str  # base64 encoded dataURL
    size: int

class MediaUploadRequest(BaseModel):
    media: List[MediaItem]

@app.post("/upload-media")
async def upload_media(req: MediaUploadRequest):
    batch_id = uuid.uuid4().hex[:8]
    batch_dir = TEMP_DIR / batch_id
    batch_dir.mkdir(exist_ok=True)

    items = []
    for i, media in enumerate(req.media):
        data = media.data
        if ',' in data:
            data = data.split(',')[1]

        file_bytes = base64.b64decode(data)
        original_filename = media.filename or "file"
        ext = original_filename.split('.')[-1] if '.' in original_filename else 'bin'

        if media.type == 'image' and ext.lower() not in ['jpg','jpeg','png','gif','webp','bmp']:
            ext = 'jpg'
        if media.type == 'video' and ext.lower() not in ['mp4','mov','avi','webm','mkv']:
            ext = 'mp4'

        media_id = f"m_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        stored_name = f"{media.type}_{i+1}_{media_id}.{ext}"
        path = batch_dir / stored_name

        with open(path, "wb") as f:
            f.write(file_bytes)

        items.append({
            "media_id": media_id,
            "type": media.type,
            "filename": original_filename,
            "mime_type": media.mime_type,
            "size": len(file_bytes),
        })

    return {"items": items}

def attach_temp_media_to_signal(media_ids: List[str], signal_id: str) -> List[Dict]:
    signal_dir = UPLOADS_DIR / signal_id
    signal_dir.mkdir(exist_ok=True)

    saved = []
    for mid in media_ids:
        matches = glob(str(TEMP_DIR / "*" / f"*{mid}*"))
        if not matches:
            continue

        src = Path(matches[0])
        dst = signal_dir / src.name
        shutil.move(str(src), str(dst))

        saved.append({
            "media_id": mid,
            "filename": dst.name
        })

    return saved

# -------------------------
# Chat models & endpoint
# -------------------------

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    location_context: Optional[Dict[str, str]] = None
    media_ids: Optional[List[str]] = None  # ✅ NEW

@app.post("/chat")
async def chat(request: ChatRequest):
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    media_ids = request.media_ids or []
    has_media = len(media_ids) > 0
    media_count = len(media_ids)

    location_context = request.location_context or extract_location_from_messages(messages)

    if location_context:
        filtered_orgs = filter_organizations_by_location(
            oblast=location_context.get('oblast'),
            obshtina=location_context.get('obshtina'),
            grad=location_context.get('grad'),
            rayon=location_context.get('rayon')
        )
        system_prompt = build_system_prompt_with_orgs(filtered_orgs, media_count)
    else:
        filtered_orgs = ORGANIZATIONS
        system_prompt = BASE_SYSTEM_PROMPT + "\n\n(Списъкът на институциите ще бъде предоставен след като разбера местоположението)"
        if has_media:
            system_prompt += f"\n\n📎 ЗАБЕЛЕЖКА: Потребителят е прикачил {media_count} файла (снимки/видеа)."

    try:
        response = claude.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            system=[
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ],
            messages=messages
        )

        assistant_message = response.content[0].text
        signal_data = extract_json_from_text(assistant_message)

        # Finalise if JSON with minimum required fields exists
        if signal_data and all(k in signal_data for k in ['title', 'description', 'agency']):
            signal_id = f"signal_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

            saved_media = []
            if has_media:
                saved_media = attach_temp_media_to_signal(media_ids, signal_id)
                signal_data['attached_media'] = saved_media

            # Validate agency if possible
            if 'location' in signal_data:
                loc = signal_data['location']
                final_filtered_orgs = filter_organizations_by_location(
                    oblast=loc.get('oblast'),
                    obshtina=loc.get('obshtina'),
                    grad=loc.get('grad'),
                    rayon=loc.get('rayon')
                )
                if 'agency_id' in signal_data:
                    if not validate_agency_id(signal_data['agency_id'], final_filtered_orgs):
                        signal_data['validation_warning'] = f"Invalid agency_id {signal_data.get('agency_id')} for location"
                else:
                    signal_data['validation_warning'] = "Missing agency_id"

            signal_data['signal_id'] = signal_id

            return {
                "signal_ready": True,
                "signal_sent": True,
                "signal_data": signal_data,
                "message": "Сигналът беше изпратен успешно! Благодарим ви.",
                "filtered_org_count": len(filtered_orgs),
                "attached_media_count": len(saved_media),
                "conversation_ended": True
            }

        return {
            "signal_ready": False,
            "signal_sent": False,
            "message": assistant_message,
            "filtered_org_count": len(filtered_orgs) if location_context else None,
            "location_context": location_context,
            "pending_media_count": media_count
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        return {
            "signal_ready": False,
            "signal_sent": False,
            "message": "Съжалявам, възникна грешка. Моля опитайте отново."
        }

@app.get("/health")
def health():
    return {
        "status": "running",
        "organizations_loaded": len(ORGANIZATIONS),
        "cities_supported": len(LOCATION_DB),
        "rayons_supported": len(RAYON_DB),
        "uploads_dir": str(UPLOADS_DIR.absolute())
    }
