#!/usr/bin/env python3
"""
Tests Unitarios para módulo de CronJobs
Agente: MiniMax-M2.1
Fecha: 2026-02-26
"""

import os
import sys
import json
import unittest
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

# Agregar directorio tools al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.cronjobs_model import Cronjob, CronjobManager, CronParser, CronjobStatus


class TestCronParser(unittest.TestCase):
    """Tests para el parser de expresiones cron"""
    
    def test_parse_basic(self):
        """Test parsing de expresión básica"""
        result = CronParser.parse("0 6 * * *")
        
        self.assertEqual(result["minute"], [0])
        self.assertEqual(result["hour"], [6])
        self.assertEqual(result["day"], list(range(1, 32)))
        self.assertEqual(result["month"], list(range(1, 13)))
        self.assertEqual(result["weekday"], list(range(0, 7)))
    
    def test_parse_wildcard(self):
        """Test wildcard (*)"""
        result = CronParser.parse("* * * * *")
        
        self.assertEqual(result["minute"], list(range(60)))
        self.assertEqual(result["hour"], list(range(24)))
    
    def test_parse_range(self):
        """Test rango con guión"""
        result = CronParser.parse("0 9-17 * * *")
        
        self.assertEqual(result["minute"], [0])
        self.assertEqual(result["hour"], [9, 10, 11, 12, 13, 14, 15, 16, 17])
    
    def test_parse_list(self):
        """Test lista con comas"""
        result = CronParser.parse("0 0,6,12,18 * * *")
        
        self.assertEqual(result["minute"], [0])
        self.assertEqual(result["hour"], [0, 6, 12, 18])
    
    def test_parse_mixed(self):
        """Test expresión mixta"""
        result = CronParser.parse("0,30 9-17 1,15 * *")
        
        self.assertEqual(result["minute"], [0, 30])
        self.assertEqual(result["hour"], [9, 10, 11, 12, 13, 14, 15, 16, 17])
        self.assertEqual(result["day"], [1, 15])
    
    def test_to_human_readable(self):
        """Test conversión a texto legible"""
        human = CronParser.to_human_readable("0 6 * * *")
        self.assertIn("6", human)
        
        human = CronParser.to_human_readable("30 * * * *")
        self.assertIn("30", human)
    
    def test_invalid_expression(self):
        """Test expresión inválida"""
        with self.assertRaises(ValueError):
            CronParser.parse("0 6 *")  # Solo 3 campos


class TestCronjob(unittest.TestCase):
    """Tests para la clase Cronjob"""
    
    def setUp(self):
        """Setup para cada test"""
        self.job_data = {
            "id": "test-cron-001",
            "name": "Test CronJob",
            "expression": "0 6 * * *",
            "command": "python test.py",
            "description": "Un cronjob de prueba",
            "enabled": True
        }
    
    def test_create_cronjob(self):
        """Test creación de cronjob"""
        job = Cronjob(**self.job_data)
        
        self.assertEqual(job.id, "test-cron-001")
        self.assertEqual(job.name, "Test CronJob")
        self.assertEqual(job.expression, "0 6 * * *")
        self.assertEqual(job.command, "python test.py")
        self.assertEqual(job.enabled, True)
        self.assertEqual(job.status, CronjobStatus.ACTIVE)
    
    def test_cronjob_to_dict(self):
        """Test conversión a diccionario"""
        job = Cronjob(**self.job_data)
        job_dict = job.to_dict()
        
        self.assertEqual(job_dict["id"], "test-cron-001")
        self.assertEqual(job_dict["name"], "Test CronJob")
        self.assertEqual(job_dict["expression"], "0 6 * * *")
        self.assertEqual(job_dict["enabled"], True)
        self.assertEqual(job_dict["status"], "active")
    
    def test_cronjob_from_dict(self):
        """Test creación desde diccionario"""
        job = Cronjob(**self.job_data)
        job_dict = job.to_dict()
        
        restored_job = Cronjob.from_dict(job_dict)
        
        self.assertEqual(restored_job.id, job.id)
        self.assertEqual(restored_job.name, job.name)
        self.assertEqual(restored_job.expression, job.expression)
        self.assertEqual(restored_job.enabled, job.enabled)
    
    def test_cronjob_to_json(self):
        """Test conversión a JSON"""
        job = Cronjob(**self.job_data)
        json_str = job.to_json()
        
        # Verificar que es JSON válido
        data = json.loads(json_str)
        self.assertEqual(data["id"], "test-cron-001")
    
    def test_cronjob_status_enum(self):
        """Test estados del enum"""
        self.assertEqual(CronjobStatus.ACTIVE.value, "active")
        self.assertEqual(CronjobStatus.PAUSED.value, "paused")
        self.assertEqual(CronjobStatus.RUNNING.value, "running")
        self.assertEqual(CronjobStatus.FAILED.value, "failed")


class TestCronjobManager(unittest.TestCase):
    """Tests para el gestor de cronjobs"""
    
    def setUp(self):
        """Setup con archivo temporal"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_file.write('{"version": "1.0", "last_update": "2026-02-26T00:00:00", "cronjobs": {}}')
        self.temp_file.close()
        self.manager = CronjobManager(self.temp_file.name)
    
    def tearDown(self):
        """Cleanup"""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_add_cronjob(self):
        """Test agregar cronjob"""
        job = Cronjob(
            id="test-001",
            name="Test Job",
            expression="0 6 * * *",
            command="echo test"
        )
        
        result = self.manager.add(job)
        self.assertTrue(result)
        self.assertEqual(len(self.manager.list_all()), 1)
    
    def test_add_duplicate(self):
        """Test agregar duplicado"""
        job1 = Cronjob(id="dup-001", name="Job 1", expression="* * * * *", command="cmd1")
        job2 = Cronjob(id="dup-001", name="Job 2", expression="* * * * *", command="cmd2")
        
        self.manager.add(job1)
        result = self.manager.add(job2)
        
        self.assertFalse(result)
        self.assertEqual(len(self.manager.list_all()), 1)
    
    def test_get_cronjob(self):
        """Test obtener cronjob por ID"""
        job = Cronjob(id="get-001", name="Test", expression="* * * * *", command="test")
        self.manager.add(job)
        
        retrieved = self.manager.get("get-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Test")
    
    def test_get_nonexistent(self):
        """Test obtener cronjob inexistente"""
        result = self.manager.get("nonexistent")
        self.assertIsNone(result)
    
    def test_update_cronjob(self):
        """Test actualizar cronjob"""
        job = Cronjob(id="update-001", name="Original", expression="* * * * *", command="test")
        self.manager.add(job)
        
        result = self.manager.update("update-001", name="Actualizado", enabled=False)
        
        self.assertTrue(result)
        updated_job = self.manager.get("update-001")
        self.assertEqual(updated_job.name, "Actualizado")
        self.assertEqual(updated_job.enabled, False)
    
    def test_update_nonexistent(self):
        """Test actualizar inexistente"""
        result = self.manager.update("nonexistent", name="Test")
        self.assertFalse(result)
    
    def test_delete_cronjob(self):
        """Test eliminar cronjob"""
        job = Cronjob(id="delete-001", name="Test", expression="* * * * *", command="test")
        self.manager.add(job)
        
        result = self.manager.delete("delete-001")
        self.assertTrue(result)
        self.assertEqual(len(self.manager.list_all()), 0)
    
    def test_delete_nonexistent(self):
        """Test eliminar inexistente"""
        result = self.manager.delete("nonexistent")
        self.assertFalse(result)
    
    def test_list_enabled(self):
        """Test listar solo habilitados"""
        job1 = Cronjob(id="e1", name="Enabled", expression="* * * * *", command="test", enabled=True)
        job2 = Cronjob(id="e2", name="Disabled", expression="* * * * *", command="test", enabled=False)
        
        self.manager.add(job1)
        self.manager.add(job2)
        
        enabled = self.manager.list_enabled()
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "Enabled")
    
    def test_persistence(self):
        """Test persistencia de datos"""
        job = Cronjob(id="persist-001", name="Persistence Test", expression="* * * * *", command="test")
        self.manager.add(job)
        
        # Crear nuevo manager (simula reinicio)
        new_manager = CronjobManager(self.temp_file.name)
        
        self.assertEqual(len(new_manager.list_all()), 1)
        restored_job = new_manager.get("persist-001")
        self.assertEqual(restored_job.name, "Persistence Test")


class TestCronjobAPI(unittest.TestCase):
    """Tests para la API REST"""
    
    def setUp(self):
        """Setup con archivo temporal"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_file.write('{"version": "1.0", "last_update": "2026-02-26T00:00:00", "cronjobs": {}}')
        self.temp_file.close()
    
    def tearDown(self):
        """Cleanup"""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    @patch('tools.cronjobs_api.subprocess')
    def test_create_cronjob_valid(self, mock_subprocess):
        """Test crear cronjob con expresión válida"""
        from tools.cronjobs_api import CronjobAPI
        
        api = CronjobAPI()
        result = api.create_cronjob({
            "name": "Test API",
            "expression": "0 6 * * *",
            "command": "echo test"
        })
        
        self.assertEqual(result["status"], "success")
        self.assertIn("cron-", result["data"]["id"])
    
    @patch('tools.cronjobs_api.subprocess')
    def test_create_cronjob_invalid_expression(self, mock_subprocess):
        """Test crear cronjob con expresión inválida"""
        from tools.cronjobs_api import CronjobAPI
        
        api = CronjobAPI()
        result = api.create_cronjob({
            "name": "Invalid",
            "expression": "invalid expression",
            "command": "echo test"
        })
        
        self.assertEqual(result["status"], "error")
        self.assertIn("inválida", result["message"])


class TestIntegration(unittest.TestCase):
    """Tests de integración"""
    
    def test_full_crud_workflow(self):
        """Test flujo completo CRUD"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        temp_file.write('{"version": "1.0", "last_update": "2026-02-26T00:00:00", "cronjobs": {}}')
        temp_file.close()
        
        try:
            # Create
            manager = CronjobManager(temp_file.name)
            job = Cronjob(
                id="integration-test",
                name="Integration Test",
                expression="0 6 * * *",
                command="python integration.py"
            )
            manager.add(job)
            
            # Read
            retrieved = manager.get("integration-test")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.name, "Integration Test")
            
            # Update
            manager.update("integration-test", name="Updated Name")
            updated = manager.get("integration-test")
            self.assertEqual(updated.name, "Updated Name")
            
            # List
            all_jobs = manager.list_all()
            self.assertEqual(len(all_jobs), 1)
            
            # Delete
            manager.delete("integration-test")
            deleted = manager.get("integration-test")
            self.assertIsNone(deleted)
            
        finally:
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
    
    def test_model_to_api_to_model(self):
        """Test conversión modelo -> API -> modelo"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        temp_file.write('{"version": "1.0", "last_update": "2026-02-26T00:00:00", "cronjobs": {}}')
        temp_file.close()
        
        try:
            from tools.cronjobs_api import CronjobAPI
            
            # Create via API
            api = CronjobAPI()
            api.create_cronjob({
                "name": "Model API Test",
                "expression": "0 6 * * *",
                "command": "test"
            })
            
            # Read via Manager
            manager = CronjobManager(temp_file.name)
            job = manager.get("cron-1")
            
            self.assertIsNotNone(job)
            self.assertEqual(job.name, "Model API Test")
            
            # Verify cron parsing still works
            parsed = CronParser.parse(job.expression)
            self.assertEqual(parsed["minute"], [0])
            self.assertEqual(parsed["hour"], [6])
            
        finally:
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)


if __name__ == '__main__':
    # Ejecutar tests
    unittest.main(verbosity=2)
