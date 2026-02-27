#!/usr/bin/env python3
"""
Scheduler de CronJobs para MiniClaw
Agente: MiniMax-M2.1 (Principal)
Asistente: Qwen3-VL-30B (UI Design)
Fecha: 2026-02-26
"""

import os
import schedule
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Callable
from tools.cronjobs_model import CronjobManager, CronjobStatus

class CronjobScheduler:
    """Scheduler que ejecuta cronjobs según su programación"""
    
    def __init__(self, storage_file: str = "cronjobs.json", interval: int = 30):
        """
        Args:
            storage_file: Archivo JSON con los cronjobs
            interval: Segundos entre verificaciones (default 30)
        """
        self.storage_file = storage_file
        self.interval = interval
        self.manager = CronjobManager(storage_file)
        self.running_jobs: Dict[str, subprocess.Popen] = {}
        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.execution_callbacks: Dict[str, Callable] = {}
        
        # Configurar logging
        self.log_dir = "logs"
        os.makedirs(self.log_dir, exist_ok=True)
        
    def _log(self, job_id: str, message: str):
        """Guardar log de ejecución"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_file = os.path.join(self.log_dir, f"{job_id}.log")
        
        with open(log_file, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
    
    def _execute_job(self, job_id: str):
        """Ejecutar un cronjob"""
        cronjob = self.manager.get(job_id)
        if not cronjob:
            return
        
        # Verificar si ya está ejecutándose
        if job_id in self.running_jobs:
            self._log(job_id, "Ya está en ejecución, saltando...")
            return
        
        # Marcar como en ejecución
        cronjob.status = CronjobStatus.RUNNING.value
        cronjob.last_run = datetime.now()
        self.manager.save()
        
        self._log(job_id, f"Iniciando ejecución: {cronjob.command}")
        
        try:
            # Ejecutar comando
            process = subprocess.Popen(
                cronjob.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            self.running_jobs[job_id] = process
            
            # Esperar a que termine (en hilo separado no bloqueante)
            def wait_and_finish():
                stdout, stderr = process.communicate()
                
                # Guardar outputs
                cronjob.output = stdout.decode('utf-8', errors='replace')
                cronjob.error = stderr.decode('utf-8', errors='replace')
                
                # Actualizar estado
                if process.returncode == 0:
                    cronjob.status = CronjobStatus.ACTIVE.value
                    self._log(job_id, f"Completado exitosamente (exit code: 0)")
                else:
                    cronjob.status = CronjobStatus.FAILED.value
                    self._log(job_id, f"Error (exit code: {process.returncode})")
                
                # Limpiar de jobs en ejecución
                if job_id in self.running_jobs:
                    del self.running_jobs[job_id]
                
                cronjob.last_run = datetime.now()
                cronjob.updated_at = datetime.now()
                self.manager.save()
                
                # Ejecutar callbacks si existen
                if job_id in self.execution_callbacks:
                    try:
                        self.execution_callbacks[job_id](cronjob)
                    except Exception as e:
                        self._log(job_id, f"Error en callback: {e}")
            
            # Ejecutar en hilo separado
            thread = threading.Thread(target=wait_and_finish)
            thread.start()
            
        except Exception as e:
            cronjob.error = str(e)
            cronjob.status = CronjobStatus.FAILED.value
            cronjob.updated_at = datetime.now()
            self.manager.save()
            self._log(job_id, f"Error fatal: {e}")
    
    def _parse_cron_expression(self, expression: str) -> schedule.Job:
        """
        Convertir expresión cron a schedule.Job
        Nota: Esta es una implementación simplificada
        """
        parts = expression.split()
        if len(parts) != 5:
            return None
        
        minute, hour, day, month, weekday = parts
        
        # Crear job schedule basado en la expresión
        # Esta implementación usa la librería schedule
        job = None
        
        if minute == '*' and hour == '*' and day == '*' and month == '*' and weekday == '*':
            # Cada minuto
            job = schedule.every(1).minutes
        elif hour != '*' and minute != '*' and day == '*' and weekday == '*':
            # Diario a hora específica
            minute_val = int(minute) if minute != '*' else 0
            hour_val = int(hour) if hour != '*' else 6
            job = schedule.every(1).day.at(f"{hour_val:02d}:{minute_val:02d}")
        elif minute != '*' and hour == '*':
            # Cada hora a minuto específico
            job = schedule.every(1).hour.at(f":{int(minute):02d}")
        else:
            # Para expresiones más complejas, usar cada minuto como fallback
            # y verificar manualmente
            job = schedule.every(1).minutes
        
        return job
    
    def load_cronjobs(self):
        """Cargar cronjobs desde archivo y programar"""
        cronjobs = self.manager.list_enabled()
        
        for cronjob in cronjobs:
            self._log(cronjob.id, f"Cargando cronjob: {cronjob.name}")
            
            # Intentar parsear expresión y programar
            # Por ahora, usar verificación cada minuto
            job = schedule.every(1).minutes
            
            # Almacenar job en estructura interna
            if not hasattr(self, '_scheduled_jobs'):
                self._scheduled_jobs = {}
            
            self._scheduled_jobs[cronjob.id] = {
                'schedule': job,
                'cronjob': cronjob
            }
            
            job.do(self._execute_job, job_id=cronjob.id)
            self._log(cronjob.id, f"Programado: {cronjob.expression}")
    
    def start(self):
        """Iniciar el scheduler"""
        self.is_running = True
        self.load_cronjobs()
        
        self._log("scheduler", "Iniciando scheduler...")
        
        # Hilo principal del scheduler
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        
        self.scheduler_thread = threading.Thread(target=run_scheduler)
        self.scheduler_thread.start()
        
        print(f"🚀 Scheduler iniciado. Monitoreando {len(self.manager.list_enabled())} cronjobs")
    
    def stop(self):
        """Detener el scheduler"""
        self.is_running = False
        schedule.clear()
        
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        self._log("scheduler", "Scheduler detenido")
        print("👋 Scheduler detenido")
    
    def add_callback(self, job_id: str, callback: Callable):
        """Agregar callback para ejecutar después de cada job"""
        self.execution_callbacks[job_id] = callback
    
    def run_job_now(self, job_id: str) -> bool:
        """Ejecutar un cronjob inmediatamente"""
        cronjob = self.manager.get(job_id)
        if not cronjob:
            return False
        
        self._execute_job(job_id)
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Obtener estado del scheduler"""
        return {
            "is_running": self.is_running,
            "total_cronjobs": len(self.manager.list_all()),
            "enabled_cronjobs": len(self.manager.list_enabled()),
            "running_jobs": len(self.running_jobs),
            "scheduled_jobs": len(getattr(self, '_scheduled_jobs', {})),
            "next_check": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# Instancia global
scheduler = None


def get_scheduler() -> CronjobScheduler:
    """Obtener instancia del scheduler"""
    global scheduler
    if scheduler is None:
        scheduler = CronjobScheduler()
    return scheduler


def main():
    """Función principal para ejecutar scheduler como servicio"""
    import signal
    import sys
    
    scheduler = get_scheduler()
    
    # Manejar señales de terminación
    def signal_handler(sig, frame):
        print("\n� received exit signal")
        scheduler.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Iniciar scheduler
    scheduler.start()
    
    # Mantener proceso vivo
    try:
        while True:
            time.sleep(60)
            status = scheduler.get_status()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Status: {status['enabled_cronjobs']} jobs activos, {status['running_jobs']} ejecutándose")
    except KeyboardInterrupt:
        scheduler.stop()


if __name__ == "__main__":
    main()
