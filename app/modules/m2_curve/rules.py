from app.normalize import number,instant
from app.errors import DomainError
from decimal import Decimal as D
from collections import defaultdict
from app.reasons import rejected
def validate_curve(points):
    if not isinstance(points,list) or len(points)<2:raise DomainError('CURVE','库容曲线至少两个点')
    try:curve=[(number(p[0]),number(p[1])) for p in points]
    except (TypeError,IndexError):raise DomainError('CURVE','曲线格式无效')
    if any(v<0 for _,v in curve) or any(b[0]<=a[0] or b[1]<=a[1] for a,b in zip(curve,curve[1:])):raise DomainError('CURVE','曲线必须严格递增')
    return curve
def normalize(row,curve):
    out=dict(row);out['time']=instant(row['time']);out['level']=number(row['level'])
    if row.get('flow_unit')=='L/s':div=D(1000)
    elif row.get('flow_unit')=='m3/s':div=D(1)
    else:raise DomainError('UNIT','流量单位无效')
    pump=bool(str(row.get('signed_flow','')).strip())
    if pump:
        # 双向泵站：只采信带符号流量；再填旧式两列属于契约矛盾，避免把两端重复计入。
        if str(row.get('inflow','')).strip() or str(row.get('outflow','')).strip():
            raise DomainError('RANGE','泵站只报带符号流量，不得同时填报进出流量')
        signed=number(row['signed_flow'])/div
        out['signed_flow']=signed;out['inflow']=D(0);out['outflow']=D(0);out['flow_mode']='pump'
    else:
        out['inflow']=number(row['inflow'])/div;out['outflow']=number(row['outflow'])/div;out['signed_flow']=None;out['flow_mode']='legacy'
        if out['inflow']<0 or out['outflow']<0:raise DomainError('RANGE','流量或水位越界')
    if not curve[0][0]<=out['level']<=curve[-1][0]:raise DomainError('RANGE','流量或水位越界')
    v=number(row['version'])
    if v<1 or v!=v.to_integral():raise DomainError('RANGE','测次版本无效')
    out['version']=int(v);out['flow_unit']='m3/s';return out
def select(rows):
    groups=defaultdict(list)
    for row in rows:groups[(row['station'],row['time'])].append(row)
    good=[];bad=[]
    for key,group in sorted(groups.items()):
        latest=max(x['version'] for x in group);top=[x for x in group if x['version']==latest]
        sig=lambda x:(x['level'],x['inflow'],x['outflow'],x['signed_flow'])
        if len({sig(x) for x in top})>1:bad.extend(rejected(x,'CONFLICT','同刻水文值矛盾') for x in group);continue
        winner=min(top,key=lambda x:x['_line']);good.append(winner);bad.extend(rejected(x,'DUPLICATE','重复或旧版测次') for x in group if x is not winner)
    return good,bad
