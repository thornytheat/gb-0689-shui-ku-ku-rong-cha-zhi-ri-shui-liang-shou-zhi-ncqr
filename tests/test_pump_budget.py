import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.config import SAMPLES
from app.modules.m2_curve.rules import validate_curve,normalize,select
from app.modules.m3_integrate.rules import integrate
from app.modules.m5_budget.rules import day_budget
from app.modules.m4_storage.service import level_to_volume

CURVE=validate_curve([['100','0'],['102','30000'],['105','100000']])
def pump(time,signed,level='101',station='P'):
    return dict(station=station,time=instant(time),level=D(level),inflow=D(0),outflow=D(0),
                signed_flow=D(signed),flow_mode='pump')
def legacy(time,qin=1,qout=0,level='101',station='S'):
    return dict(station=station,time=instant(time),level=D(level),inflow=D(qin),outflow=D(qout),
                signed_flow=None,flow_mode='legacy')

def test_pump_signed_integral_direction():
    # 正值进库、负值出库。M3 同向段净值=梯形带符号积分；方向毛量在 M5 按过零点拆分后核对。
    parts,_=integrate([pump('2026-11-17T00:00:00Z','2'),pump('2026-11-17T01:00:00Z','2'),
                       pump('2026-11-17T02:00:00Z','-2'),pump('2026-11-17T03:00:00Z','-2')],D(2))
    # 恒+2 一小时进库7200；末段恒-2 一小时出库7200；中间段为换向（方向毛量由M5拆分）
    assert parts[0]['in_m3']==7200 and parts[0]['out_m3']==0 and parts[0]['net_m3']==7200
    assert parts[2]['net_m3']==-7200 and parts[2]['in_m3']==0 and parts[2]['out_m3']==7200
    days=day_budget(parts,CURVE,level_to_volume)
    # 中间换向段正、负三角各1800，故日进=7200+1800=9000、日出=7200+1800=9000，净量抵消为0
    assert days[0]['in_m3']==9000 and days[0]['out_m3']==9000 and days[0]['net_m3']==0

def test_pump_reversal_splits_directions():
    # 单段内由+2线性换向到-2：净量抵消为0，正、负两半各是三角形面积1800，不能当成同时双向过水
    parts,_=integrate([pump('2026-11-17T00:00:00Z','2'),pump('2026-11-17T01:00:00Z','-2')],D(2))
    days=day_budget(parts,CURVE,level_to_volume)
    assert len(days)==1
    row=days[0]
    assert row['net_m3']==0
    assert row['in_m3']==1800 and row['out_m3']==1800

def test_pump_midnight_reversal_split_across_days():
    # 跨午夜换向：+2 持续到午夜，午夜处为0，随后 -2；正、负半段分属两日
    parts,_=integrate([pump('2026-11-17T23:00:00+08:00','2'),pump('2026-11-18T01:00:00+08:00','-2')],D(2))
    days=day_budget(parts,CURVE,level_to_volume)
    assert len(days)==2
    first,second=days
    assert first['in_m3']==3600 and first['out_m3']==0 and first['net_m3']==3600
    assert second['in_m3']==0 and second['out_m3']==3600 and second['net_m3']==-3600

def test_pump_daily_net_reconciles_to_segment_net():
    parts,_=integrate([pump('2026-11-17T23:00:00+08:00','2'),pump('2026-11-18T01:00:00+08:00','-2')],D(2))
    days=day_budget(parts,CURVE,level_to_volume)
    assert sum((r['net_m3'] for r in days),D(0))==sum((p['net_m3'] for p in parts),D(0))
    assert all(r['in_m3']-r['out_m3']==r['net_m3'] for r in days)

def test_pump_partial_day_still_待补测():
    # 覆盖不足24h始终待补测，即使水量守恒也不插补
    parts,_=integrate([pump('2026-11-17T00:00:00Z','1'),pump('2026-11-17T01:00:00Z','1')],D(2))
    assert day_budget(parts,CURVE,level_to_volume)[0]['state']=='缺测'

def test_legacy_logs_unchanged():
    parts,_=integrate([legacy('2026-11-17T00:00:00Z'),legacy('2026-11-17T01:00:00Z')],D(2))
    days=day_budget(parts,CURVE,level_to_volume)
    r=days[0]
    assert r['flow_mode']=='legacy' and r['in_m3']==3600 and r['out_m3']==0 and r['net_m3']==3600

def test_pump_mixed_columns_rejected():
    row=dict(id='1',station='P',time='2026-11-17T00:00:00Z',level='101',inflow='1',outflow='',
             signed_flow='2',flow_unit='m3/s',version='1',_line=2)
    with pytest.raises(DomainError):normalize(row,CURVE)

def test_pump_l_per_second_conversion():
    row=dict(id='1',station='P',time='2026-11-17T00:00:00Z',level='101',inflow='',outflow='',
             signed_flow='-2000',flow_unit='L/s',version='1',_line=2)
    assert normalize(row,CURVE)['signed_flow']==D('-2')

def test_extra_column_still_quarantined():
    text=('id,station,time,level,inflow,outflow,flow_unit,version,signed_flow,extra\n'
          'X1,P,2026-11-17T00:00:00+08:00,100,,,m3/s,1,2,9,99\n')
    r=run(text,persist=False)
    assert any(q['code']=='COLUMN_COUNT' for q in r['quarantine'])
    assert r['records']==[]

def test_legacy_header_without_optional_column_pads():
    text=('id,station,time,level,inflow,outflow,flow_unit,version\n'
          'X1,S,2026-11-17T00:00:00Z,100,1,0,m3/s,1\n'
          'X2,S,2026-11-17T01:00:00Z,100,1,0,m3/s,1\n')
    r=run(text,stop=2,persist=False)
    assert len(r['records'])==2 and all(x['flow_mode']=='legacy' for x in r['records'])

def test_pump_conflict_signature_includes_signed():
    a=dict(pump('2026-11-17T00:00:00Z','2'),id='1',version=1,_line=2)
    b=dict(pump('2026-11-17T00:00:00Z','3'),id='2',version=1,_line=3)
    good,bad=select([a,b])
    assert not good and bad and all(x['code']=='CONFLICT' for x in bad)

def test_pump_pipeline_end_to_end(raw_pump,tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    result=run(raw_pump)
    pumps=[r for r in result['budgets'] if r['flow_mode']=='pump']
    legacy_rows=[r for r in result['budgets'] if r['flow_mode']=='legacy']
    assert pumps and legacy_rows
    # 净水量整段对账通过（M7 不守恒会抛错），且双向毛量分别可核对
    assert D(result['audit']['net_m3'])==D(result['audit']['day_net_m3'])
    assert D(result['audit']['out_m3'])==D(result['audit']['day_out_m3'])
    # 两个方向各走了多少水都可核对：存在进库为主的日，也存在出库为主的日
    assert any(D(r['in_m3'])>0 for r in pumps)
    assert any(D(r['out_m3'])>0 for r in pumps)
    assert all(D(r['in_m3'])-D(r['out_m3'])==D(r['net_m3']) for r in pumps)

def test_pump_idempotent_same_batch(raw_pump,tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    a=run(raw_pump);b=run(raw_pump)
    assert a['manifest']['run_id']==b['manifest']['run_id']

def test_pump_and_legacy_have_signed_field_in_evidence(raw_pump,tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    result=run(raw_pump,persist=False)
    assert all('signed_flow' in r and 'flow_mode' in r for r in result['records'])

@pytest.fixture
def raw_pump(): return (SAMPLES/'pump.csv').read_bytes()
