#!/usr/bin/env python3
"""
Tests Unitarios para módulo de CronJobs (Actualizado para Agno)
"""

import os
import sys
import json
import unittest
import tempfile
from unittest.mock import patch, MagicMock

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.scheduler import JadaScheduler
from agno.scheduler.cron import validate_cron_expr

class TestCronjobAPI(unittest.TestCase):
    """Tests para la lógica de Cronjobs via Agno Tools"""
    
    def setUp(self):
        """Setup con callback mock"""
        self.mock_callback = MagicMock()
        self.scheduler = JadaScheduler(self.mock_callback)
        
    def test_create_cronjob_valid(self):
        """Test crear cronjob con expresión válida (usando cron_expr)"""
        job = self.scheduler.add_job(
            job_id="test-api-001",
            name="Test API",
            cron_expr="0 6 * * *",
            prompt="hola",
            room_id="room1"
        )
        
        self.assertEqual(job["name"], "Test API")
        self.assertEqual(job["cron_expr"], "0 6 * * *")
        
    def test_invalid_expression(self):
        """Verificar validación de expresión cron"""
        self.assertFalse(validate_cron_expr("invalid"))
        self.assertTrue(validate_cron_expr("0 6 * * *"))

class TestIntegration(unittest.TestCase):
    """Integration style tests for scheduler"""

    def test_model_to_api_to_model(self):
        """Test minimal data flow with correct field names"""
        mock_cb = MagicMock()
        sched = JadaScheduler(mock_cb)
        
        # Test add through scheduler logic
        job = sched.add_job(
            job_id="cron-1",
            name="Model API Test",
            cron_expr="0 6 * * *",
            prompt="test",
            room_id="room1"
        )
        
        self.assertEqual(job["name"], "Model API Test")
        self.assertEqual(job["cron_expr"], "0 6 * * *")

if __name__ == '__main__':
    unittest.main(verbosity=2)
