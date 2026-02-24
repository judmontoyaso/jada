"""
tools/gym_parser.py — Parser determinístico de notación de gym
Convierte las notas del usuario directamente a JSON estructurado
sin depender del LLM para interpretar los datos.

Notación soportada:
- 12x20        → 1 serie: 12 reps @ 20kg
- 10x30x3      → 3 series: 10 reps @ 30kg cada una
- 12x2 con barra → 2 series: 12 reps @ 20kg (barra)
- 8x7.5kgx3    → 3 series: 8 reps @ 7.5kg cada una
- 10. 9. 8. 7. → 4 series de peso corporal
"""
import re
from datetime import date, timedelta


def parse_workout_text(text: str) -> list:
    """
    Parsea texto completo de entrenamiento a estructura JSON.
    Detecta ejercicios por nombre (palabras con mayúscula seguidas de datos numéricos),
    incluso si todo viene en una sola línea sin saltos de línea.
    """
    # Paso 1: Normalizar — reemplazar saltos de línea con un separador especial
    text = text.replace("\n", " ¶ ")
    
    # Paso 2: Detectar donde empieza cada ejercicio por su nombre
    # Un ejercicio empieza con 2+ letras (puede incluir tildes) seguidas de datos numéricos
    # Ejemplos: "Press plano 12x20", "Fondos paralelas 10.", "Read deltoid 12x10"
    exercise_pattern = re.compile(
        r'(?:^|(?<=\s¶\s)|(?<=\.\s)|(?<=\s))'  # antes del nombre
        r'([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:\s+(?:de\s+)?[a-záéíóúñüA-ZÁÉÍÓÚÑ]+)*)'  # nombre
        r'[\.\s]+'  # separador
        r'(?=\d)',  # seguido de número
    )
    
    # Encontrar todas las posiciones de inicio de ejercicios
    matches = list(exercise_pattern.finditer(text))
    
    if not matches:
        return []
    
    # Paso 3: Extraer cada ejercicio con nombre + datos
    ejercicios = []
    for i, m in enumerate(matches):
        nombre = m.group(1).strip()
        
        # Los datos van desde el fin del nombre hasta el inicio del siguiente ejercicio
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        datos = text[start:end].strip().rstrip("¶ ").strip()
        
        if not datos:
            continue
        
        sets = _parse_sets(datos)
        if not sets:
            continue
        
        notas = _extract_notes(datos)
        
        ejercicios.append({
            "nombre": nombre,
            "series": len(sets),
            "repeticiones": [s["reps"] for s in sets],
            "peso_kg": [s["peso"] for s in sets],
            "notas": notas,
        })
    
    return ejercicios


def _parse_exercise_line(line: str) -> dict | None:
    """Parsea una línea de ejercicio."""
    # Extraer nombre del ejercicio (texto antes de los números)
    # Buscar donde empiezan los datos numéricos
    name_match = re.match(r'^([A-Za-záéíóúñÁÉÍÓÚÑü\s]+?)[\.\s]+(?=\d)', line)
    
    if not name_match:
        # Podría ser "Fondos paralelas 10. 9. 8." (nombre pegado al número)
        name_match = re.match(r'^([A-Za-záéíóúñÁÉÍÓÚÑü\s]+?)\s+(?=\d+[\.\s])', line)
    
    if not name_match:
        return None

    nombre = name_match.group(1).strip()
    datos = line[name_match.end():].strip()

    # Parsear sets de la parte de datos
    sets = _parse_sets(datos)
    
    if not sets:
        return None

    # Extraer notas (dropsets, etc.)
    notas = _extract_notes(datos)

    return {
        "nombre": nombre,
        "series": len(sets),
        "repeticiones": [s["reps"] for s in sets],
        "peso_kg": [s["peso"] for s in sets],
        "notas": notas,
    }


def _parse_sets(datos: str) -> list[dict]:
    """
    Parsea la parte de datos de un ejercicio.
    Retorna lista de {"reps": int, "peso": float}
    """
    sets = []
    
    # Determinar si hay "con barra" global
    con_barra = "con barra" in datos.lower()
    
    # Separar por puntos y espacios, limpiando
    # Primero quitar notas como "con dropset de ..." y "cada mano/lado"
    clean = re.sub(r'\s*(con\s+dropset\s+de\s+[\dx.]+)', '', datos, flags=re.IGNORECASE)
    clean = re.sub(r'\s*y\s+(?=\d+x)', ' ', clean)  # "y 7x50" → " 7x50"
    
    # Encontrar todos los tokens de sets
    # Patrones posibles:
    # 12x20          → 12 reps @ 20kg
    # 10x30x3        → 3 × (10 reps @ 30kg)
    # 8x7.5kgx3      → 3 × (8 reps @ 7.5kg)
    # 12x5kg         → 12 reps @ 5kg
    # 12x2 con barra → 2 × (12 reps @ 20kg)
    # 10              → 10 reps @ 0kg (peso corporal)
    
    # Pattern con "con barra" al final: NxM con barra = M series de N reps @ 20kg
    barra_match = re.search(r'(\d+)x(\d+)\s+con\s+barra', clean, re.IGNORECASE)
    if barra_match:
        reps = int(barra_match.group(1))
        num_sets = int(barra_match.group(2))
        for _ in range(num_sets):
            sets.append({"reps": reps, "peso": 0})
        # Quitar este token del string para no procesarlo de nuevo
        clean = clean[:barra_match.start()] + clean[barra_match.end():]
    
    # Pattern principal: REPSxPESO(kg)?xMULTIPLIER o REPSxPESO(kg)?
    for m in re.finditer(r'(\d+)x([\d.]+)(?:kg)?(?:x(\d+))?', clean):
        reps = int(m.group(1))
        peso = float(m.group(2))
        multiplier = int(m.group(3)) if m.group(3) else 1
        
        for _ in range(multiplier):
            sets.append({"reps": reps, "peso": peso})
    
    # Si no encontró patrones NxP, buscar solo números (peso corporal)
    # Ej: "10. 9. 9. 8. 7." para fondos
    if not sets:
        for m in re.finditer(r'(?<!\d)(\d+)(?!\d*x)(?:\.|$|\s)', datos):
            reps = int(m.group(1))
            if 1 <= reps <= 50:  # filtro razonable para reps
                sets.append({"reps": reps, "peso": 0})

    return sets


def _extract_notes(datos: str) -> str:
    """Extrae notas como dropsets, cada mano, etc."""
    notes_parts = []
    
    dropset = re.search(r'(?:con\s+)?dropset\s+de\s+([\dx.]+)', datos, re.IGNORECASE)
    if dropset:
        notes_parts.append(f"Dropset de {dropset.group(1)}")
    
    if "cada mano" in datos.lower():
        notes_parts.append("Cada mano")
    elif "cada lado" in datos.lower():
        notes_parts.append("Cada lado")
    
    return ". ".join(notes_parts)


def expand_gym_notation(text: str) -> str:
    """
    Versión simple: solo expande notaciones abreviadas.
    Usada cuando no queremos parseo completo.
    """
    lines = text.split("\n")
    expanded = []
    for line in lines:
        if not re.search(r'\d+x\d', line):
            expanded.append(line)
            continue

        # NxPxM → expandir
        def expand_mult(m):
            reps, weight, mult = m.group(1), m.group(2), int(m.group(3))
            unit = m.group(4) or ""
            return ", ".join([f"{reps}x{weight}"] * mult) + unit

        line = re.sub(r'(\d+)x([\d.]+kg?)x(\d+)((?:\s+cada\s+(?:mano|lado))?)', expand_mult, line)
        line = re.sub(r'(\d+)x([\d.]+)x(\d+)((?:\s+cada\s+(?:mano|lado))?)', expand_mult, line)
        line = re.sub(
            r'(\d+)x(\d+)\s+con\s+barra',
            lambda m: ", ".join([f"{m.group(1)}x0"] * int(m.group(2))) + " (barra)",
            line
        )
        expanded.append(line)

    return "\n".join(expanded)


# ─── Tests ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_input = """Press plano 12x2 con barra. 12x20. 10x30. 5x40. 7x40 6x40x2
Press inclinado 10x20. 6x30 5x30x2. 7x20x2
Apertura de pecho. 12x30kg. 10x50. 7x50x2 y 7x50 con dropset de 9x35
Press shoulder. 12x20kg. 10x25kg. 8x30kg. 6x35kgx2
Vuelos laterales con mancuernas. 12x5kg cada mano. 8x7.5kgx3 cada lado
Read deltoid 12x10kg. 12x20kg. 7x25kg. 10x20
Fondos paralelas 10. 9. 9. 8. 7.
Fondos máquina. 12x25kg. 10x30x3
Extensiones de tríceps. 12x15kg. 12x20kg 9x22.5 y 9x22.5 con dropset de 10x15"""

    print("=== PARSEO DETERMINÍSTICO ===\n")
    ejercicios = parse_workout_text(test_input)
    
    for i, ej in enumerate(ejercicios, 1):
        print(f"{i}. {ej['nombre']}")
        print(f"   Series: {ej['series']}")
        print(f"   Reps:   {ej['repeticiones']}")
        print(f"   Peso:   {ej['peso_kg']}")
        if ej['notas']:
            print(f"   Notas:  {ej['notas']}")
        print()
