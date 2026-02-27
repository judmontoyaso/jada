"""
MÃ³dulo de modelo de datos para CronJobs en Jada
DiseÃ±ado por: MiniMax-M2.1 (Agente Principal)
Asistencia: Qwen3-VL-30B
Fecha: 2026-02-26
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

class CronjobStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    RUNNING = "running"
    FAILED = "failed"

class Cronjob:
    """Modelo de datos para un CronJob"""
    
    def __init__(
        self,
        id: str,
        name: str,
        expression: str,  # ExpresiÃ³n cron: "0 6 * * *"
        command: str,      # Comando a ejecutar: "python main.py --task X"
        description: str = "",
        enabled: bool = True,
        last_run: Optional[datetime] = None,
        next_run: Optional[datetime] = None,
        status: CronjobStatus = CronjobStatus.ACTIVE,
        output: str = "",
        error: str = "",
        created_at: datetime = datetime.now(),
        updated_at: datetime = datetime.now()
    ):
        self.id = id
        self.name = name
        self.expression = expression
        self.command = command
        self.description = description
        self.enabled = enabled
        self.last_run = last_run
        self.next_run = next_run
        self.status = status
        self.output = output
        self.error = error
        self.created_at = created_at
        self.updated_at = updated_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertir a diccionario para JSON"""
        return {
            "id": self.id,
            "name": self.name,
            "expression": self.expression,
            "command": self.command,
            "description": self.description,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Cronjob':
        """Crear desde diccionario"""
        return cls(
            id=data["id"],
            name=data["name"],
            expression=data["expression"],
            command=data["command"],
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            status=CronjobStatus(data.get("status", "active")),
            output=data.get("output", ""),
            error=data.get("error", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
        )
    
    def to_json(self) -> str:
        """Convertir a JSON"""
        return json.dumps(self.to_dict(), indent=2)


class CronjobManager:
    """Gestor de CronJobs con persistencia"""
    
    def __init__(self, storage_file: str = "cronjobs.json"):
        self.storage_file = storage_file
        self.cronjobs: Dict[str, Cronjob] = {}
        self.load()
    
    def add(self, cronjob: Cronjob) -> bool:
        """Agregar un cronjob"""
        if cronjob.id in self.cronjobs:
            return False
        self.cronjobs[cronjob.id] = cronjob
        self.save()
        return True
    
    def get(self, id: str) -> Optional[Cronjob]:
        """Obtener un cronjob por ID"""
        return self.cronjobs.get(id)
    
    def update(self, id: str, **kwargs) -> bool:
        """Actualizar un cronjob"""
        if id not in self.cronjobs:
            return False
        
        cronjob = self.cronjobs[id]
        for key, value in kwargs.items():
            if hasattr(cronjob, key):
                setattr(cronjob, key, value)
        cronjob.updated_at = datetime.now()
        self.save()
        return True
    
    def delete(self, id: str) -> bool:
        """Eliminar un cronjob"""
        if id not in self.cronjobs:
            return False
        del self.cronjobs[id]
        self.save()
        return True
    
    def list_all(self) -> List[Cronjob]:
        """Listar todos los cronjobs"""
        return list(self.cronjobs.values())
    
    def list_enabled(self) -> List[Cronjob]:
        """Listar solo los cronjobs activos"""
        return [cj for cj in self.cronjobs.values() if cj.enabled]
    
    def save(self) -> None:
        """Guardar a archivo JSON"""
        data = {
            "version": "1.0",
            "last_update": datetime.now().isoformat(),
            "cronjobs": {id: cj.to_dict() for id, cj in self.cronjobs.items()}
        }
        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load(self) -> None:
        """Cargar desde archivo JSON"""
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
            for id, cj_data in data.get("cronjobs", {}).items():
                self.cronjobs[id] = Cronjob.from_dict(cj_data)
        except FileNotFoundError:
            self.cronjobs = {}
        except json.JSONDecodeError:
            self.cronjobs = {}


# Parser de expresiones cron (bÃ¡sico)
class CronParser:
    """Parser bÃ¡sico de expresiones cron"""
    
    @staticmethod
    def parse(expression: str) -> Dict[str, List[int]]:
        """
        Parsear expresiÃ³n cron "minuto hora dÃ­a mes dÃ­a_semana"
        Retorna diccionario con campos separados
        """
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError("ExpresiÃ³n cron debe tener 5 campos")
        
        return {
            "minute": CronParser._parse_field(parts[0], 0, 59),
            "hour": CronParser._parse_field(parts[1], 0, 23),
            "day": CronParser._parse_field(parts[2], 1, 31),
            "month": CronParser._parse_field(parts[3], 1, 12),
            "weekday": CronParser._parse_field(parts[4], 0, 6)
        }
    
    @staticmethod
    def _parse_field(value: str, min_val: int, max_val: int) -> List[int]:
        """Parsear un campo individual"""
        result = []
        for part in value.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                result.extend(range(start, end + 1))
            elif part == '*':
                result.extend(range(min_val, max_val + 1))
            else:
                val = int(part)
                if min_val <= val <= max_val:
                    result.append(val)
        return sorted(list(set(result)))
    
    @staticmethod
    def to_human_readable(expression: str) -> str:
        """Convertir expresiÃ³n cron a texto legible"""
        parsed = CronParser.parse(expression)
        
        parts = []
        
        # Minuto
        if parsed["minute"] == list(range(60)):
            minute_str = "cada minuto"
        elif parsed["minute"] == [0]:
            minute_str = "en punto"
        else:
            minute_str = f"minutos {parsed['minute']}"
        
        # Hora
        if parsed["hour"] == list(range(24)):
            hour_str = "cada hora"
        elif len(parsed["hour"]) == 1:
            hour_str = f"a las {parsed['hour'][0]}:00"
        else:
            hour_str = f"a las {parsed['hour']}"
        
        return f"{minute_str} {hour_str}"


if __name__ == "__main__":
    # Demo del modelo
    print("=== Demo Cronjob Model ===")
    
    # Crear un cronjob de ejemplo
    job = Cronjob(
        id="cron-001",
        name="Noticias Diarias",
        expression="0 6 * * *",
        command="python main.py --task noticias",
        description="Busca noticias cada maÃ±ana a las 6 AM"
    )
    
    print(f"Cronjob creado: {job.name}")
    print(f"ExpresiÃ³n: {job.expression}")
    print(f"Lectura humana: {CronParser.to_human_readable(job.expression)}")
    print("\nJSON:")
    print(job.to_json())
    
    # Probar el manager
    manager = CronjobManager("demo_cronjobs.json")
    manager.add(job)
    print(f"\nâœ… Guardado en {manager.storage_file}")
    print(f"Total cronjobs: {len(manager.list_all())}")
