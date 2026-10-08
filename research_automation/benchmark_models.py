"""Exact Shockley and implicit series-resistance comparison models.

Adapted from the user-approved pair demonstration; coefficients are effective
comparison parameters. No mechanism, intrinsic contact resistance or barrier claim.
"""
from types import SimpleNamespace
import numpy as np
from scipy.optimize import least_squares
from scipy.special import wrightomega

LOW2=np.log([1e-18,0.001]); HIGH2=np.log([1e-2,100.])

def model_current(x, Is, a, Rs=0.):
    """Exact implicit Shockley+Rs solution, including the minus-one term."""
    x=np.asarray(x,dtype=float)
    if not Is>0 or not a>0 or not Rs>=0:raise ValueError('다이오드 비교식 계수는 Is>0, a>0, Rs≥0이어야 합니다.')
    if Rs == 0: return Is*np.expm1(np.clip(x/a,-700,700))
    y=a/Rs*wrightomega(np.log(Is*Rs/a)+(x+Is*Rs)/a)-Is
    return np.where(x==0,0.,y)

def decode(p, model):
    return float(np.exp(p[0])),float(np.exp(p[1])),float(p[2]*1e6) if model=='Shockley+Rs' else 0.

def initial(x,y):
    slope,intercept=np.polyfit(x,np.log(y),1)
    a=np.clip(1/max(slope,0.001),0.005,30.)
    Is=np.clip(np.median(y/np.expm1(np.clip(x/a,1e-10,700))),1e-17,1e-3)
    return np.log(Is),np.log(a)

def fit_branch(x,y,model):
    x=np.asarray(x,float);y=np.asarray(y,float)
    if model not in ('Shockley','Shockley+Rs') or len(x)<5 or len(x)!=len(y) or len(np.unique(x))<5 or not np.all(np.isfinite(x)&np.isfinite(y)&(x>0)&(y>0)):
        raise ValueError('극성별 모델에는 서로 다른 전압의 유효한 양의 전류점 5개 이상이 필요합니다.')
    seed=np.array(initial(x,y))
    low=LOW2 if model=='Shockley' else np.r_[LOW2,0.]
    high=HIGH2 if model=='Shockley' else np.r_[HIGH2,1e5]
    starts=[seed] if model=='Shockley' else [np.r_[seed,r] for r in (0.,0.3,3.)]
    def residual(p):
        pred=model_current(x,*decode(p,model))
        return np.log(np.maximum(pred,1e-300))-np.log(y)
    trials=[]
    for seed in starts:
        f=least_squares(residual,np.clip(seed,low+1e-12,high-1e-12),bounds=(low,high),
            x_scale='jac',max_nfev=600,ftol=1e-10,xtol=1e-10,gtol=1e-10)
        trials.append(f)
    f=min(trials,key=lambda f:float(np.sum(f.fun**2)))
    Is,a,Rs=decode(f.x,model)
    pred=model_current(x,Is,a,Rs)
    e=pred-y
    jac=f.jac
    norm=np.linalg.norm(jac,axis=0)
    sv=np.linalg.svd(jac/np.maximum(norm,1e-300),compute_uv=False)
    cond=float(sv[0]/max(sv[-1],1e-300)) if np.linalg.matrix_rank(jac)==len(f.x) else float('inf')
    covariance=np.linalg.pinv(jac.T@jac)
    sd=np.sqrt(np.maximum(np.diag(covariance),0))
    corr=covariance/np.maximum(np.outer(sd,sd),1e-300)
    rho=float(corr[1,2]) if model=='Shockley+Rs' else np.nan
    near_bound=bool(np.any(f.x-low<1e-6) or np.any(high-f.x<1e-6))
    residual_voltage=a*np.log1p(pred/Is)+pred*Rs-x
    return {'model':model,'Is_A':Is,'a_V':a,'Rs_ohm':Rs,'n_points':len(x),
        'RMSE_ln':float(np.sqrt(np.mean(f.fun**2))),
        'RMSE_A':float(np.sqrt(np.mean(e**2))),
        'NRMSE_span_pct':float(np.sqrt(np.mean(e**2))/(np.max(y)-np.min(y))*100) if np.ptp(y)>0 else None,
        'max_abs_relative_error_pct':float(np.max(np.abs(e/y))*100),
        'corr_a_Rs_local':rho,'jacobian_normalized_condition':cond,
        'near_parameter_bound':near_bound,'optimizer_success':bool(f.success),
        'implicit_max_error_V':float(np.max(np.abs(residual_voltage))),
        'nfev':int(f.nfev),'params':f.x.tolist(),
        'multi_start_log_SSE':[float(np.sum(t.fun**2)) for t in trials]}, pred

def fit_signed(v,y,model,n_fixed,thermal):
    """A conventional single-diode reference over both polarities, not a mechanism claim."""
    v=np.asarray(v,float);y=np.asarray(y,float)
    if len(v)<5 or len(v)!=len(y) or not np.all(np.isfinite(v)&np.isfinite(y)) or not np.any(v>0) or not np.any(v<0) or not np.any(y):raise ValueError('양극성 단일 다이오드 비교에는 양·음 전압의 유효 원본점이 필요합니다.')
    if n_fixed is not None and (thermal is None or thermal<=0):raise ValueError('n 고정 비교에는 온도 근거가 필요합니다.')
    jref=float(np.median(np.abs(y)))
    if jref<=0:raise ValueError('양극성 비교의 전류 규모를 정의할 수 없습니다.')
    candidates=[]
    for sign in (-1,1):
        if n_fixed is not None and model=='Shockley':
            # The fixed-n model is linear in Is. Solve it exactly; its small Is
            # is allowed rather than forcing the free-n model's search floor.
            a=float(n_fixed*thermal)
            basis=sign*np.expm1(sign*v/a)
            Is=float(np.clip(np.dot(basis,y)/np.dot(basis,basis),1e-100,1e-2))
            pred=Is*basis
            candidates.append((float(np.sum((pred-y)**2)),sign,
                SimpleNamespace(success=True),Is,a,0.,pred))
            continue
        pos=sign*v>0
        logIs,loga=initial(np.abs(v[pos]),np.abs(y[pos]))
        free_a=n_fixed is None
        base=[logIs]+([loga] if free_a else [])
        low=[LOW2[0]]+([LOW2[1]] if free_a else [])+([0] if model=='Shockley+Rs' else [])
        high=[HIGH2[0]]+([HIGH2[1]] if free_a else [])+([1e5] if model=='Shockley+Rs' else [])
        def decode_signed(p):
            a=float(np.exp(p[1])) if free_a else float(n_fixed*thermal)
            Rs=float(p[-1]*1e6) if model=='Shockley+Rs' else 0.
            return float(np.exp(p[0])),a,Rs
        def residual(p):
            return (sign*model_current(sign*v,*decode_signed(p))-y)/jref
        for r in ((0.,0.3,3.) if model=='Shockley+Rs' else (None,)):
            seed=base+([r] if r is not None else [])
            f=least_squares(residual,np.clip(seed,np.array(low)+1e-12,np.array(high)-1e-12),
                bounds=(low,high),x_scale='jac',max_nfev=1000)
            Is,a,Rs=decode_signed(f.x)
            pred=sign*model_current(sign*v,Is,a,Rs)
            candidates.append((float(np.sum((pred-y)**2)),sign,f,Is,a,Rs,pred))
    _,sign,f,Is,a,Rs,pred=min(candidates,key=lambda r:r[0])
    e=pred-y
    out={'model':model,'a_V':a,'n_effective':a/thermal if thermal else np.nan,'Is_A':Is,'Rs_ohm':Rs,
        'orientation':sign,'n_fixed':n_fixed,'n_points':len(v),
        'RMSE_A':float(np.sqrt(np.mean(e**2))),
        'NRMSE_span_pct':float(np.sqrt(np.mean(e**2))/(np.max(y)-np.min(y))*100) if np.ptp(y)>0 else None,
        'optimizer_success':bool(f.success)}
    for s,label in ((1,'positive'),(-1,'negative')):
        ee=e[v*s>0]
        out[f'RMSE_{label}_A']=float(np.sqrt(np.mean(ee**2)))
    return out,pred
