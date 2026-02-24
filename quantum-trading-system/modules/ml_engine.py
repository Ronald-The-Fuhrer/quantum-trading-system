"""
ML Engine - Machine Learning model training and prediction
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
import logging
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
import xgboost as xgb
import lightgbm as lgb
import pickle
import os

logger = logging.getLogger(__name__)


class MLEngine:
    """Machine Learning Engine for trading predictions"""
    
    def __init__(self, config: Dict, data_manager):
        self.config = config
        self.data_manager = data_manager
        self.models = {}
        self.scalers = {}
        self.feature_importance = {}
        self.performance_metrics = {}
        self.model_dir = 'data/models'
        
        # Create model directory
        os.makedirs(self.model_dir, exist_ok=True)
    
    def prepare_features(self, df: pd.DataFrame) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Prepare features for ML training"""
        if df is None or len(df) < 100:
            return None, None
        
        feature_cols = [
            'RSI', 'MACD', 'MACD_Signal', 'ADX', 'ATR', 'NATR',
            'OBV', 'AD', 'CCI', 'STOCH_K', 'STOCH_D', 'WILLR',
            'BB_Width', 'Volume_Ratio', 'Volatility', 'MOM', 'ROC', 'MFI'
        ]
        
        available_features = [col for col in feature_cols if col in df.columns]
        
        if len(available_features) < 5:
            logger.warning("Insufficient features available")
            return None, None
        
        # Create target (next day return > 0)
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        df = df.dropna()
        
        if len(df) < 100:
            return None, None
        
        X = df[available_features].values
        y = df['Target'].values
        
        return X[:-1], y[:-1]  # Remove last row (no future data)
    
    def train_all_models(self, tickers: List[str]):
        """Train ML models for all tickers"""
        logger.info(f"Training ML models for {len(tickers)} tickers...")
        
        successful = 0
        failed = 0
        
        for ticker in tickers:
            try:
                df = self.data_manager.fetch_historical_data(ticker, period='2y')
                if df is not None and len(df) > 100:
                    self.train_ensemble(ticker, df)
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Error training models for {ticker}: {e}")
                failed += 1
        
        logger.info(f"✓ Model training complete: {successful} successful, {failed} failed")
    
    def train_ensemble(self, ticker: str, df: pd.DataFrame):
        """Train ensemble of ML models for a ticker"""
        X, y = self.prepare_features(df)
        
        if X is None or len(X) < 100:
            logger.warning(f"Insufficient data for training {ticker}")
            return
        
        # Scale features
        scaler = RobustScaler()
        X_scaled = scaler.fit_transform(X)
        self.scalers[ticker] = scaler
        
        # Time series split for validation
        tscv = TimeSeriesSplit(n_splits=5)
        
        models_dict = {}
        
        try:
            # Random Forest
            rf = RandomForestClassifier(
                n_estimators=200,
                max_depth=10,
                min_samples_split=20,
                random_state=42,
                n_jobs=-1
            )
            rf.fit(X_scaled, y)
            models_dict['rf'] = rf
            
            # XGBoost
            xgb_model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=-1
            )
            xgb_model.fit(X_scaled, y)
            models_dict['xgb'] = xgb_model
            
            # LightGBM
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=-1,
                verbose=-1
            )
            lgb_model.fit(X_scaled, y)
            models_dict['lgb'] = lgb_model
            
            # Gradient Boosting
            gb = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
            gb.fit(X_scaled, y)
            models_dict['gb'] = gb
            
            self.models[ticker] = models_dict
            
            # Evaluate models
            self._evaluate_models(ticker, X_scaled, y, tscv)
            
            # Save models
            self._save_models(ticker, models_dict, scaler)
            
            logger.info(f"✓ Trained {len(models_dict)} models for {ticker}")
            
        except Exception as e:
            logger.error(f"Error in ensemble training for {ticker}: {e}")
    
    def _evaluate_models(self, ticker: str, X: np.ndarray, y: np.ndarray, cv):
        """Evaluate model performance"""
        metrics = {}
        
        for name, model in self.models[ticker].items():
            try:
                scores = cross_val_score(model, X, y, cv=cv, scoring='accuracy')
                metrics[name] = {
                    'accuracy': scores.mean(),
                    'std': scores.std()
                }
            except Exception as e:
                logger.error(f"Error evaluating {name} for {ticker}: {e}")
        
        self.performance_metrics[ticker] = metrics
        logger.debug(f"Model performance for {ticker}: {metrics}")
    
    def predict(self, ticker: str, current_features: pd.DataFrame) -> Tuple[int, float]:
        """Get ensemble prediction"""
        if ticker not in self.models or ticker not in self.scalers:
            logger.debug(f"No model available for {ticker}")
            return 0, 0.5
        
        feature_cols = [
            'RSI', 'MACD', 'MACD_Signal', 'ADX', 'ATR', 'NATR',
            'OBV', 'AD', 'CCI', 'STOCH_K', 'STOCH_D', 'WILLR',
            'BB_Width', 'Volume_Ratio', 'Volatility', 'MOM', 'ROC', 'MFI'
        ]
        
        available_features = [col for col in feature_cols if col in current_features.columns]
        
        if not available_features:
            return 0, 0.5
        
        try:
            X = current_features[available_features].values
            X_scaled = self.scalers[ticker].transform(X)
            
            predictions = []
            confidences = []
            
            for name, model in self.models[ticker].items():
                pred = model.predict(X_scaled)[0]
                prob = model.predict_proba(X_scaled)[0]
                predictions.append(pred)
                confidences.append(max(prob))
            
            # Weighted voting based on model performance
            if ticker in self.performance_metrics:
                weights = [
                    self.performance_metrics[ticker].get(name, {}).get('accuracy', 0.5)
                    for name in self.models[ticker].keys()
                ]
                weighted_pred = np.average(predictions, weights=weights)
                weighted_conf = np.average(confidences, weights=weights)
            else:
                weighted_pred = np.mean(predictions)
                weighted_conf = np.mean(confidences)
            
            signal = 1 if weighted_pred > 0.5 else (-1 if weighted_pred < 0.5 else 0)
            
            return signal, weighted_conf
            
        except Exception as e:
            logger.error(f"Error predicting for {ticker}: {e}")
            return 0, 0.5
    
    def _save_models(self, ticker: str, models_dict: Dict, scaler):
        """Save trained models to disk"""
        try:
            model_path = os.path.join(self.model_dir, f'{ticker}_models.pkl')
            scaler_path = os.path.join(self.model_dir, f'{ticker}_scaler.pkl')
            
            with open(model_path, 'wb') as f:
                pickle.dump(models_dict, f)
            
            with open(scaler_path, 'wb') as f:
                pickle.dump(scaler, f)
                
        except Exception as e:
            logger.error(f"Error saving models for {ticker}: {e}")
    
    def load_models(self, ticker: str) -> bool:
        """Load trained models from disk"""
        try:
            model_path = os.path.join(self.model_dir, f'{ticker}_models.pkl')
            scaler_path = os.path.join(self.model_dir, f'{ticker}_scaler.pkl')
            
            if not os.path.exists(model_path) or not os.path.exists(scaler_path):
                return False
            
            with open(model_path, 'rb') as f:
                self.models[ticker] = pickle.load(f)
            
            with open(scaler_path, 'rb') as f:
                self.scalers[ticker] = pickle.load(f)
            
            logger.debug(f"✓ Loaded models for {ticker}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading models for {ticker}: {e}")
            return False
    
    def get_feature_importance(self, ticker: str) -> Dict:
        """Get feature importance for a ticker"""
        if ticker not in self.models:
            return {}
        
        importance = {}
        
        for name, model in self.models[ticker].items():
            if hasattr(model, 'feature_importances_'):
                importance[name] = model.feature_importances_.tolist()
        
        return importance