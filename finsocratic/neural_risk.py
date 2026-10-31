"""Chronological early stopping and validation-selected neural ensembles."""
import copy
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import mean_absolute_error


class RiskEnsemble:
    def __init__(self, members, offset, scale, weight, base_index, base_mean, base_scale):
        self.members=members; self.offset=offset; self.scale=scale; self.weight=weight
        self.base_index=base_index; self.base_mean=base_mean; self.base_scale=base_scale
        self.n_iter_=sum(m.n_iter_ for m in members)
        self.loss_curve_=members[0].loss_curve_

    def predict(self,x):
        estimates=np.mean([m.predict(x)*self.scale+self.offset for m in self.members],axis=0)
        baseline=x[:,self.base_index]*self.base_scale+self.base_mean
        return np.maximum(self.weight*estimates+(1-self.weight)*baseline,0)


def fit_risk_ensemble(x,y,xval,yval,scaler):
    # Normalize targets using training data only. Keep chronological validation external.
    offset=float(np.mean(y)); scale=max(float(np.std(y)),1e-6)
    members=[]; details=[]
    for seed in (17,42,73):
        net=MLPRegressor(hidden_layer_sizes=(32,16),alpha=1.,random_state=seed,
                         learning_rate_init=.001,early_stopping=False,batch_size=256)
        best=None; best_score=float('inf'); stale=0
        for epoch in range(160):
            net.partial_fit(x,(y-offset)/scale)
            score=mean_absolute_error(yval,np.maximum(net.predict(xval)*scale+offset,0))
            if score < best_score-1e-4:
                best_score=score;best=copy.deepcopy(net);stale=0;best_epoch=epoch+1
            else: stale+=1
            if stale>=15:break
        best.n_iter_=best_epoch
        members.append(best)
        details.append({'seed':seed,'best_epoch':best_epoch,'epochs_run':epoch+1,'validation_mae':best_score})
    candidates=[]
    for weight in (.25,.5,.75,1.):
        model=RiskEnsemble(members,offset,scale,weight,0,scaler.mean_[0],scaler.scale_[0])
        candidates.append((mean_absolute_error(yval,model.predict(xval)),model))
    score,chosen=min(candidates,key=lambda pair:pair[0])
    return chosen,{'members':details,'neural_weight':chosen.weight,'validation_mae':score,
                    'selection':'3 fixed seeds; validation early stopping; 4 fixed neural/persistence blends; no test-based selection',
                    'validation_candidates':[{'neural_weight':m.weight,'mae':s} for s,m in candidates]}
