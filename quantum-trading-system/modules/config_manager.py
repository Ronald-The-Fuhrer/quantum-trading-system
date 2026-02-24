"""
Configuration Manager - Handles all configuration loading and validation
"""

import json
import os
from enum import Enum
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class TradingMode(Enum):
    """Trading modes"""
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


class ConfigManager:
    """Manages system configuration"""
    
    def __init__(self, config_path: str = 'config.json'):
        self.config_path = config_path
        self.config = self._load_config()
        self._validate_config()
        self._load_environment_variables()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        try:
            if not os.path.exists(self.config_path):
                logger.error(f"Config file not found: {self.config_path}")
                raise FileNotFoundError(f"Config file not found: {self.config_path}")
            
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            logger.info(f"✓ Configuration loaded from {self.config_path}")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise
    
    def _validate_config(self):
        """Validate critical configuration parameters"""
        required_fields = [
            'trading_mode',
            'initial_capital',
            'max_position_size',
            'max_drawdown',
            'strategies_enabled'
        ]
        
        missing = [field for field in required_fields if field not in self.config]
        if missing:
            raise ValueError(f"Missing required config fields: {missing}")
        
        # Validate ranges
        if not 0 < self.config['max_position_size'] <= 1:
            raise ValueError("max_position_size must be between 0 and 1")
        
        if not 0 < self.config['max_drawdown'] <= 1:
            raise ValueError("max_drawdown must be between 0 and 1")
        
        if self.config['initial_capital'] <= 0:
            raise ValueError("initial_capital must be positive")
        
        # Validate trading mode
        try:
            TradingMode(self.config['trading_mode'])
        except ValueError:
            raise ValueError(f"Invalid trading_mode: {self.config['trading_mode']}")
        
        logger.info("✓ Configuration validated")
    
    def _load_environment_variables(self):
        """Load sensitive data from environment variables"""
        env_mappings = {
            'ALPACA_KEY': 'alpaca_key',
            'ALPACA_SECRET': 'alpaca_secret',
            'NEWS_API_KEY': 'news_api_key',
            'ALPHA_VANTAGE_KEY': 'alpha_vantage_key',
            'POLYGON_API_KEY': 'polygon_api_key',
            'TWITTER_API_KEY': 'twitter_api_key',
            'TWITTER_API_SECRET': 'twitter_api_secret'
        }
        
        for env_var, config_key in env_mappings.items():
            if env_value := os.getenv(env_var):
                self.config[config_key] = env_value
                logger.debug(f"Loaded {config_key} from environment")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value"""
        self.config[key] = value
    
    def save(self):
        """Save current configuration to file"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"✓ Configuration saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise
    
    def get_strategy_config(self, strategy_name: str) -> Dict:
        """Get configuration for specific strategy"""
        return {
            'enabled': strategy_name in self.config.get('strategies_enabled', []),
            'weight': self.config.get('strategy_weights', {}).get(strategy_name, 0.1),
            'params': self.config.get('strategy_params', {}).get(strategy_name, {})
        }
    
    def is_strategy_enabled(self, strategy_name: str) -> bool:
        """Check if strategy is enabled"""
        return strategy_name in self.config.get('strategies_enabled', [])
    
    def get_risk_params(self) -> Dict:
        """Get all risk management parameters"""
        return {
            'max_position_size': self.get('max_position_size', 0.05),
            'max_portfolio_risk': self.get('max_portfolio_risk', 0.02),
            'max_drawdown': self.get('max_drawdown', 0.15),
            'max_leverage': self.get('max_leverage', 1.0),
            'max_correlation': self.get('max_correlation', 0.7),
            'var_confidence': self.get('var_confidence', 0.95),
            'kelly_fraction': self.get('kelly_fraction', 0.25),
            'stop_loss_pct': self.get('stop_loss_pct', 0.02),
            'take_profit_pct': self.get('take_profit_pct', 0.06)
        }
    
    def get_ml_config(self) -> Dict:
        """Get ML configuration"""
        return {
            'enabled': self.get('enable_ml', True),
            'models': self.get('ml_models', []),
            'retrain_frequency': self.get('retrain_frequency_days', 1),
            'min_samples': self.get('min_training_samples', 252),
            'cv_folds': self.get('cross_validation_folds', 5)
        }
    
    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access"""
        return self.config[key]
    
    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator"""
        return key in self.config