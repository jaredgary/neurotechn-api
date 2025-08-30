"""
Celery configuration for background tasks and scheduled jobs
"""

from celery import Celery
from celery.schedules import crontab
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create Celery instance
app = Celery(
    'farmacias_siman',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    include=['src.tasks']
)

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Tegucigalpa',  # Honduras timezone
    enable_utc=True,
    result_expires=3600,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Scheduled tasks configuration
app.conf.beat_schedule = {
    # Generate forecast every 4 hours
    'generate-forecast-4h': {
        'task': 'src.tasks.generate_forecast_task',
        'schedule': crontab(minute=0, hour='*/4'),
        'args': (),
        'options': {
            'queue': 'forecast',
            'priority': 5,
        }
    },
    
    # Check for stock alerts every hour
    'check-stock-alerts': {
        'task': 'src.tasks.check_stock_alerts_task',
        'schedule': crontab(minute=30),
        'args': (),
        'options': {
            'queue': 'alerts',
            'priority': 8,
        }
    },
    
    # Check for expiration alerts daily at 6 AM
    'check-expiration-alerts': {
        'task': 'src.tasks.check_expiration_alerts_task',
        'schedule': crontab(minute=0, hour=6),
        'args': (),
        'options': {
            'queue': 'alerts',
            'priority': 7,
        }
    },
    
    # Update model metrics daily at 2 AM
    'update-model-metrics': {
        'task': 'src.tasks.update_model_metrics_task',
        'schedule': crontab(minute=0, hour=2),
        'args': (),
        'options': {
            'queue': 'metrics',
            'priority': 3,
        }
    },
    
    # Clean up old data weekly on Sunday at 3 AM
    'cleanup-old-data': {
        'task': 'src.tasks.cleanup_old_data_task',
        'schedule': crontab(minute=0, hour=3, day_of_week=0),
        'args': (),
        'options': {
            'queue': 'maintenance',
            'priority': 1,
        }
    },
}

# Queue routing configuration
app.conf.task_routes = {
    'src.tasks.generate_forecast_task': {'queue': 'forecast'},
    'src.tasks.check_stock_alerts_task': {'queue': 'alerts'},
    'src.tasks.check_expiration_alerts_task': {'queue': 'alerts'},
    'src.tasks.update_model_metrics_task': {'queue': 'metrics'},
    'src.tasks.cleanup_old_data_task': {'queue': 'maintenance'},
}

if __name__ == '__main__':
    app.start()