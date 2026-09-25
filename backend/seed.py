"""
Seed the database with a realistic demo scenario: a cluster of flood
requests around Aluva/Kochi so the dashboard map, hotspot detection, and
priority queue all have something meaningful to show on first run.

Run with:  python seed.py
"""
import requests

API = "http://localhost:8000/api/requests"

DEMO_REQUESTS = [
    dict(name="Radhamani K.", phone="9847XXXXX1", channel="ivr", language="ml",
         description="water entering house fast, elderly mother trapped on roof, cannot swim",
         category="rescue", has_elderly=True, lat=10.1075, lng=76.3516, location_text="Aluva, near market"),
    dict(name="Suresh Nair", phone="9847XXXXX2", channel="whatsapp", language="ml",
         description="two children stuck on first floor, water still rising rapidly",
         category="rescue", has_children=True, lat=10.1081, lng=76.3529, location_text="Aluva, Desom road"),
    dict(name="Beena Thomas", phone="9847XXXXX3", channel="app", language="en",
         description="diabetic patient out of insulin, area cut off by floodwater",
         category="medical", has_medical_need=True, lat=10.1069, lng=76.3502, location_text="Aluva, Church road"),
    dict(name="Unknown caller", phone="9847XXXXX4", channel="sms", language="ml",
         description="need dry food and clean water for family of four",
         category="food", lat=10.1090, lng=76.3540, location_text="Aluva East"),
    dict(name="Anitha Raj", phone="9847XXXXX5", channel="app", language="en",
         description="house compound flooded, main house still dry for now",
         category="general", lat=10.0523, lng=76.3211, location_text="Kalamassery"),
    dict(name="Joseph Mathew", phone="9847XXXXX6", channel="whatsapp", language="ml",
         description="wheelchair user cannot evacuate alone, water rising slowly",
         category="rescue", has_elderly=True, lat=10.1078, lng=76.3521, location_text="Aluva, near market"),
    dict(name="Fathima Beevi", phone="9847XXXXX7", channel="ivr", language="ml",
         description="pregnant woman in labour, roads flooded, cannot reach hospital",
         category="medical", has_medical_need=True, lat=10.1088, lng=76.3508, location_text="Aluva, market road"),
    dict(name="Volunteer Ravi", phone="9847XXXXX8", channel="app", language="en",
         description="want to volunteer for relief work this weekend",
         category="general", lat=9.9816, lng=76.2999, location_text="Kochi city"),
]

if __name__ == "__main__":
    for payload in DEMO_REQUESTS:
        resp = requests.post(API, json=payload, timeout=10)
        resp.raise_for_status()
        r = resp.json()
        print(f"[{r['urgency_label']:>8}] score={r['urgency_score']:>5} -> {r['description'][:60]}")
    print(f"\nSeeded {len(DEMO_REQUESTS)} demo requests.")
