"""CLI sin red. Evalúa datos, nunca código propuesto por un modelo."""
import argparse,json,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from .evaluation import make_cases,public_cases,evaluate,loads_strict


def read_json(path):
    with Path(path).open('r',encoding='utf-8') as f:
        text=f.read(2_000_001)
    return loads_strict(text)


def main(argv=None):
    p=argparse.ArgumentParser(description='Laboratorio local: pruebas limitadas, no certificación de inteligencia/seguridad')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('cases',help='Ejercicios sintéticos públicos, no un holdout');a.add_argument('--seed',type=int,default=17);a.add_argument('--per-family',type=int,default=4);a.add_argument('--public',action='store_true')
    a=sub.add_parser('score',help='Evalúa un catálogo y una lista JSON de respuestas');a.add_argument('cases');a.add_argument('responses')
    a=sub.add_parser('forecast-score',help='Brier de resoluciones declaradas, sin verificar fuentes');a.add_argument('forecasts');a.add_argument('resolutions');a.add_argument('--now',default=None)
    a=sub.add_parser('backtest',help='Baselines retrospectivos de serie equiespaciada');a.add_argument('observations');a.add_argument('--min-train',type=int,default=4);a.add_argument('--horizon',type=int,default=1);a.add_argument('--seasonal-period',type=int,default=2)
    sub.add_parser('demo-control',help='Sólo calendario ficticio y aprobaciones de fixture; ninguna acción externa')
    args=p.parse_args(argv)
    try:
        if args.command=='cases':
            result=make_cases(args.seed,args.per_family)
            if args.public:result=public_cases(result)
        elif args.command=='score':result=evaluate(read_json(args.cases),read_json(args.responses))
        elif args.command=='forecast-score':
            from .forecasts import score_binary_forecasts
            now=args.now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            result=score_binary_forecasts(read_json(args.forecasts),read_json(args.resolutions),now)
        elif args.command=='backtest':
            from .forecasts import rolling_naive_backtest
            result=rolling_naive_backtest(read_json(args.observations),args.min_train,args.horizon,args.seasonal_period)
        else:
            from .authority import LocalAuthority,intent_digest
            with tempfile.TemporaryDirectory(prefix='laboratorio-demo-') as d:
                a=LocalAuthority(Path(d)/'fixture.sqlite3',clock=lambda:'2026-09-19T10:00:00Z')
                i={'schema_version':'C1.intent.v1','intent_id':'demo_intent','run_id':'demo_run','principal_id':'demo_agent','calendar_id':'demo_calendar','event_id':'demo_event','operation':'RESCHEDULE_EVENT','expected_version':0,'start_utc':'2026-09-20T10:00:00Z','end_utc':'2026-09-20T10:30:00Z'}
                a.create_event(i['calendar_id'],i['event_id'],'2026-09-20T08:00:00Z','2026-09-20T08:30:00Z',title='EVENTO FICTICIO')
                token=a.approve(i,original_request_digest=intent_digest(i),approver_id='fixture_not_a_human',expires_at='2026-09-19T11:00:00Z')
                def send(intent,approval,op):return a.execute(intent,approval_id=approval,operation_id=op,authenticated_principal='demo_agent')
                altered_denied=False
                try:send({**i,'start_utc':'2026-09-20T10:01:00Z'},token,'demo_altered')
                except PermissionError:altered_denied=True
                receipt=send(i,token,'demo_operation');again=send(i,token,'demo_operation')
                j={**i,'intent_id':'demo_next','expected_version':1}
                pending=a.approve(j,original_request_digest=intent_digest(j),approver_id='fixture_not_a_human',expires_at='2026-09-19T11:00:00Z')
                a.revoke_all();revoked_denied=False
                try:send(j,pending,'demo_revoked')
                except PermissionError:revoked_denied=True
                result={'synthetic_data':True,'synthetic_clock':True,'human_approval_performed':False,'external_effects':False,'altered_intent_denied':altered_denied,'replay_same_receipt':receipt==again,'revoked_intent_denied':revoked_denied,'final_event':a.get_event(i['calendar_id'],i['event_id']),'C1_T02_verified':False}
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except (ValueError,OSError) as e:
        print(json.dumps({'error':str(e),'actions_authorized':False},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
