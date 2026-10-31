import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import eval_props as ep
from sklearn.linear_model import Ridge

pl = ep.load()
d, ic = ep.build("pass_yds", pl)
tr, te = d[(d.season < 2024) & (d.season >= 2021)], d[d.season == 2024]
X = lambda x: x[ep.FEATS].fillna(x[ep.FEATS].mean()).values
rg = Ridge(alpha=10).fit(X(tr), tr.y)
mu = np.maximum(rg.predict(X(tr)), 0.3)
a, b = ep.fit_var(mu, (tr.y.values - mu) ** 2)
print("a,b", a, b, "mu range", mu.min(), mu.max(), "resid sd", (tr.y - mu).std())
mt = rg.predict(X(te))
print("pred var sd", np.sqrt(a * mt ** b).mean(), "te resid sd", (te.y - mt).std())
print(te[["y", "line", "med8", "ew6"]].describe().T[["mean", "std"]])
print("mean(mu-line)", (mt - te.line).mean(), "std", (mt - te.line).std())
print(rg.coef_, dict(zip(ep.FEATS, np.round(rg.coef_, 3))))
