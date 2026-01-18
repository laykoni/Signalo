"""
Interactive Organization Filter Tester
Type in any location and see what organizations would be returned
"""

import csv
from typing import List, Dict, Optional

def load_orgs():
    orgs = []
    with open('organizations.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row['0'] or not row['0'].strip():
                continue
            orgs.append({
                'id': int(row['0']),
                'name': row['org_name'].strip(),
                'oblast': row.get('Област', '').strip() or None,
                'obshtina': row.get('Община', '').strip() or None,
                'grad': row.get('Град/село', '').strip() or None,
                'rayon': row.get('Район', '').strip() or None,
            })
    return orgs

def normalize(s):
    return s.strip().lower() if s else ""

def location_matches(user_loc, org_loc):
    if org_loc is None:
        return True
    if ';' in org_loc or ',' in org_loc:
        for sep in [';', ',']:
            if sep in org_loc:
                return normalize(user_loc) in [normalize(x) for x in org_loc.split(sep)]
    return normalize(user_loc) == normalize(org_loc)

def filter_orgs(orgs, oblast=None, obshtina=None, grad=None, rayon=None):
    """FIXED filtering logic - excludes orgs that are too specific"""
    filtered = []
    for org in orgs:
        # Check oblast
        if org['oblast'] is not None and oblast is not None:
            if not location_matches(oblast, org['oblast']):
                continue
        
        # Exclude if too specific: user didn't specify obshtina
        if obshtina is None:
            if org['obshtina'] is not None:
                continue
        else:
            if org['obshtina'] is not None:
                if not location_matches(obshtina, org['obshtina']):
                    continue
        
        # Exclude if too specific: user didn't specify grad
        if grad is None:
            if org['grad'] is not None:
                continue
        else:
            if org['grad'] is not None:
                if not location_matches(grad, org['grad']):
                    continue
        
        # Exclude if too specific: user didn't specify rayon
        if rayon is None:
            if org['rayon'] is not None:
                continue
        else:
            if org['rayon'] is not None:
                if not location_matches(rayon, org['rayon']):
                    continue
        
        filtered.append(org)
    return filtered

def print_results(filtered, search_term=""):
    """Print filtered results in a nice table format"""
    
    # Categorize
    national = [o for o in filtered if not any([o['oblast'], o['obshtina'], o['grad'], o['rayon']])]
    oblast_only = [o for o in filtered if o['oblast'] and not o['obshtina']]
    obshtina_only = [o for o in filtered if o['obshtina'] and not o['grad']]
    grad_only = [o for o in filtered if o['grad'] and not o['rayon']]
    rayon_only = [o for o in filtered if o['rayon']]
    
    print(f"\n{'='*120}")
    print(f"RESULTS: {len(filtered)} organizations total")
    print(f"{'='*120}")
    
    print(f"\n📊 BREAKDOWN:")
    print(f"  • National: {len(national)}")
    print(f"  • Oblast-level: {len(oblast_only)}")
    print(f"  • Obshtina-level: {len(obshtina_only)}")
    print(f"  • Grad-level: {len(grad_only)}")
    print(f"  • Rayon-level: {len(rayon_only)}")
    
    # Print table header
    print(f"\n{'='*120}")
    print(f"{'ID':<6} {'Level':<8} {'Organization Name':<50} {'Coverage':<50}")
    print(f"{'='*120}")
    
    # Helper to get level name
    def get_level(org):
        if org['rayon']:
            return "Rayon"
        elif org['grad']:
            return "Grad"
        elif org['obshtina']:
            return "Obshtina"
        elif org['oblast']:
            return "Oblast"
        else:
            return "National"
    
    # Helper to format coverage
    def get_coverage(org):
        parts = []
        if org['oblast']:
            parts.append(f"O:{org['oblast'][:12]}")
        if org['obshtina']:
            parts.append(f"Ob:{org['obshtina'][:12]}")
        if org['grad']:
            parts.append(f"G:{org['grad'][:12]}")
        if org['rayon']:
            parts.append(f"R:{org['rayon'][:12]}")
        return " | ".join(parts) if parts else "-"
    
    # Sort organizations: rayon > grad > obshtina > oblast > national
    # Then by name within each level
    def sort_key(org):
        level_priority = {
            'Rayon': 0,
            'Grad': 1,
            'Obshtina': 2,
            'Oblast': 3,
            'National': 4
        }
        return (level_priority[get_level(org)], org['name'].lower())
    
    sorted_orgs = sorted(filtered, key=sort_key)
    
    # Print all organizations
    current_level = None
    for org in sorted_orgs:
        level = get_level(org)
        
        # Print section header when level changes
        if level != current_level:
            print(f"\n{'─'*120}")
            print(f"{level.upper()} ORGANIZATIONS:")
            print(f"{'─'*120}")
            current_level = level
        
        name = org['name'][:48] + '..' if len(org['name']) > 50 else org['name']
        coverage = get_coverage(org)[:48] + '..' if len(get_coverage(org)) > 50 else get_coverage(org)
        
        print(f"{org['id']:<6} {level:<8} {name:<50} {coverage:<50}")
    
    print(f"{'='*120}")

def main():
    print("="*80)
    print("INTERACTIVE ORGANIZATION FILTER TESTER")
    print("="*80)
    print("Type location details to see which organizations would be returned")
    print("Leave fields blank to skip them (press Enter)")
    print("Type 'quit' to exit\n")
    
    orgs = load_orgs()
    print(f"✓ Loaded {len(orgs)} organizations\n")
    
    while True:
        print("-"*80)
        print("\nEnter location details:")
        
        # Get oblast
        oblast = input("  Oblast (e.g. Пловдив, София-столица): ").strip()
        if oblast.lower() == 'quit':
            break
        oblast = oblast if oblast else None
        
        # Get obshtina
        obshtina = input("  Obshtina (e.g. Пловдив, София): ").strip()
        if obshtina.lower() == 'quit':
            break
        obshtina = obshtina if obshtina else None
        
        # Get grad
        grad = input("  Grad (e.g. Пловдив, София): ").strip()
        if grad.lower() == 'quit':
            break
        grad = grad if grad else None
        
        # Get rayon
        rayon = input("  Rayon (e.g. Район Западен, Лозенец): ").strip()
        if rayon.lower() == 'quit':
            break
        rayon = rayon if rayon else None
        
        # Show what we're searching for
        print(f"\n🔍 FILTERING FOR:")
        search_parts = []
        if oblast: search_parts.append(f"Oblast: {oblast}")
        if obshtina: search_parts.append(f"Obshtina: {obshtina}")
        if grad: search_parts.append(f"Grad: {grad}")
        if rayon: search_parts.append(f"Rayon: {rayon}")
        
        if not search_parts:
            print("  (No location specified - will return ALL organizations)")
        else:
            for part in search_parts:
                print(f"  • {part}")
        
        # Filter
        filtered = filter_orgs(orgs, oblast=oblast, obshtina=obshtina, grad=grad, rayon=rayon)
        
        # Determine search term for location-specific orgs
        search_term = grad or obshtina or oblast or ""
        
        # Print results
        print_results(filtered, search_term)
        
        # Ask if they want to continue
        print(f"\n{'='*80}")
        continue_choice = input("\nTest another location? (y/n): ").strip().lower()
        if continue_choice != 'y':
            break
    
    print("\n✓ Done!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✓ Interrupted. Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()