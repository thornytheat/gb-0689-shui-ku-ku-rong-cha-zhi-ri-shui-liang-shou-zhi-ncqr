from app.normalize import rows_from
from app.reasons import rejected
# 旧式日志使用 inflow/outflow 两列；双向泵站只报一列带符号流量 signed_flow（+进库/-出库）。
# signed_flow 为可选列（见 normalize.OPTIONAL_COLUMNS），旧式日志缺该列时按空值补齐、照常核算。
def receive(raw):
    result=rows_from(raw,['id','station','time','level','inflow','outflow','flow_unit','version'])
    good=[]
    for row in result['raw']:
        if not row['id'] or not row['station']:result['quarantine'].append(rejected(row,'MISSING','测次或测站缺失'))
        else:good.append(row)
    result['records']=good;return result
