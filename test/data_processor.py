import json
from datetime import datetime

def process_user_data(raw_data: str) -> dict:
    """
    Parses raw JSON data, filters active users, and calculates age.
    """
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON", "count": 0, "users": []}

    processed_users = []
    current_year = datetime.now().year

    for user in data.get("users", []):
        # Filtering logic
        if not user.get("active", False):
            continue
            
        birth_year = user.get("birth_year", current_year)
        age = current_year - birth_year
        
        # Transformation logic
        processed_user = {
            "id": user.get("id"),
            "full_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            "age": age,
            "category": "senior" if age >= 65 else "adult" if age >= 18 else "minor"
        }
        processed_users.append(processed_user)

    return {
        "status": "success",
        "count": len(processed_users),
        "users": processed_users
    }
