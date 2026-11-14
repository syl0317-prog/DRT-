from pathlib import Path

for name, spans in {
    "sewook31/app.py": [(0, 85)],
    "sewook31/modules/live_control.py": [(0, 50), (200, 430)],
    "sewook31/modules/vehicle_positions.py": [(10, 45), (125, 170), (265, 375), (375, 460)],
}.items():
    lines = Path(name).read_text(encoding="utf-8").splitlines()
    print(f"### {name}")
    for start, end in spans:
        for i in range(start, min(end, len(lines))):
            print(f"{i+1}: {lines[i]}")
