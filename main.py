"""
Citizen Signals API with Media Upload Support
Media is saved ONLY when signal is finalized (JSON detected)
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
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set!")
    exit(1)

print(f"✓ API Key loaded: {ANTHROPIC_API_KEY[:20]}...")
claude = Anthropic(api_key=ANTHROPIC_API_KEY)

# Load system prompt from file
def load_prompt(filepath='prompt.txt'):
    """Load the system prompt from an external file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Remove the triple quotes if present (from Python docstring format)
            if content.startswith('"""'):
                content = content[3:]
            if content.endswith('"""'):
                content = content[:-3]
            print(f"✓ Loaded prompt from {filepath} ({len(content)} chars)")
            return content.strip()
    except FileNotFoundError:
        print(f"⚠ Prompt file not found: {filepath}, using default")
        return None

# Create uploads directory for storing media files
UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)
print(f"✓ Uploads directory: {UPLOADS_DIR.absolute()}")

def load_organizations(csv_path='organizations.csv'):
    """Load organizations from CSV file"""
    organizations = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row['0'] or not row['0'].strip():
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
        exit(1)

ORGANIZATIONS = load_organizations()

def normalize_location(location: str) -> str:
    """Normalize location names for comparison"""
    if not location:
        return ""
    return location.strip().lower()

def build_location_db_from_orgs():
    """Build location database dynamically from loaded organizations"""
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
    """Check if organization's location field matches user's location"""
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
    """Filter organizations based on hierarchical location logic"""
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
    """Extract location from conversation using dynamic pattern matching"""
    
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
    """Create formatted list of organizations for the system prompt"""
    org_lines = []
    for org in organizations:
        org_lines.append(f"{org['id']}. {org['name']}")
    return "\n".join(org_lines)

# Load the base system prompt from file (or use fallback)
BASE_SYSTEM_PROMPT = load_prompt('prompt.txt')

if not BASE_SYSTEM_PROMPT:
    BASE_SYSTEM_PROMPT = """Ти си асистент за подаване на граждански сигнали към българските държавни институции.
    
ТВОЯТА ЦЕЛ: Да събереш информация за сигнала и да го изпратиш до правилната институция.

Питай за: КЪДЕ (местоположение), КАКВО (проблем), КОГА (време).
След като имаш достатъчно информация, попитай "Да изпратя ли сигнала?" и генерирай JSON."""
    print("⚠ Using fallback prompt")


def build_system_prompt_with_orgs(organizations: List[Dict], media_count: int = 0) -> str:
    """Build complete system prompt with filtered organization list"""
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
- За проблеми в конкретен район на град (напр. "район Западен"), избери районната администрация ако има такава в списъка и тя би била отговорната за този сигнал
- Ако няма районна администрация, избери администрацията на града/селото
- За проблеми на ниво област, избери областната администрация

ПРИМЕРИ:
- Проблем в "Пловдив, район Западен" → Избери "Община Пловдив - Район Западен" (ID 336)
- Проблем в "София, район Лозенец" → Избери "Столична община - Район Лозенец"  
- Проблем в "Варна" (без район) → Избери "Община Варна" """

def extract_json_from_text(text: str) -> dict:
    """Try to extract JSON from Claude's response"""
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
    """Check if agency_id exists in our filtered organizations list"""
    if agency_id is None:
        return False
    return any(org['id'] == agency_id for org in filtered_orgs)

def save_media_files(media_list: List[Dict], signal_id: str) -> List[Dict]:
    """Save uploaded media files and return metadata"""
    saved_files = []
    
    signal_dir = UPLOADS_DIR / signal_id
    signal_dir.mkdir(exist_ok=True)
    
    for i, media in enumerate(media_list):
        try:
            # Extract base64 data
            data = media.get('data', '')
            if ',' in data:
                # Remove data URL prefix like "data:image/jpeg;base64,"
                data = data.split(',')[1]
            
            # Decode
            file_bytes = base64.b64decode(data)
            
            # Generate filename with proper extension
            original_filename = media.get('filename', 'file')
            ext = original_filename.split('.')[-1] if '.' in original_filename else 'bin'
            
            # Ensure proper extension based on type
            if media['type'] == 'image' and ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                ext = 'jpg'
            elif media['type'] == 'video' and ext.lower() not in ['mp4', 'mov', 'avi', 'webm', 'mkv']:
                ext = 'mp4'
            
            filename = f"{media['type']}_{i+1}_{uuid.uuid4().hex[:8]}.{ext}"
            filepath = signal_dir / filename
            
            # Save file
            with open(filepath, 'wb') as f:
                f.write(file_bytes)
            
            saved_files.append({
                'filename': filename,
                'original_name': original_filename,
                'type': media['type'],
                'mime_type': media.get('mime_type', ''),
                'size': len(file_bytes),
                'path': str(filepath.absolute())
            })
            
            print(f"✓ Saved media file: {filepath} ({len(file_bytes)} bytes)")
            
        except Exception as e:
            print(f"❌ Error saving media file: {e}")
            import traceback
            traceback.print_exc()
    
    return saved_files


# Pydantic models
class MediaItem(BaseModel):
    type: str  # 'image' or 'video'
    filename: str
    mime_type: str
    data: str  # base64 encoded
    size: int

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    location_context: Optional[Dict[str, str]] = None
    media: Optional[List[MediaItem]] = None


@app.post("/chat")
async def chat(request: ChatRequest):
    """Handle chat conversation with location-based organization filtering and media support"""
    
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    # Check if media was uploaded
    has_media = request.media and len(request.media) > 0
    media_count = len(request.media) if has_media else 0
    
    if has_media:
        print(f"✓ Received {media_count} media files in request")
        for i, m in enumerate(request.media):
            print(f"  - File {i+1}: {m.filename} ({m.type}, {m.size} bytes)")
    
    # Try to extract location
    location_context = request.location_context or extract_location_from_messages(messages)
    
    # Filter organizations based on location
    if location_context:
        filtered_orgs = filter_organizations_by_location(
            oblast=location_context.get('oblast'),
            obshtina=location_context.get('obshtina'),
            grad=location_context.get('grad'),
            rayon=location_context.get('rayon')
        )
        system_prompt = build_system_prompt_with_orgs(filtered_orgs, media_count)
        print(f"✓ Using filtered list with {len(filtered_orgs)} organizations")
    else:
        filtered_orgs = ORGANIZATIONS
        system_prompt = BASE_SYSTEM_PROMPT + "\n\n(Списъкът на институциите ще бъде предоставен след като разбера местоположението)"
        if has_media:
            system_prompt += f"\n\n📎 ЗАБЕЛЕЖКА: Потребителят е прикачил {media_count} файла (снимки/видеа)."
        print("⚠ No location context - using all organizations")
    
    try:
        response = claude.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=messages
        )
        
        assistant_message = response.content[0].text
        signal_data = extract_json_from_text(assistant_message)
        
        # Check if signal is ready (JSON detected with required fields)
        if signal_data and all(k in signal_data for k in ['title', 'description', 'agency']):
            # Generate signal ID
            signal_id = f"signal_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            
            # *** THIS IS WHERE WE SAVE THE MEDIA - ONLY WHEN SIGNAL IS FINALIZED ***
            saved_media = []
            if has_media:
                print(f"📁 Signal ready! Saving {media_count} media files...")
                saved_media = save_media_files(
                    [m.model_dump() for m in request.media],
                    signal_id
                )
                signal_data['attached_media'] = saved_media
                print(f"✓ Saved {len(saved_media)} media files for signal {signal_id}")
            else:
                print("📁 Signal ready! No media files to save.")
            
            # Validate agency
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
                        print(f"❌ ERROR: Invalid agency_id {signal_data['agency_id']} for location {loc}")
                        signal_data['validation_warning'] = f"Invalid agency_id {signal_data['agency_id']} for location"
                    else:
                        print(f"✓ Valid agency_id {signal_data['agency_id']}")
                else:
                    signal_data['validation_warning'] = "Missing agency_id"
            
            # Add signal ID
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
        else:
            # Signal not ready yet - continue conversation
            # Media is NOT saved yet, just tracked
            return {
                "signal_ready": False,
                "signal_sent": False,
                "message": assistant_message,
                "filtered_org_count": len(filtered_orgs) if location_context else None,
                "location_context": location_context,
                "pending_media_count": media_count  # Let frontend know we're tracking media
            }
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "signal_ready": False,
            "signal_sent": False,
            "message": "Съжалявам, възникна грешка. Моля опитайте отново."
        }

@app.post("/filter-organizations")
async def filter_orgs(location: Dict[str, Optional[str]]):
    """Endpoint to manually filter organizations by location"""
    filtered = filter_organizations_by_location(
        oblast=location.get('oblast'),
        obshtina=location.get('obshtina'),
        grad=location.get('grad'),
        rayon=location.get('rayon')
    )
    
    return {
        "count": len(filtered),
        "organizations": filtered
    }

@app.get("/")
def root():
    return {
        "message": "Citizen Signals Chat API with Media Upload Support", 
        "status": "running",
        "organizations_loaded": len(ORGANIZATIONS),
        "cities_supported": len(LOCATION_DB),
        "rayons_supported": len(RAYON_DB),
        "uploads_dir": str(UPLOADS_DIR.absolute())
    }

@app.get("/organizations")
def get_organizations():
    """Get list of all organizations"""
    return {
        "organizations": ORGANIZATIONS,
        "count": len(ORGANIZATIONS)
    }

@app.get("/locations")
def get_locations():
    """Get list of all supported locations"""
    return {
        "cities": list(LOCATION_DB.keys()),
        "rayons": list(RAYON_DB.keys()),
        "city_count": len(LOCATION_DB),
        "rayon_count": len(RAYON_DB)
    }

@app.get("/signals/{signal_id}/media")
def get_signal_media(signal_id: str):
    """Get list of media files for a signal"""
    signal_dir = UPLOADS_DIR / signal_id
    if not signal_dir.exists():
        return {"error": "Signal not found", "files": []}
    
    files = list(signal_dir.iterdir())
    return {
        "signal_id": signal_id,
        "files": [{"name": f.name, "size": f.stat().st_size, "path": str(f.absolute())} for f in files]
    }

@app.get("/signals")
def list_signals():
    """List all signals with media"""
    signals = []
    for signal_dir in UPLOADS_DIR.iterdir():
        if signal_dir.is_dir():
            files = list(signal_dir.iterdir())
            signals.append({
                "signal_id": signal_dir.name,
                "file_count": len(files),
                "files": [f.name for f in files]
            })
    return {"signals": signals, "count": len(signals)}

if __name__ == "__main__":
    import uvicorn
    print(f"✓ Base system prompt length: {len(BASE_SYSTEM_PROMPT)} characters")
    print(f"✓ Starting server with {len(ORGANIZATIONS)} organizations")
    print(f"✓ Supporting {len(LOCATION_DB)} cities and {len(RAYON_DB)} rayons")
    print(f"✓ Media uploads will be saved to: {UPLOADS_DIR.absolute()}")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
