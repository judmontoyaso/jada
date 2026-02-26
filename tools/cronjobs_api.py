#!/usr/bin/env python3
"""
API REST para gestión de CronJobs en MiniClaw
Agente: MiniMax-M2.1 (Principal)
Asistente: Qwen3-VL-30B (UI Design)
Fecha: 2026-02-26
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qs, urlparse

# Importar modelo de datos
from tools.cronjobs_model import Cronjob, CronjobManager, CronParser

# Configuración
STORAGE_FILE = "cronjobs.json"
PORT = 8080
HOST = "0.0.0.0"

class CronjobAPI:
    """API REST para gestionar CronJobs"""
    
    def __init__(self):
        self.manager = CronjobManager(STORAGE_FILE)
        self.active_jobs: Dict[str, subprocess.Popen] = {}
        
    def create_cronjob(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Crear un nuevo cronjob"""
        # Validar expresión cron
        try:
            CronParser.parse(data.get("expression", "* * * * *"))
        except ValueError as e:
            return {"status": "error", "message": f"Expresión cron inválida: {e}"}
        
        # Generar ID único
        job_id = f"cron-{int(time.time())}"
        
        # Crear cronjob
        cronjob = Cronjob(
            id=job_id,
            name=data.get("name", "Sin nombre"),
            expression=data.get("expression", "* * * * *"),
            command=data.get("command", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True)
        )
        
        # Calcular próxima ejecución
        cronjob.next_run = self._calculate_next_run(cronjob.expression)
        
        # Guardar
        if self.manager.add(cronjob):
            # Si está habilitado, registrar en crontab del sistema
            if cronjob.enabled:
                self._register_system_cron(cronjob)
            
            return {
                "status": "success",
                "message": "Cronjob creado exitosamente",
                "data": cronjob.to_dict()
            }
        else:
            return {"status": "error", "message": "El cronjob ya existe"}
    
    def get_cronjob(self, job_id: str) -> Optional[Cronjob]:
        """Obtener un cronjob por ID"""
        return self.manager.get(job_id)
    
    def list_cronjobs(self) -> List[Dict[str, Any]]:
        """Listar todos los cronjobs"""
        return [cj.to_dict() for cj in self.manager.list_all()]
    
    def update_cronjob(self, job_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Actualizar un cronjob"""
        cronjob = self.manager.get(job_id)
        if not cronjob:
            return {"status": "error", "message": "Cronjob no encontrado"}
        
        # Actualizar campos permitidos
        allowed_fields = ['name', 'expression', 'command', 'description', 'enabled']
        for field in allowed_fields:
            if field in data:
                setattr(cronjob, field, data[field])
        
        # Si cambió la expresión, recalcular próxima ejecución
        if 'expression' in data:
            cronjob.next_run = self._calculate_next_run(data['expression'])
        
        cronjob.updated_at = datetime.now()
        
        # Si cambió el estado de enabled, actualizar crontab del sistema
        if 'enabled' in data:
            if data['enabled']:
                self._register_system_cron(cronjob)
            else:
                self._unregister_system_cron(job_id)
        
        self.manager.save()
        
        return {
            "status": "success",
            "message": "Cronjob actualizado",
            "data": cronjob.to_dict()
        }
    
    def delete_cronjob(self, job_id: str) -> Dict[str, Any]:
        """Eliminar un cronjob"""
        # Eliminar del sistema
        self._unregister_system_cron(job_id)
        
        # Eliminar del manager
        if self.manager.delete(job_id):
            return {"status": "success", "message": "Cronjob eliminado"}
        else:
            return {"status": "error", "message": "Cronjob no encontrado"}
    
    def run_now(self, job_id: str) -> Dict[str, Any]:
        """Ejecutar un cronjob inmediatamente"""
        cronjob = self.manager.get(job_id)
        if not cronjob:
            return {"status": "error", "message": "Cronjob no encontrado"}
        
        # Ejecutar en hilo separado
        def execute():
            try:
                cronjob.status = "running"
                cronjob.last_run = datetime.now()
                self.manager.save()
                
                # Ejecutar comando
                process = subprocess.Popen(
                    cronjob.command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                stdout, stderr = process.communicate()
                
                cronjob.output = stdout.decode('utf-8', errors='replace')
                cronjob.error = stderr.decode('utf-8', errors='replace')
                cronjob.status = "completed" if process.returncode == 0 else "failed"
                cronjob.last_run = datetime.now()
                
            except Exception as e:
                cronjob.error = str(e)
                cronjob.status = "failed"
            
            cronjob.updated_at = datetime.now()
            self.manager.save()
        
        thread = threading.Thread(target=execute)
        thread.start()
        
        return {
            "status": "success",
            "message": f"Cronjob '{cronjob.name}' ejecutándose",
            "execution_id": job_id
        }
    
    def get_logs(self, job_id: str) -> Dict[str, Any]:
        """Obtener logs de ejecución de un cronjob"""
        cronjob = self.manager.get(job_id)
        if not cronjob:
            return {"status": "error", "message": "Cronjob no encontrado"}
        
        return {
            "status": "success",
            "data": {
                "output": cronjob.output,
                "error": cronjob.error,
                "last_run": cronjob.last_run.isoformat() if cronjob.last_run else None,
                "status": cronjob.status
            }
        }
    
    def _calculate_next_run(self, expression: str) -> Optional[datetime]:
        """Calcular próxima ejecución basándose en expresión cron"""
        # Implementación básica - retorna None por ahora
        # Una implementación completa usaría una librería como python-crontab
        return None
    
    def _register_system_cron(self, cronjob: Cronjob):
        """Registrar cronjob en el sistema operativo"""
        # Crear entrada de crontab
        cron_entry = f"{cronjob.expression} cd {os.getcwd()} && {cronjob.command} >> logs/{cronjob.id}.log 2>&1"
        
        try:
            # Obtener crontab actual
            result = subprocess.run(
                ['crontab', '-l'],
                capture_output=True,
                text=True
            )
            
            current_crontab = result.stdout if result.returncode == 0 else ""
            
            # Agregar nueva entrada
            new_crontab = current_crontab + f"\n# MiniClaw CronJob: {cronjob.name}\n{cron_entry}\n"
            
            # Instalar nuevo crontab
            subprocess.run(
                ['crontab', '-'],
                input=new_crontab,
                text=True
            )
            
        except Exception as e:
            print(f"Error registering system cron: {e}")
    
    def _unregister_system_cron(self, job_id: str):
        """Eliminar cronjob del sistema operativo"""
        try:
            # Obtener crontab actual
            result = subprocess.run(
                ['crontab', '-l'],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return
            
            # Filtrar entradas relacionadas con este job
            lines = result.stdout.split('\n')
            filtered_lines = []
            skip = False
            
            for i, line in enumerate(lines):
                if f"# MiniClaw CronJob" in line or f"# MiniClaw CronJob" in line:
                    skip = True
                    continue
                if skip and line.strip().startswith('#'):
                    skip = False
                if not skip:
                    filtered_lines.append(line)
            
            # Actualizar crontab
            new_crontab = '\n'.join(filtered_lines)
            subprocess.run(
                ['crontab', '-'],
                input=new_crontab,
                text=True
            )
            
        except Exception as e:
            print(f"Error unregistering system cron: {e}")


# Instancia global de la API
api = CronjobAPI()


class APIHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler para la API"""
    
    def _send_json(self, status: int, data: Dict[str, Any]):
        """Enviar respuesta JSON"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        """Manejar GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/cronjobs':
            # Listar todos los cronjobs
            self._send_json(200, {
                "status": "success",
                "data": api.list_cronjobs()
            })
        elif path.startswith('/api/cronjobs/'):
            # Obtener un cronjob específico o logs
            parts = path.split('/')
            job_id = parts[-1]
            if parts[-2] == 'logs':
                self._send_json(200, api.get_logs(job_id))
            else:
                cronjob = api.get_cronjob(job_id)
                if cronjob:
                    self._send_json(200, {
                        "status": "success",
                        "data": cronjob.to_dict()
                    })
                else:
                    self._send_json(404, {"status": "error", "message": "No encontrado"})
        else:
            self._send_json(404, {"status": "error", "message": "Endpoint no encontrado"})
    
    def do_POST(self):
        """Manejar POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/cronjobs':
            # Crear nuevo cronjob
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode()
            
            try:
                data = json.loads(body)
                result = api.create_cronjob(data)
                
                if result["status"] == "success":
                    self._send_json(201, result)
                else:
                    self._send_json(400, result)
                    
            except json.JSONDecodeError:
                self._send_json(400, {"status": "error", "message": "JSON inválido"})
                
        elif path.startswith('/api/cronjobs/'):
            # Ejecutar un cronjob ahora
            parts = path.split('/')
            if parts[-1] == 'run':
                job_id = parts[-2]
                self._send_json(200, api.run_now(job_id))
            else:
                self._send_json(404, {"status": "error", "message": "Endpoint no encontrado"})
        else:
            self._send_json(404, {"status": "error", "message": "Endpoint no encontrado"})
    
    def do_PUT(self):
        """Manejar PUT requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path.startswith('/api/cronjobs/'):
            # Actualizar cronjob
            job_id = path.split('/')[-1]
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode()
            
            try:
                data = json.loads(body)
                result = api.update_cronjob(job_id, data)
                
                if result["status"] == "success":
                    self._send_json(200, result)
                else:
                    self._send_json(404, result)
                    
            except json.JSONDecodeError:
                self._send_json(400, {"status": "error", "message": "JSON inválido"})
        else:
            self._send_json(404, {"status": "error", "message": "Endpoint no encontrado"})
    
    def do_DELETE(self):
        """Manejar DELETE requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path.startswith('/api/cronjobs/'):
            # Eliminar cronjob
            job_id = path.split('/')[-1]
            result = api.delete_cronjob(job_id)
            
            if result["status"] == "success":
                self._send_json(200, result)
            else:
                self._send_json(404, result)
        else:
            self._send_json(404, {"status": "error", "message": "Endpoint no encontrado"})
    
    def log_message(self, format, *args):
        """Log personalizado"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")


def run_server():
    """Iniciar el servidor API"""
    server = HTTPServer((HOST, PORT), APIHandler)
    print(f"🚀 Servidor API de CronJobs ejecutándose en http://{HOST}:{PORT}")
    print(f"📋 Endpoints disponibles:")
    print(f"   GET    /api/cronjobs              - Listar todos")
    print(f"   GET    /api/cronjobs/<id>         - Obtener uno")
    print(f"   GET    /api/cronjobs/<id>/logs    - Ver logs")
    print(f"   POST   /api/cronjobs              - Crear")
    print(f"   POST   /api/cronjobs/<id>/run     - Ejecutar ahora")
    print(f"   PUT    /api/cronjobs/<id>         - Actualizar")
    print(f"   DELETE /api/cronjobs/<id>         - Eliminar")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Servidor detenido")
        server.shutdown()


if __name__ == "__main__":
    run_server()
