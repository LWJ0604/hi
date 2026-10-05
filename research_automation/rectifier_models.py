"""Optional effective rectifier fits in current space; no physical winner claims."""
import numpy as np
from scipy.optimize import least_squares
from scipy.special import wrightomega

PARAMETER_COUNTS={'exponential':4,'independent':6,'shared_a_j0':4,'shared_a':5}


def predict_current(u,rs,a,j0):
    u=np.asarray(u,dtype=float)
    if rs==0:return np.exp(np.clip(np.log(j0)+u/a,-700,700))
    return a/rs*wrightomega(np.log(rs*j0/a)+u/a)


def decode(model,parameters,jref):
    p=parameters
    if model=='exponential':return [(0.,np.exp(p[0]),jref*np.exp(p[1])),(0.,np.exp(p[2]),jref*np.exp(p[3]))]
    if model=='independent':return [(p[0]/jref,np.exp(p[1]),jref*np.exp(p[2])),(p[3]/jref,np.exp(p[4]),jref*np.exp(p[5]))]
    if model=='shared_a_j0':return [(p[0]/jref,np.exp(p[2]),jref*np.exp(p[3])),(p[1]/jref,np.exp(p[2]),jref*np.exp(p[3]))]
    return [(p[0]/jref,np.exp(p[2]),jref*np.exp(p[3])),(p[1]/jref,np.exp(p[2]),jref*np.exp(p[4]))]


def model_prediction(model,p,u,polarity,jref):
    decoded=decode(model,p,jref); values=np.empty(len(u))
    for sign,params in zip((1,-1),decoded):
        mask=polarity==sign;values[mask]=predict_current(u[mask],*params)
    return values


def setup(model,u,current,polarity,jref):
    estimates=[]
    for sign in (1,-1):
        mask=polarity==sign; slope,offset=np.polyfit(u[mask],np.log(current[mask]/jref),1)
        estimates.append((np.log(np.clip(1/max(slope,.1),.01,10)),np.clip(offset,-30,5)))
    la,lj=np.mean(estimates,axis=0)
    if model=='exponential':start=[*estimates[0],*estimates[1]];low=[-7,-35]*2;high=[3,7]*2
    elif model=='independent':start=[.1,*estimates[0],.1,*estimates[1]];low=[0,-7,-35]*2;high=[1e4,3,7]*2
    elif model=='shared_a_j0':start=[.1,.1,la,lj];low=[0,0,-7,-35];high=[1e4,1e4,3,7]
    else:start=[.1,.1,la,estimates[0][1],estimates[1][1]];low=[0,0,-7,-35,-35];high=[1e4,1e4,3,7,7]
    return np.array(start),np.array(low),np.array(high)


def fit_effective_models(frame,cfg):
    if not cfg.data['science']['rectifier_models_enabled']:return {'model_status':'not_run','reason':'optional_models_disabled','models':[]}
    lower,upper=cfg.data['science']['rectifier_range_v']
    voltage=frame['vd'].to_numpy();current=np.abs(frame['id'].to_numpy());u=np.abs(voltage);polarity=np.sign(voltage)
    eligible=np.asarray(frame.get('metric_eligible',np.ones(len(frame),dtype=bool))) & (u>=lower)&(u<=upper)&(current>0)
    limit=cfg.data['science']['detection_limit_a'] if cfg.data['science']['detection_limit_evidence'] else None
    if limit:eligible&=current>=limit
    indices=np.flatnonzero(eligible); u=u[eligible];current=current[eligible];polarity=polarity[eligible]
    counts=[np.sum(polarity==sign) for sign in (1,-1)]
    if min(counts,default=0)<6:return {'model_status':'not_run','reason':'need_six_positive_and_six_negative_valid_points','models':[],'window_v':[lower,upper]}
    # The SAME scale/points/current-space loss are shared by every candidate.
    jref=float(np.median(current));holdout=np.zeros(len(u),dtype=bool)
    for sign in (1,-1):
        selected=np.flatnonzero(polarity==sign);ordered=selected[np.argsort(u[selected])]
        holdout[ordered[-max(2,len(ordered)//5):]]=True
    training=~holdout;results=[]
    for model in cfg.data['science']['rectifier_models']:
        try:
            start,low,high=setup(model,u[training],current[training],polarity[training],jref)
            def residual(p,mask=training):return (model_prediction(model,p,u[mask],polarity[mask],jref)-current[mask])/jref
            trials=[]
            for factor in (.5,1.,2.):
                trial=np.clip(start+np.log(factor)*np.array([0 if l==0 else 1 for l in low]),low+1e-10,high-1e-10)
                trials.append(least_squares(residual,trial,bounds=(low,high),max_nfev=1500,ftol=1e-10,xtol=1e-10,gtol=1e-10))
            fit=min(trials,key=lambda fit:float(np.sum(fit.fun**2)))
            prediction=model_prediction(model,fit.x,u,polarity,jref);error=prediction-current
            scaled=fit.jac/np.maximum(np.linalg.norm(fit.jac,axis=0),np.finfo(float).tiny)
            singular=np.linalg.svd(scaled,compute_uv=False);condition=float(min(singular[0]/max(singular[-1],np.finfo(float).tiny),np.finfo(float).max))
            normalized_params=decode(model,fit.x,jref)
            unit_parameters={'positive':dict(zip(('rs_ohm','a_v','j0_a'),normalized_params[0])), 'negative':dict(zip(('rs_ohm','a_v','j0_a'),normalized_params[1]))}
            with np.errstate(invalid='ignore',divide='ignore'):
                correlation=np.corrcoef(scaled.T)
            np.fill_diagonal(correlation,0)
            largest=float(np.max(np.abs(correlation[np.isfinite(correlation)]))) if np.isfinite(correlation).any() else 1.
            missing_correlation=not np.isfinite(correlation).all()
            boundary=bool(np.any(np.minimum(fit.x-low,high-fit.x)<1e-5))
            status='failed' if not fit.success else 'unstable' if boundary else 'poorly_identified' if condition>1e6 or largest>.995 or missing_correlation or np.sum(training)<=PARAMETER_COUNTS[model]+2 else 'converged'
            lag={}
            for sign,label in ((1,'positive'),(-1,'negative')):
                e=error[training & (polarity==sign)]
                lag[label]=float(np.corrcoef(e[:-1],e[1:])[0,1]) if len(e)>3 and np.std(e[:-1])>0 and np.std(e[1:])>0 else None
            sensitivity=[]
            for variant,mask in [('trim_low_voltage',training&(u>min(u[training]))),('trim_high_voltage',training&(u<max(u[training])))]:
                if np.sum(mask)>PARAMETER_COUNTS[model]+2:
                    alternate=least_squares(lambda p:(model_prediction(model,p,u[mask],polarity[mask],jref)-current[mask])/jref,fit.x,bounds=(low,high),max_nfev=600)
                    sensitivity.append({'variant':variant,'model_status':'converged' if alternate.success else 'failed','parameters':decode(model,alternate.x,jref)})
            rss=float(np.sum(error[training]**2));n=int(np.sum(training));k=PARAMETER_COUNTS[model]
            results.append({'model':model,'model_status':status,'n':n,'k':k,'parameters':unit_parameters,
                'parameter_units':{'rs_ohm':'ohm','a_v':'V','j0_a':'A'},'initial_values_scaled':start.tolist(),
                'bounds_scaled':[low.tolist(),high.tolist()],'convergence':{'success':bool(fit.success),'message':fit.message,'nfev':fit.nfev},
                'current_rmse_a':float(np.sqrt(np.mean(error[training]**2))),
                'heldout_rmse_a':float(np.sqrt(np.mean(error[holdout]**2))),
                'polarity_rmse_a':{label:float(np.sqrt(np.mean(error[training&(polarity==sign)]**2))) for sign,label in ((1,'positive'),(-1,'negative'))},
                'aic':float(2*k+n*np.log(max(rss/n,np.finfo(float).tiny))),
                'jacobian_condition':condition,'largest_jacobian_column_correlation':largest,
                'residual_lag1':lag,'parameter_confidence_interval':None,
                'confidence_interval_reason':'no iid CI asserted for potentially correlated residuals',
                'range_sensitivity':sensitivity,'current_scale_jref_a':jref,'loss':'same_points_squared_current_residual_divided_by_common_jref',
                'source_rows':[int(frame.iloc[i]['source_row']) for i in indices],
                'predicted_current_a':prediction.tolist(),'observed_abs_current_a':current.tolist(),'voltage_abs_v':u.tolist(),'polarity':polarity.tolist(),
                'heldout_mask':holdout.tolist(),'residual_current_a':error.tolist()})
        except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError) as error:
            results.append({'model':model,'model_status':'failed','reason':str(error)})
    return {'model_status':'candidate_comparison','models':results,'window_v':[lower,upper],
        'equation':'u=Rs*j+a*ln(j/j0), u=abs(Vd), j=abs(Id); exponential has Rs=0',
        'sharing':{'independent':'separate Rs,a,j0 per polarity (6)','shared_a_j0':'shared a and j0; separate Rs (4)','shared_a':'shared a; separate Rs and j0 (5)'},
        'interpretation':'effective fit coefficients only; no mechanism winner or contact/barrier conversion'}
