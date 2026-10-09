import numpy as np
rng = np.random.default_rng(42)
N_SUB = 16  # bitmask subsets of |Omega|=4; index 0 = empty set
NE = list(range(1,16))

def dempster(b, q):
    g = np.zeros(16)
    for a in range(1,16):
        if b[a]==0: continue
        for c in range(1,16):
            if q[c]==0: continue
            g[a & c] += b[a]*q[c]
    K = g[0]; s = 1-K
    if s <= 0: return None, K
    out = g.copy(); out[0]=0.0; out /= s
    return out, K

def rand_bpa(k=None):
    m = np.zeros(16)
    if k is None:
        m[1:] = rng.dirichlet(np.ones(15)*0.3)
    else:
        idx = rng.choice(NE, size=k, replace=False)
        m[idx] = rng.dirichlet(np.ones(k))
    return m

# ---- 1) Theorem 1: empirical Lipschitz ratio vs 3/(2 delta) ----
print("== Theorem 1: L_delta empirical check ==")
for delta in [0.05,0.1,0.15,0.2,0.3,0.5]:
    worst = 0.0; n_ok = 0
    for _ in range(60000):
        b = rand_bpa(rng.integers(1,4))
        q = rand_bpa(rng.integers(1,4))
        Fq, K1 = dempster(b,q)
        if Fq is None or 1-K1 < delta: continue
        # local perturbation (approximates sup) + occasional global pair
        if rng.random()<0.7:
            eta = np.zeros(16); eta[1:] = rng.normal(size=15)
            qp = q.copy(); qp[1:] = np.clip(q[1:] + 1e-4*eta[1:],0,None)
            if qp[1:].sum()==0: continue
            qp[1:] /= qp[1:].sum()
        else:
            qp = rand_bpa(rng.integers(1,4))
        Fqp, K2 = dempster(b,qp)
        if Fqp is None: continue
        dq = np.abs(q-qp).sum()
        if dq < 1e-12: continue
        ratio = np.abs(Fq-Fqp).sum()/dq
        worst = max(worst, ratio); n_ok += 1
    print(f" delta={delta:0.2f}  bound 3/(2d)={1.5/delta:7.2f}  1/d={1/delta:6.2f}  max_ratio={worst:7.3f}  n={n_ok}")

# ---- 2) Proposition 0: exact-duplicate invariance of pooling ----
print("\n== Prop 0: pooling invariance ==")
def pool(group_msgs, alpha_cap=0.1):
    # msg: (claim_id, mass, reliability); dedup by claim_id (root+hash+bucket collapsed to claim_id here)
    seen = {}
    for cid, m, r in group_msgs:
        if cid not in seen or r > seen[cid][1]:
            seen[cid] = (m, r)
    reps = list(seen.values())
    w = np.array([r for _,r in reps]); w = w/w.sum()*alpha_cap
    q = np.zeros(16); q[15] = 1.0 - w.sum()  # vacuous remainder
    for (m,_),wi in zip(reps,w):
        dm = m*0.0; dm[1:] = m[1:]  # already BPA
        q += wi*dm
        q[15] -= wi*m[15]*0  # m includes its own Omega mass; mixture handles it
    return q
mA = np.zeros(16); mA[2]=0.8; mA[15]=0.2   # supports {w1}
base = [("c1", mA, 0.7)]
q1 = pool(base)
q20 = pool(base*20)
print(f" ||q(1 msg) - q(20 dup)||_1 = {np.abs(q1-q20).sum():.2e}")

# ---- 3) Report-11 counterexample & analytic limit ----
print("\n== Cumulative influence counterexample (per-message cap fails) ==")
r, gamma, dt = 0.1, 0.01, 1.0
alpha = np.exp(-gamma*dt)
x = 0.0
for n in range(100):
    x = r + alpha*(1-r)*x
x_inf = r/(1-alpha*(1-r))
print(f" simulated Bel after 100 msgs = {x:.6f}   analytic limit = {x_inf:.6f}")
# full D-S simulation on Omega=4 to cross-check the scalar recursion
B = np.zeros(16); B[15]=1.0
mH = np.zeros(16); mH[2]=1.0  # {w1}
for n in range(100):
    B = np.exp(-gamma*dt)*B + (1-np.exp(-gamma*dt))*np.eye(16)[15]  # predict toward vacuous
    Dm = r*mH; Dm[15] += 1-r
    B,_ = dempster(B, Dm)
print(f" full D-S simulation Bel({{w1}}) after 100 msgs = {B[2]:.6f}")
