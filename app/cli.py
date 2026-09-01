from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from app.core.config import get_settings
from app.db.automation_repositories import APITokenRepository
from app.db.database import Database


def local_token()->str:
    settings=get_settings();database=Database(settings.database_path,settings.backup_dir);database.initialize()
    tokens=APITokenRepository(database,settings.data_dir);tokens.ensure_default();return tokens.local_token()


def call(method:str,path:str,body:dict|None=None):
    settings=get_settings();data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(
        f"http://{settings.host}:{settings.port}/api/v1{path}",data=data,method=method,
        headers={"Authorization":f"Bearer {local_token()}","Content-Type":"application/json"},
    )
    try:
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace");raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def parser()->argparse.ArgumentParser:
    root=argparse.ArgumentParser(prog="tinix",description="Tinix local automation CLI")
    commands=root.add_subparsers(dest="command",required=True)
    commands.add_parser("token",help="In local token đã được bảo vệ trên máy này")
    commands.add_parser("health");commands.add_parser("platforms")
    for name in ("jobs","releases","content","media"):
        item=commands.add_parser(name);item.add_argument("--limit",type=int,default=50)
    for name in ("retry","cancel"):
        item=commands.add_parser(name);item.add_argument("job_id")
    schedule=commands.add_parser("schedule")
    schedule.add_argument("--content",required=True);schedule.add_argument("--account",required=True)
    schedule.add_argument("--targets",required=True,nargs="+");schedule.add_argument("--format",default="post")
    schedule.add_argument("--at");schedule.add_argument("--real",action="store_true")
    return root


def main(argv:list[str]|None=None)->int:
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    if hasattr(sys.stderr,"reconfigure"):sys.stderr.reconfigure(encoding="utf-8",errors="replace")
    args=parser().parse_args(argv)
    try:
        if args.command=="token":result={"token":local_token(),"scopes":["read","write","publish"]}
        elif args.command in {"health","platforms"}:result=call("GET",f"/{args.command}")
        elif args.command in {"jobs","releases","content","media"}:result=call("GET",f"/{args.command}?limit={args.limit}")
        elif args.command in {"retry","cancel"}:result=call("POST",f"/jobs/{args.job_id}/{args.command}",{})
        elif args.command=="schedule":
            result=call("POST","/plans",{"content_id":args.content,"account_id":args.account,"target_ids":args.targets,"scheduled_at":args.at,"dry_run":not args.real,"content_format":args.format,"platform_settings":{},"delay_seconds":0,"random_delay_seconds":0,"missed_policy":"confirm"})
        else:return 2
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as exc:print(str(exc),file=sys.stderr);return 1


if __name__=="__main__":raise SystemExit(main())
