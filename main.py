"""
FIXED: Proper hierarchical filtering - excludes organizations that are too specific
Key principle: If user doesn't specify a level, EXCLUDE organizations at that level and below
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
import os
import json
import csv
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
    """
    Filter organizations based on hierarchical location logic
    
    KEY PRINCIPLE: If user doesn't specify a level, EXCLUDE organizations at that level
    
    Examples:
    - User says "Oblast Plovdiv" → Include National + Oblast-level, EXCLUDE Obshtina/Grad/Rayon
    - User says "Plovdiv city" → Include National + Oblast + Obshtina + Grad, EXCLUDE Rayon
    - User says "Plovdiv, Rayon Zapaden" → Include all levels including matching Rayon
    """
    filtered = []
    
    for org in ORGANIZATIONS:
        # Rule 1: If org has oblast, it must match (if user specified oblast)
        if org['oblast'] is not None and oblast is not None:
            if not location_matches(oblast, org['oblast']):
                continue  # Oblast doesn't match, skip
        
        # Rule 2: If user didn't specify obshtina, EXCLUDE orgs that have obshtina
        # (they're too specific - they cover only part of the oblast)
        if obshtina is None:
            if org['obshtina'] is not None:
                continue  # Too specific, skip
        else:
            # User specified obshtina, so check if it matches
            if org['obshtina'] is not None:
                if not location_matches(obshtina, org['obshtina']):
                    continue  # Obshtina doesn't match, skip
        
        # Rule 3: If user didn't specify grad, EXCLUDE orgs that have grad
        if grad is None:
            if org['grad'] is not None:
                continue  # Too specific, skip
        else:
            # User specified grad, so check if it matches
            if org['grad'] is not None:
                if not location_matches(grad, org['grad']):
                    continue  # Grad doesn't match, skip
        
        # Rule 4: If user didn't specify rayon, EXCLUDE orgs that have rayon
        if rayon is None:
            if org['rayon'] is not None:
                continue  # Too specific, skip
        else:
            # User specified rayon, so check if it matches
            if org['rayon'] is not None:
                if not location_matches(rayon, org['rayon']):
                    continue  # Rayon doesn't match, skip
        
        # If we got here, org is valid for this location
        filtered.append(org)
    
    print(f"✓ Filtered to {len(filtered)} organizations for: {oblast}/{obshtina}/{grad}/{rayon}")
    return filtered

def extract_location_from_messages(messages: List[Dict]) -> Optional[Dict[str, str]]:
    """Extract location from conversation using pattern matching"""
    
    location_db = {
        'пловдив': {'oblast': 'Пловдив', 'obshtina': 'Пловдив', 'grad': 'Пловдив'},
        'софия': {'oblast': 'София-столица', 'obshtina': 'София', 'grad': 'София'},
        'варна': {'oblast': 'Варна', 'obshtina': 'Варна', 'grad': 'Варна'},
        'бургас': {'oblast': 'Бургас', 'obshtina': 'Бургас', 'grad': 'Бургас'},
        'русе': {'oblast': 'Русе', 'obshtina': 'Русе', 'grad': 'Русе'},
        'стара загора': {'oblast': 'Стара Загора', 'obshtina': 'Стара Загора', 'grad': 'Стара Загора'},
        'плевен': {'oblast': 'Плевен', 'obshtina': 'Плевен', 'grad': 'Плевен'},
        'сливен': {'oblast': 'Сливен', 'obshtina': 'Сливен', 'grad': 'Сливен'},
        'добрич': {'oblast': 'Добрич', 'obshtina': 'Добрич', 'grad': 'Добрич'},
    }
    
    rayon_patterns = {
        'западен': 'Район Западен',
        'източен': 'Район Източен', 
        'северен': 'Район Северен',
        'централен': 'Район Централен',
        'тракия': 'Район Тракия',
        'южен': 'Район Южен',
        'лозенец': 'Лозенец',
        'витоша': 'Витоша',
        'младост': 'Младост',
        'аспарухово': 'Район Аспарухово',
        'одесос': 'Район Одесос',
    }
    
    # Check last few messages
    for msg in reversed(messages[-6:]):
        content = msg['content'].lower()
        
        # Try to find city
        for city_key, loc_data in location_db.items():
            if city_key in content:
                result = loc_data.copy()
                
                # Try to find rayon
                for rayon_key, rayon_value in rayon_patterns.items():
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

BASE_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT = """Ти си асистент за подаване на граждански сигнали към българските държавни институции.

ТВОЯТА ЦЕЛ: Да събереш ДОСТАТЪЧНО информация, за да може институцията РЕАЛНО да реагира на сигнала.

ПРОЦЕС:
1. КЪДЕ - Първо установи точното местоположение (град, район, адрес)
2. КАКВО - Разбери какъв е проблемът в детайли
3. КОГА - Кога се е случило (дата, час ако е важно)
4. ДЕТАЙЛИ ПО ТИП СИГНАЛ - Задай специфични въпроси според вида проблем (виж примерите долу)
5. КОНТАКТ - Само ако е нужно за реакция на сигнала
6. ПОТВЪРЖДЕНИЕ - Обобщи и питай "Да изпратя ли сигнала?"

⚠️ КРИТИЧНО ВАЖНО:
- НЕ бързай да генерираш сигнал! По-добре е да зададеш 1-2 въпроса повече, отколкото да изпратиш непълен сигнал.
- Преди да предложиш изпращане, ПРОВЕРИ дали имаш достатъчно информация институцията да действа.
- Ако информацията е недостатъчна, кажи на потребителя какво липсва и защо е важно.
- Ако потребителят спомене, че вече е изпращан сигнал до институции, но няма реакция, избери по визша организация, за да ескалираме сигнлата (НО само ако сигналът е сериозен, за дребни проблеми не ескалирай)

ПРИМЕРИ ЗА НУЖНА ИНФОРМАЦИЯ ПО ТИП СИГНАЛ:

📋 ФИСКАЛНИ НАРУШЕНИЯ (липса на касова бележка, неиздаден фискален бон):
- Име на търговския обект (ЗАДЪЛЖИТЕЛНО - без него НАП не може да провери!)
- Точен адрес
- Дата и приблизителен час
- Какво е закупено и на каква стойност (поне приблизително)
- Поискахте ли касова бележка и какво ви отговориха?

🚧 ИНФРАСТРУКТУРНИ ПРОБЛЕМИ (дупки, улично осветление, тротоари):
- Точен адрес или ориентир (между кои улици, до кой номер)
- Описание на проблема (размер на дупката, колко лампи не светят)
- От колко време съществува проблемът?
- Има ли опасност за хора/коли?

🗑️ ЧИСТОТА И ОТПАДЪЦИ (боклуци, нерегламентирани сметища):
- Точна локация
- Какъв вид отпадъци (битови, строителни, опасни)
- Приблизително количество
- От колко време е там?

🌳 ЕКОЛОГИЧНИ ПРОБЛЕМИ (замърсяване, незаконна сеч):
- Точна локация (GPS координати ако има)
- Вид замърсяване/нарушение
- Мащаб на проблема
- Има ли извършител (фирма, лице)?

🏗️ НЕЗАКОННО СТРОИТЕЛСТВО:
- Точен адрес
- Какво се строи
- От кога продължава
- Има ли видими разрешителни/табели?

🐕 БЕЗСТОПАНСТВЕНИ ЖИВОТНИ:
- Локация където се намират
- Брой животни
- Агресивни ли са?
- Има ли наранени животни?

🔊 ШУМ И НАРУШЕНИЯ НА ОБЩЕСТВЕНИЯ РЕД:
- Точен адрес на източника
- Вид шум (музика, строителство, производство)
- В какви часове се случва
- Колко често (еднократно, всяка вечер)?

ВАЖНО ЗА МЕСТОПОЛОЖЕНИЕТО:
- За големи градове (София, Пловдив, Варна) - ВИНАГИ питай за район
- Извлечи: област, община, град/село, район (ако е приложимо), улица/адрес

КОНТАКТНА ИНФОРМАЦИЯ:
- Питай за име само ако потребителят иска да бъде включено
- Питай за телефон/имейл САМО ако институцията ще има нужда да се свърже (напр. за оглед, за допълнителни въпроси)
- За анонимни сигнали - не настоявай за контакт

JSON ФОРМАТ (връщай САМО когато имаш ДОСТАТЪЧНО информация И потребителят потвърди):
```json
{
  "title": "Кратко заглавие на сигнала",
  "description": "ПОДРОБНО описание с ВСИЧКИ събрани детайли - това е най-важното поле!",
  "agency_id": 123,
  "agency": "Име на институцията",
  "location": {
    "oblast": "Област",
    "obshtina": "Община", 
    "grad": "Град/село",
    "rayon": "Район (ако е приложимо)",
    "street": "Улица/адрес"
  },
  "category": "",
  "urgency": "спешно/нормално/неспешно"
}
```

ПРАВИЛА:
- Задавай по 1-2 въпроса наведнъж, не претоварвай потребителя
- Ако потребителят не знае нещо, продължи напред
- Описанието в JSON трябва да е ПЪЛНО изречение с всички детайли, не телеграфен стил"""


def build_system_prompt_with_orgs(organizations: List[Dict]) -> str:
    """Build complete system prompt with filtered organization list"""
    org_list = create_org_list_text(organizations)
    
    return f"""{BASE_SYSTEM_PROMPT}

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

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    location_context: Optional[Dict[str, str]] = None

@app.post("/chat")
async def chat(request: ChatRequest):
    """Handle chat conversation with location-based organization filtering"""
    
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    

    # Check if signal was already sent - look for completed signal JSON in assistant messages
    for msg in messages:
        if msg['role'] == 'assistant':
            content = msg['content']
            # Check if this message contains a completed signal JSON
            if all(marker in content for marker in ['"agency_id"', '"title"', '"description"', '"agency"']):
                print("⚠ Signal already sent in this conversation - blocking duplicate")
                return {
                    "signal_ready": False,
                    "signal_sent": True,
                    "message": "Сигналът вече беше изпратен. Ако искате да подадете нов сигнал, моля започнете нов разговор.",
                    "conversation_ended": True
                }
    
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
        system_prompt = build_system_prompt_with_orgs(filtered_orgs)
        print(f"✓ Using filtered list with {len(filtered_orgs)} organizations")
    else:
        filtered_orgs = ORGANIZATIONS
        system_prompt = BASE_SYSTEM_PROMPT + "\n\n(Списъкът на институциите ще бъде предоставен след като разбера местоположението)"
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
        
        if signal_data and all(k in signal_data for k in ['title', 'description', 'agency']):
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
            
            return {
                "signal_ready": True,
                "signal_sent": True,
                "signal_data": signal_data,
                "message": "✅ Сигналът беше изпратен успешно! Благодарим ви. Ако искате да подадете нов сигнал, моля започнете нов разговор.",
                "filtered_org_count": len(filtered_orgs),
                "conversation_ended": True
            }
        else:
            return {
                "signal_ready": False,
                "signal_sent": False,
                "message": assistant_message,
                "filtered_org_count": len(filtered_orgs) if location_context else None,
                "location_context": location_context
            }
    
    except Exception as e:
        print(f"❌ Error: {e}")
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
        "message": "Citizen Signals Chat API with Proper Hierarchical Filtering", 
        "status": "running",
        "organizations_loaded": len(ORGANIZATIONS)
    }

@app.get("/organizations")
def get_organizations():
    """Get list of all organizations"""
    return {
        "organizations": ORGANIZATIONS,
        "count": len(ORGANIZATIONS)
    }

if __name__ == "__main__":
    import uvicorn
    print(f"✓ Base system prompt length: {len(BASE_SYSTEM_PROMPT)} characters")
    print(f"✓ Starting server with {len(ORGANIZATIONS)} organizations")
    
    # Quick test
    print("\n" + "="*80)
    print("TESTING FILTERING LOGIC:")
    print("="*80)
    
    test1 = filter_organizations_by_location(oblast="Пловдив")
    plovdiv1 = [o for o in test1 if 'пловдив' in o['name'].lower()]
    print(f"✓ Oblast only: {len(test1)} orgs (Plovdiv-specific: {len(plovdiv1)})")
    
    test2 = filter_organizations_by_location(oblast="Пловдив", obshtina="Пловдив", grad="Пловдив")
    plovdiv2 = [o for o in test2 if 'пловдив' in o['name'].lower()]
    print(f"✓ With grad: {len(test2)} orgs (Plovdiv-specific: {len(plovdiv2)})")
    
    test3 = filter_organizations_by_location(oblast="Пловдив", obshtina="Пловдив", grad="Пловдив", rayon="Район Западен")
    plovdiv3 = [o for o in test3 if 'пловдив' in o['name'].lower()]
    print(f"✓ With rayon: {len(test3)} orgs (Plovdiv-specific: {len(plovdiv3)})")
    print("="*80 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
