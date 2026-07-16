import re, json

# Test the regex fix
text = '{"label": "D", "-than", "text": "Yes, it is behind the classroom"}'
print("Before:", repr(text))

result = re.sub(
    r'\{\s*"label"\s*:\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*"text"\s*:\s*',
    r'{"label": "\1", "text": ',
    text
)
print("After:", repr(result))

# Test full JSON with all questions
full_json = '''{
  "questions": [
    {
      "stem": "Where is the library?",
      "options": [
        {"label": "A", "text": "On the second floor"},
        {"label": "B", "text": "Next to the classroom"},
        {"label": "C", "text": "Behind the school"},
        {"label": "D", "-than", "text": "Yes, it is behind the classroom"}
      ],
      "answer": "A"
    }
  ]
}'''

print("\nFull JSON before:", repr(full_json[:200]))
fixed = re.sub(
    r'\{\s*"label"\s*:\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*"text"\s*:\s*',
    r'{"label": "\1", "text": ',
    full_json
)
print("Full JSON after:", repr(fixed[:200]))

# Try parsing
try:
    data = json.loads(fixed)
    print("Parse SUCCESS!")
    print("Questions:", len(data["questions"]))
    q2 = data["questions"][0]
    print("Options:", len(q2["options"]))
    for o in q2["options"]:
        print(" ", o)
except json.JSONDecodeError as e:
    print("Parse FAILED:", e)
