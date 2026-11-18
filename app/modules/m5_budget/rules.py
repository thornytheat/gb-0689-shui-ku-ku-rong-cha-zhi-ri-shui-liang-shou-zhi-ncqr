from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from collections import defaultdict
# Public pure interpolation is deliberately passed in by the service.
def _point(left,right,duration,frac,key):
    return left[key]+(right[key]-left[key])*frac
def _time_at(start,duration,frac):
    return start+timedelta(seconds=float(duration*frac))
def day_budget(flows,curve,interpolate):
    zone=timezone(timedelta(hours=8));buckets=defaultdict(lambda:{'in_m3':D(0),'out_m3':D(0),'net_m3':D(0),'storage_change':D(0),'coverage_hours':D(0),'flow_mode':'legacy'})
    for part in flows:
        left,right=part['left'],part['right'];start,end=part['start'],part['end'];duration=D(str((end-start).total_seconds()));cursor=start;pump=part.get('flow_mode')=='pump'
        def at(t,key):return left[key]+(right[key]-left[key])*D(str((t-start).total_seconds()))/duration
        if pump:
            # 断点以段内比例(Decimal)表示：午夜日界与带符号流量过零点，保证水量仍按精确十进制解析式积分。
            cuts={D(0),D(1)}
            local=start.astimezone(zone);midnight=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),zone)
            if start<midnight<end:cuts.add(D(str((midnight-start).total_seconds()))/duration)
            if left['signed_flow']!=right['signed_flow']:
                frac=D(-left['signed_flow'])/(right['signed_flow']-left['signed_flow'])
                if D(0)<frac<D(1):cuts.add(frac)
            seq=sorted(cuts)
            for f0,f1 in zip(seq,seq[1:]):
                t0,t1=_time_at(start,duration,f0),_time_at(start,duration,f1)
                day=t0.astimezone(zone).date().isoformat();b=buckets[(part['station'],day)];b['flow_mode']='pump'
                q0=_point(left,right,duration,f0,'signed_flow');q1=_point(left,right,duration,f1,'signed_flow')
                net=(q0+q1)/2*duration*(f1-f0)
                b['net_m3']+=net
                if net>0:b['in_m3']+=net
                elif net<0:b['out_m3']+=-net
                b['storage_change']+=interpolate(_point(left,right,duration,f1,'level'),curve)-interpolate(_point(left,right,duration,f0,'level'),curve)
                b['coverage_hours']+=duration*(f1-f0)/3600
            continue
        while cursor<end:
            local=cursor.astimezone(zone);midnight=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),zone)
            stop=min(end,midnight);seconds=D(str((stop-cursor).total_seconds()))
            b=buckets[(part['station'],local.date().isoformat())]
            b['in_m3']+=(at(cursor,'inflow')+at(stop,'inflow'))/2*seconds
            b['out_m3']+=(at(cursor,'outflow')+at(stop,'outflow'))/2*seconds
            b['net_m3']=b['in_m3']-b['out_m3']
            b['storage_change']+=interpolate(at(stop,'level'),curve)-interpolate(at(cursor,'level'),curve)
            b['coverage_hours']+=seconds/3600;cursor=stop
    result=[]
    for (station,day),values in sorted(buckets.items()):
        # 净量恒等于进库减出库（含换向抵消），整段净水量据此与日账对账。
        residual=values['storage_change']-values['in_m3']+values['out_m3']
        result.append({'station':station,'date':day,**values,'residual':residual,'state':'完整' if values['coverage_hours']==24 else '缺测'})
    return result
