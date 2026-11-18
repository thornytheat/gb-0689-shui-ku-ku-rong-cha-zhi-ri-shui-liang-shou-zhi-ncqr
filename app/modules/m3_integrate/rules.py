from collections import defaultdict
from decimal import Decimal as D
def _gross_from_signed(a,b,seconds):
    # 带符号流量在一段内的梯形积分，按线性过零点把正、负半段分别累计为进库/出库毛量，
    # 避免“净量抵消后两端各记一次”或把整段净值只挂一个方向。
    qa,qb=a['signed_flow'],b['signed_flow']
    net=(qa+qb)/2*seconds
    if qa==qb or qa*qb>=0:
        gross_in=net if net>0 else D(0);gross_out=(-net) if net<0 else D(0)
    else:
        # 过零点把梯形切成两个三角形：各自面积=0.5*|端值|*该半段时长。
        frac=(-qa)/(qb-qa)
        gross_in=abs(qa)/2*seconds*(frac if qa>0 else 1-frac)
        gross_out=abs(qb)/2*seconds*((1-frac) if qb<0 else frac)
    return net,gross_in,gross_out
def integrate(rows,max_gap):
    stations=defaultdict(list)
    for row in rows:stations[row['station']].append(row)
    parts=[];gaps=[]
    for station,items in sorted(stations.items()):
        items=sorted(items,key=lambda r:r['time'])
        for a,b in zip(items,items[1:]):
            seconds=D(str((b['time']-a['time']).total_seconds()))
            if seconds>max_gap*3600:
                gaps.append({'station':station,'start':a['time'],'end':b['time'],'hours':seconds/3600,'code':'GAP','state':'缺测'});continue
            pump=a.get('flow_mode')=='pump' or b.get('flow_mode')=='pump'
            part={'station':station,'start':a['time'],'end':b['time'],'left':a,'right':b,'flow_mode':'pump' if pump else 'legacy'}
            if pump:
                part['net_m3'],part['in_m3'],part['out_m3']=_gross_from_signed(a,b,seconds)
            else:
                part['in_m3']=(a['inflow']+b['inflow'])/2*seconds
                part['out_m3']=(a['outflow']+b['outflow'])/2*seconds
                part['net_m3']=part['in_m3']-part['out_m3']
            parts.append(part)
    return parts,gaps
