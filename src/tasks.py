"""
Celery tasks for background processing
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta
import asyncio
from typing import Dict, Any

# Import local modules
from src.database import DatabaseManager
from src.forecasting.xgboost_model import XGBoostForecaster

logger = get_task_logger(__name__)


@shared_task(name='src.tasks.generate_forecast_task')
def generate_forecast_task() -> Dict[str, Any]:
    """
    Generate forecast for all SKUs with different horizons
    Scheduled to run every 4 hours
    """
    try:
        logger.info("Starting forecast generation task")
        
        # Initialize components
        db = DatabaseManager()
        forecaster = XGBoostForecaster()
        
        # Generate forecasts for different horizons
        results = []
        for horizon in [7, 14, 28]:
            logger.info(f"Generating forecast for {horizon} days horizon")
            
            # Run forecast
            forecast_result = asyncio.run(
                forecaster.generate_forecast(horizon=horizon)
            )
            
            results.append({
                'horizon': horizon,
                'run_id': forecast_result.get('run_id'),
                'skus_processed': len(forecast_result.get('forecasts', [])),
                'timestamp': datetime.utcnow().isoformat()
            })
            
            logger.info(f"Forecast completed for {horizon} days: {forecast_result.get('run_id')}")
        
        # Close database connection
        asyncio.run(db.close())
        
        return {
            'status': 'success',
            'message': 'Forecast generation completed',
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Forecast generation failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@shared_task(name='src.tasks.check_stock_alerts_task')
def check_stock_alerts_task() -> Dict[str, Any]:
    """
    Check for stock alerts (low stock conditions)
    Scheduled to run every hour
    """
    try:
        logger.info("Starting stock alerts check")
        
        db = DatabaseManager()
        
        # Check for low stock conditions
        alerts_created = asyncio.run(db.check_and_create_stock_alerts())
        
        logger.info(f"Stock alerts check completed: {alerts_created} new alerts")
        
        asyncio.run(db.close())
        
        return {
            'status': 'success',
            'alerts_created': alerts_created,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Stock alerts check failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@shared_task(name='src.tasks.check_expiration_alerts_task')
def check_expiration_alerts_task() -> Dict[str, Any]:
    """
    Check for product expiration alerts
    Scheduled to run daily at 6 AM
    """
    try:
        logger.info("Starting expiration alerts check")
        
        db = DatabaseManager()
        
        # Check for products expiring in the next 30 days
        expiration_date = datetime.utcnow() + timedelta(days=30)
        alerts_created = asyncio.run(
            db.check_and_create_expiration_alerts(expiration_date)
        )
        
        logger.info(f"Expiration alerts check completed: {alerts_created} new alerts")
        
        asyncio.run(db.close())
        
        return {
            'status': 'success',
            'alerts_created': alerts_created,
            'checked_until': expiration_date.isoformat(),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Expiration alerts check failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@shared_task(name='src.tasks.update_model_metrics_task')
def update_model_metrics_task() -> Dict[str, Any]:
    """
    Update model performance metrics
    Scheduled to run daily at 2 AM
    """
    try:
        logger.info("Starting model metrics update")
        
        db = DatabaseManager()
        forecaster = XGBoostForecaster()
        
        # Calculate and update metrics
        metrics = asyncio.run(forecaster.calculate_performance_metrics())
        
        # Store metrics in database
        asyncio.run(db.store_model_metrics(metrics))
        
        logger.info(f"Model metrics updated: MAPE={metrics.get('mape', 'N/A')}%")
        
        asyncio.run(db.close())
        
        return {
            'status': 'success',
            'metrics': metrics,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Model metrics update failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@shared_task(name='src.tasks.cleanup_old_data_task')
def cleanup_old_data_task() -> Dict[str, Any]:
    """
    Clean up old data from the database
    Scheduled to run weekly on Sunday at 3 AM
    """
    try:
        logger.info("Starting data cleanup task")
        
        db = DatabaseManager()
        
        # Define retention periods
        retention_config = {
            'forecast_history': 90,  # Keep 90 days of forecast history
            'alerts_resolved': 30,   # Keep 30 days of resolved alerts
            'logs': 7,               # Keep 7 days of logs
        }
        
        # Perform cleanup
        cleanup_results = {}
        for data_type, retention_days in retention_config.items():
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            rows_deleted = asyncio.run(
                db.cleanup_old_data(data_type, cutoff_date)
            )
            cleanup_results[data_type] = rows_deleted
            logger.info(f"Cleaned up {rows_deleted} rows from {data_type}")
        
        asyncio.run(db.close())
        
        return {
            'status': 'success',
            'cleanup_results': cleanup_results,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Data cleanup failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@shared_task(name='src.tasks.retrain_model_task')
def retrain_model_task(force: bool = False) -> Dict[str, Any]:
    """
    Retrain the XGBoost model with latest data
    Can be triggered manually or scheduled
    """
    try:
        logger.info("Starting model retraining task")
        
        forecaster = XGBoostForecaster()
        
        # Check if retraining is needed
        if not force:
            needs_retraining = asyncio.run(forecaster.check_retraining_needed())
            if not needs_retraining:
                logger.info("Model retraining not needed at this time")
                return {
                    'status': 'skipped',
                    'message': 'Model performance within acceptable range',
                    'timestamp': datetime.utcnow().isoformat()
                }
        
        # Perform retraining
        training_results = asyncio.run(forecaster.retrain_model())
        
        logger.info(f"Model retraining completed: {training_results}")
        
        return {
            'status': 'success',
            'training_results': training_results,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Model retraining failed: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }