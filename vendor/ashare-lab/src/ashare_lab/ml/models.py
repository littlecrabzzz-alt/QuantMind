"""符号平均、纯 NumPy 岭回归和延迟导入的 LightGBM。"""

import numpy as np


class SignedAverage:
    def __init__(self):
        self.info = {}

    def fit(self, X_train, y_train, X_valid, y_valid):
        self.signs = np.sign(X_train.corrwith(y_train).fillna(0).to_numpy())
        self.info = {"signs": self.signs.tolist()}
        return self

    def predict(self, X):
        return X.to_numpy() @ self.signs / len(self.signs)


class Ridge:
    def __init__(self, lambdas=(0.1, 1, 10, 100)):
        self.lambdas = lambdas
        self.info = {}

    def fit(self, X_train, y_train, X_valid, y_valid):
        self.x_mean = X_train.to_numpy().mean(axis=0)
        self.y_mean = float(y_train.mean())
        X = X_train.to_numpy() - self.x_mean
        y = y_train.to_numpy() - self.y_mean
        gram, rhs = X.T @ X, X.T @ y
        best = np.inf
        for lam in self.lambdas:
            coef = np.linalg.solve(gram + lam * len(X) * np.eye(X.shape[1]), rhs)
            prediction = (X_valid.to_numpy() - self.x_mean) @ coef + self.y_mean
            mse = np.mean((prediction - y_valid.to_numpy()) ** 2)
            if mse < best:
                best, self.coef = mse, coef
                self.info = {"lambda": lam, "coef": coef.tolist()}
        return self

    def predict(self, X):
        return (X.to_numpy() - self.x_mean) @ self.coef + self.y_mean


class LGBM:
    def __init__(self, params=None):
        self.params = {
            "objective": "regression", "metric": "l2", "num_leaves": 15,
            "learning_rate": 0.05, "min_data_in_leaf": 200,
            "feature_fraction": 0.8, "bagging_fraction": 0.8,
            "bagging_freq": 1, "lambda_l2": 1, "seed": 0, "verbosity": -1,
            **(params or {}),
        }
        self.info = {}

    def fit(self, X_train, y_train, X_valid, y_valid):
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise ImportError("lgbm 方法需要 lightgbm；当前未安装，请用 --methods 排除 lgbm") from exc
        train = lgb.Dataset(X_train, label=y_train)
        valid = lgb.Dataset(X_valid, label=y_valid, reference=train)
        self.model = lgb.train(self.params, train, num_boost_round=500,
                               valid_sets=[valid], callbacks=[lgb.early_stopping(50, verbose=False)])
        self.info = {
            "best_iteration": self.model.best_iteration,
            "importance_gain": dict(zip(X_train.columns,
                                        self.model.feature_importance(importance_type="gain"))),
        }
        return self

    def predict(self, X):
        return self.model.predict(X, num_iteration=self.model.best_iteration)
